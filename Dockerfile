# --- frontend build (Node 26)
FROM node:26-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- backend without the frontend (shared by Kartei and the DMZ relay)
FROM python:3.14-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.txt .
# python-ldap needs headers to build; the -dev packages keep the runtime libs installed
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libldap2-dev libsasl2-dev \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y gcc && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY backend/ .
RUN useradd -r -u 1000 kartei

# --- CardDAV relay for the DMZ (docker build --target relay): own SQLite file in /data, no frontend
FROM backend AS relay
ENV DJANGO_SETTINGS_MODULE=config.relay_settings RELAY_DB=/data/relay.sqlite3 HOME=/tmp
RUN mkdir /data && chown kartei /data
USER kartei
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput -v0 && exec gunicorn config.wsgi -b 0.0.0.0:8000 -k gthread -w 1 --threads 8 --access-logfile - --forwarded-allow-ips='*'"]

# --- Kartei (default target)
FROM backend
ENV FRONTEND_DIST=/app/frontend/dist EXPORT_ROOT=/export
COPY examples/ /app/examples/
COPY --from=frontend /app/frontend/dist /app/frontend/dist
RUN SECRET_KEY=build python manage.py collectstatic --noinput -v0 \
 && mkdir -p /export && chown kartei /export
USER kartei
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py init_app && exec gunicorn config.wsgi -b 0.0.0.0:8000 -k gthread -w 3 --threads 4 --access-logfile - --forwarded-allow-ips='*'"]
