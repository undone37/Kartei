#!/usr/bin/env bash
# Dynamic security scan (OWASP ZAP) of a running Kartei, built from this checkout:
#   1. baseline scan of the web app, signed in as a read-only demo user (spider + passive checks)
#   2. API scan of /api/v1 from docs/openapi.yaml with a read token (active attacks; writes are refused with 403)
# Reports land in .zap/reports/. Fails if ZAP finds anything of high risk.
# Runs in GitHub Actions (.github/workflows/zap.yml) and locally in a clean checkout without .env (Docker, curl, jq).
set -euo pipefail
cd "$(dirname "$0")/.."

ZAP_IMAGE=ghcr.io/zaproxy/zaproxy:2.17.0
PROJECT=kartei-zap
PORT=${ZAP_WEB_PORT:-18090}
PW=zap-demo-12345
export COMPOSE_PROJECT_NAME=$PROJECT COMPOSE_FILE=compose.yaml
WRK=.zap/reports
mkdir -p "$WRK" && chmod 777 "$WRK"   # ZAP runs as its own user inside the container

if [[ -f .env ]]; then
  echo "This checkout has a .env; run the scan in a clean one: git worktree add /tmp/kartei-zap && /tmp/kartei-zap/.zap/scan.sh" >&2
  exit 2
fi
cat > .env <<EOF
SECRET_KEY=$(head -c 32 /dev/urandom | base64)
ALLOWED_HOSTS=localhost,web
CSRF_TRUSTED_ORIGINS=http://localhost:$PORT,http://web:8000
POSTGRES_PASSWORD=$(head -c 16 /dev/urandom | base64 | tr -d '/+=')
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$PW
SECURE_COOKIES=0
PROXY_HEADERS=0
EOF
cleanup() {
  docker compose down -v >/dev/null 2>&1 || true
  rm -f .env
}
trap cleanup EXIT

WEB_PORT=$PORT docker compose up -d --build --wait web
docker compose exec -T web python manage.py seed_demo --password "$PW" >/dev/null

# a read token for the API scan, and a signed-in read-only user for the web app
TOKEN=$(docker compose exec -T web python manage.py shell -c "
import secrets
from kartei.models import ApiToken
t = 'kt_' + secrets.token_urlsafe(24)
ApiToken.objects.create(name='zap', scope='read', token_hash=ApiToken.digest(t))
print(t)" | tail -1)
jar=$(mktemp)
curl -sf -c "$jar" -o /dev/null "http://localhost:$PORT/api/session"
csrf=$(awk '$6 == "csrftoken" {print $7}' "$jar")
curl -sf -b "$jar" -c "$jar" -o /dev/null -H "Content-Type: application/json" -H "X-CSRFToken: $csrf" \
  -H "Referer: http://localhost:$PORT/" -d "{\"username\":\"lschmidt\",\"password\":\"$PW\"}" "http://localhost:$PORT/api/login"
SESSION=$(awk '$6 == "sessionid" {print $7}' "$jar")
rm -f "$jar"
[[ -n $SESSION && -n $TOKEN ]] || { echo "could not sign in for the scan" >&2; exit 1; }

# ZAP's replacer adds a header to every request it sends
header() { echo "-config replacer.full_list(0).description=auth -config replacer.full_list(0).enabled=true \
-config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=$1 \
-config replacer.full_list(0).regex=false -config replacer.full_list(0).replacement=$2"; }
zap() { docker run --rm --network "${PROJECT}_default" -v "$PWD/$WRK:/zap/wrk:rw" "$ZAP_IMAGE" "$@"; }

sed 's#https://kartei.example.com#http://web:8000#g' docs/openapi.yaml > "$WRK/openapi.yaml"
cp .zap/rules.tsv "$WRK/rules.tsv"

# -I: warnings don't fail the scan; the risk check below decides
zap zap-baseline.py -t http://web:8000/ -j -I -c rules.tsv -r baseline.html -J baseline.json -z "$(header Cookie "sessionid=$SESSION")"
zap zap-api-scan.py -t /zap/wrk/openapi.yaml -f openapi -I -c rules.tsv -r api.html -J api.json -z "$(header Authorization "Bearer $TOKEN")"

ignored=$(awk -F'\t' '$2 == "IGNORE" {print $1}' .zap/rules.tsv | jq -R . | jq -sc .)
high=$(jq --argjson ign "$ignored" '[.site[].alerts[] | select(.riskcode == "3" and (.pluginid | IN($ign[]) | not))] | length' \
  "$WRK/baseline.json" "$WRK/api.json" | jq -s add)
jq -r '.site[].alerts[] | "\(.riskdesc)\t\(.name)\t\(.count) x"' "$WRK/baseline.json" "$WRK/api.json" | sort -u
if (( high > 0 )); then
  echo "ZAP found $high alert(s) of high risk, see $WRK/*.html" >&2
  exit 1
fi
echo "No high-risk findings. Reports: $WRK/baseline.html, $WRK/api.html"
