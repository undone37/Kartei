---
title: Administrationshandbuch
lang: de
role: admin
other: /en/admin.html
---

# Administrationshandbuch

Dieses Handbuch richtet sich an die IT-Administration, die Kartei installiert, einrichtet und betreibt. Es beschreibt die Einrichtung mit Docker, den Betrieb (Updates, Sicherung, Logs) und alle Reiter der *Einstellungen*. Die tägliche Arbeit mit Kontakten (Suchen, Bearbeiten, Prüfungen, Vorschläge, Papierkorb) steht im [Benutzerhandbuch](user.html).

## Überblick

Kartei ist das zentrale Adressverzeichnis für Personen und Firmen. Admins legen die Felder fest, gepflegt wird in der Web-App, und Kartei gibt die Daten an andere Systeme weiter:

| Ziel | Weg | Eingerichtet unter |
|---|---|---|
| Telefone mit Exchange-Online-Postfach (iPhone und Android) | Kontaktordner in jedem Postfach, den die Outlook-App auf dem Telefon speichert | *Einstellungen → Outlook / Exchange* |
| Tischtelefone (Yealink, Snom, Grandstream) und die Anruferanzeige von Telefonanlagen | Online-Telefonbuch (XML) und Rufnummernsuche | *Einstellungen → Telefone & CardDAV* |
| Telefone ohne Postfach (z. B. Sammeltelefone) oder ohne Microsoft 365 | schreibgeschütztes CardDAV-Adressbuch (iPhone; Android braucht eine CardDAV-App) | *Einstellungen → Telefone & CardDAV* |
| Systeme, die Kontakte aus dem Active Directory lesen (z. B. Anruferkennung einer Telefonanlage, Adressbücher von Kommunikations-Clients) | AD-Kontaktobjekte in einer OU | *Einstellungen → Active Directory* |
| Skripte, andere Anwendungen, Tabellenkalkulation | CSV-/XLSX-Dateien in einem Verzeichnis | *Einstellungen → Exporte* |
| Andere Systeme (z. B. Intranet, Telefonanlage) | REST-API mit Token (nur lesen oder lesen und schreiben) | *Einstellungen → API* |

### Dienste

Kartei läuft in drei Docker-Containern (Compose-Projekt `kartei`):

| Dienst | Aufgabe |
|---|---|
| `web` | Django-Backend und Web-App auf Port 8000 (gunicorn). Führt bei jedem Start die Datenbankmigrationen aus und legt bei Bedarf den ersten Admin aus der `.env` an. |
| `exporter` | Erledigt in einer Schleife alle Hintergrundaufgaben (siehe unten). Gleiches Image wie `web`. |
| `db` | PostgreSQL 18. Die Daten liegen im Docker-Volume `pgdata`. Startet nicht, wenn Kartei einen [eigenen PostgreSQL-Server](#eigener-postgresql-server) nutzt. |

`web` und `exporter` binden beide das Exportverzeichnis des Hosts als `/export` ein.

Optional läuft auf einem eigenen Host in der DMZ ein vierter Container, der CardDAV-Relay (`compose.relay.yaml`); siehe [Relay in der DMZ](#relay-dmz).

### Hintergrundaufgaben

Der Dienst `exporter` macht alle *Export-Intervall* Minuten (*Einstellungen → Allgemein*, Standard 15) einen Durchlauf:

| Aufgabe | Läuft |
|---|---|
| Exporte mit Ausführung *automatisch* | bei jedem Durchlauf; eine Datei wird nur neu geschrieben, wenn sich ihr Inhalt geändert hat |
| Papierkorb leeren | bei jedem Durchlauf, wenn eine Aufbewahrungsdauer eingestellt ist |
| Prüfungen: geplante Prüfungen starten, Prüf-E-Mails, Erinnerungen und Vorschlags-E-Mails senden | bei jedem Durchlauf |
| Outlook-Sync | bei jedem Durchlauf, wenn aktiv; *Jetzt synchronisieren* wird nach etwa 10 Sekunden aufgegriffen |
| AD-Kontaktsync | bei jedem Durchlauf, wenn aktiv; *Jetzt synchronisieren* wird nach etwa 10 Sekunden aufgegriffen |
| Übertragung zum CardDAV-Relay in der DMZ | bei jedem Durchlauf, wenn aktiv; *Jetzt synchronisieren* wird nach etwa 10 Sekunden aufgegriffen |
| AD-Benutzerimport | einmal alle 24 Stunden, wenn ein LDAP-Server und mindestens eine Rollengruppe eingetragen sind |

Schlägt ein Durchlauf fehl, landet der Fehler im Log, und der nächste Durchlauf startet nach 5 Minuten.

> Tipp: Änderungen an den Einstellungen wirken sofort. Nach Änderungen in der Web-App musst du keinen Container neu starten.
{: .tip}

## Installation

### Voraussetzungen

- Ein Linux-Host mit Docker und dem Docker-Compose-Plugin.
- Ein DNS-Name für Kartei (z. B. `kartei.example.de`) und ein TLS-Zertifikat dafür.
- Ein Reverse Proxy für HTTPS (z. B. nginx, Apache, Traefik). HTTPS ist Pflicht: Die Sitzungs-Cookies werden nur über HTTPS übertragen, und als App (PWA) lässt sich Kartei nur über HTTPS installieren.
- Optional: eine Netzwerkfreigabe für die Exporte, auf dem Host eingehängt.

### `.env` anlegen

Aus der Umgebung kommen nur wenige Startwerte. Alles andere stellst du in der Web-App ein, gespeichert wird es in der Datenbank.

```sh
cd /opt/kartei            # das ausgecheckte Repository
cp .env.example .env
```

| Variable | Bedeutung |
|---|---|
| `SECRET_KEY` | Lange Zufallszeichenfolge. Signiert die Sitzungen und **verschlüsselt die gespeicherten Passwörter** (LDAP, AD-Schreibkonto, Outlook-Clientschlüssel, SMTP). Später nie ändern (siehe [Sicherheit](#sicherheit)). |
| `ALLOWED_HOSTS` | Hostnamen, unter denen Kartei erreichbar ist, kommagetrennt, ohne Schema: `kartei.example.de,localhost`. |
| `CSRF_TRUSTED_ORIGINS` | Vollständige Origins mit Schema (und Port, falls nicht Standard): `https://kartei.example.de`. |
| `POSTGRES_PASSWORD` | Passwort des Datenbankbenutzers `kartei` im mitgelieferten `db`-Container. |
| `DATABASE_URL`, `COMPOSE_FILE` | Nur für einen [eigenen PostgreSQL-Server](#eigener-postgresql-server). |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Erster lokaler Admin. Wird beim Start nur angelegt, wenn es überhaupt keinen aktiven Admin gibt und der Benutzername noch frei ist. |
| `EXPORT_HOST_DIR` | Host-Verzeichnis, das als `/export` eingebunden wird (Standard `./export_out`). |
| `WEB_PORT` | Veröffentlichter Port von `web` (Standard `8000`). Mit `127.0.0.1:8000` nur auf der Loopback-Schnittstelle. |
| `SECURE_COOKIES` | `1` (Standard). Nur für lokale Tests über reines HTTP auf `0` setzen. |
| `PROXY_HEADERS` | `1` (Standard): Die Absenderadresse (Sperren nach Fehlversuchen, Protokoll, erlaubte Adressen fürs Monitoring) kommt aus dem letzten Eintrag von `X-Forwarded-For`, den der Reverse Proxy anhängt. Auf `0` setzen, wenn Kartei ohne Reverse Proxy erreichbar ist. |
| `TRUSTED_PROXIES` | Adressen oder Netze, deren `X-Forwarded-For` und `X-Forwarded-Proto` zählen, durch Kommas getrennt. Standard `127.0.0.0/8,::1/128,172.16.0.0/12` (Loopback und Docker-Netze: Proxy auf demselben Host). Für einen Proxy auf einem anderen Host seine Adresse ergänzen, z. B. `10.0.5.10/32`. Die Header aller anderen werden ignoriert, sie können ihre Adresse also nicht fälschen. |
| `LOG_LEVEL` | Log-Level von `web` und `exporter` (Standard `INFO`). |
| `KARTEI_SOURCE_URL` | Link zum Quellcode unten im Benutzermenü (Standard: das Kartei-Repository). Betreibst du eine veränderte Fassung, trag hier deren Quellcode ein: Die AGPL verlangt, ihn den Benutzern anzubieten. |

Einen Schlüssel erzeugst du zum Beispiel so:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

> Achtung: Leg die `.env` in den Passwortsafe oder die Sicherung. Ohne denselben `SECRET_KEY` verliert eine wiederhergestellte Datenbank ihre gespeicherten Passwörter.
{: .warn}

### Exportverzeichnis

Exporte werden in den Containern nur unterhalb von `/export` geschrieben, auf dem Host ist das `EXPORT_HOST_DIR`. Die Container laufen mit der User-ID 1000, das Verzeichnis muss also für UID 1000 beschreibbar sein.

Das kann ein lokales Verzeichnis sein oder eine Netzwerkfreigabe, die du auf dem Host einhängst, zum Beispiel:

```sh
# .env
EXPORT_HOST_DIR=/srv/kartei-export
```

> Achtung: Ist das Verzeichnis ein Einhängepunkt, muss es eingehängt sein, bevor die Container starten. Wird es später (oder neu) eingehängt, starte die Container mit `docker compose restart web exporter` neu, sonst schreiben sie weiter in das Verzeichnis unter dem Einhängepunkt.
{: .warn}

### Eigener PostgreSQL-Server (optional) {#eigener-postgresql-server}

Standardmäßig startet Kartei einen eigenen PostgreSQL-18-Container (`db`). Betreibt deine Organisation PostgreSQL zentral – als einzelnen Server, als Cluster oder als verwaltete Cloud-Datenbank –, kann Kartei stattdessen diesen nutzen.

**Was die Datenbank braucht**

- PostgreSQL 14 oder neuer (getestet ist Kartei mit 18).
- Eine leere Datenbank mit UTF-8-Kodierung, die einer Login-Rolle für Kartei gehört. Superuser-Rechte und Erweiterungen sind nicht nötig: Kartei legt seine Tabellen bei jedem Start von `web` selbst an und aktualisiert sie.

  ```sql
  CREATE ROLE kartei LOGIN PASSWORD 'ein-langes-zufälliges-passwort';
  CREATE DATABASE kartei OWNER kartei ENCODING 'UTF8';
  ```

- Netzwerkzugriff vom Docker-Host auf den Server und ein Eintrag in der `pg_hba.conf` für diese Rolle (am besten `hostssl … scram-sha-256`).
- Verbindungen: Eine Kartei-Installation hält bis zu etwa 15 Verbindungen offen (`web`: 3 Prozesse mit je 4 Threads, dazu `exporter`); unbenutzte werden nach 10 Minuten geschlossen.

**Kartei einrichten**

Ergänze zwei Zeilen in der `.env`:

```sh
DATABASE_URL=postgres://kartei:ein-langes-zufaelliges-passwort@pg.example.de:5432/kartei?sslmode=verify-full&sslrootcert=system
COMPOSE_FILE=compose.yaml:compose.external-db.yaml
```

Danach wie gewohnt mit `docker compose up -d` starten (oder neu starten). `compose.external-db.yaml` lässt den `db`-Container weg und gibt `DATABASE_URL` an `web` und `exporter` weiter; `POSTGRES_PASSWORD` wird nicht verwendet.

| Teil der `DATABASE_URL` | Hinweise |
|---|---|
| `kartei:passwort@` | Rolle und Passwort. Sonderzeichen im Passwort prozentkodieren, z. B. `@` als `%40`, `:` als `%3A`, `/` als `%2F`. |
| `pg.example.de:5432` | Host und Port des Servers bzw. des Schreib-Endpunkts des Clusters. |
| `/kartei` | Name der Datenbank. |
| `?sslmode=…` | TLS: `verify-full` prüft Zertifikat und Hostnamen (empfohlen), `require` verschlüsselt nur, `disable` schaltet TLS ab. |
| `&sslrootcert=…` | Die Zertifizierungsstelle für `verify-full`/`verify-ca`: `system` nimmt die im Container hinterlegten Stammzertifikate (öffentliche Zertifikate, z. B. bei Cloud-Datenbanken); bei einer internen CA den Pfad einer eingebundenen Datei (siehe unten). |

Weitere PostgreSQL-Verbindungsparameter hängst du genauso an, z. B. `connect_timeout=5` oder `application_name=kartei`.

**Interne CA:** Binde das CA-Zertifikat mit einer kleinen Zusatzdatei in beide Container ein, z. B. `compose.local.yaml`:

```yaml
services:
  web:
    volumes: ["/etc/kartei/pg-ca.pem:/certs/pg-ca.pem:ro"]
  exporter:
    volumes: ["/etc/kartei/pg-ca.pem:/certs/pg-ca.pem:ro"]
```

und verwende sie in der `.env`: `COMPOSE_FILE=compose.yaml:compose.external-db.yaml:compose.local.yaml` sowie `…?sslmode=verify-full&sslrootcert=/certs/pg-ca.pem`.

**Cluster:** Kartei verbindet sich mit einer Adresse. Trag in `DATABASE_URL` den Schreib-Endpunkt des Clusters ein: eine virtuelle IP oder einen DNS-Namen, der dem Primary folgt (z. B. mit Patroni), HAProxy oder den Endpunkt einer verwalteten Datenbank. Nach einem Failover prüft Kartei jede wiederverwendete Verbindung vor der Nutzung und verbindet sich neu; höchstens die gerade laufenden Anfragen schlagen fehl. PgBouncer funktioniert im Session- und im Transaction-Pooling.

**Vom mitgelieferten Container auf einen eigenen Server umziehen**

1. Rolle und leere Datenbank auf dem neuen Server anlegen (siehe oben).
2. Kartei anhalten und die Daten kopieren:

   ```sh
   cd /opt/kartei
   docker compose stop web exporter
   docker compose exec -T db pg_dump -U kartei --no-owner kartei \
     | docker run --rm -i postgres:18 psql -q "postgres://kartei:PASSWORT@pg.example.de:5432/kartei?sslmode=require"
   ```

3. `DATABASE_URL` und `COMPOSE_FILE` wie oben in der `.env` setzen und `docker compose up -d` ausführen. Der alte `db`-Container startet nicht mehr; wenn alles läuft, entfernst du ihn samt Daten mit `docker compose -f compose.yaml rm -s db` und `docker volume rm kartei_pgdata`.

Sicherung und Wiederherstellung eines eigenen Servers übernimmt meist dessen Betrieb. Für eigene Sicherungen siehe [Sicherung](#sicherung).

### Starten

```sh
docker compose up -d --build
docker compose ps          # web sollte "healthy" werden
```

Beim ersten Start legt `web` die Datenbanktabellen, einige Standardfelder und den ersten Admin aus `ADMIN_USERNAME`/`ADMIN_PASSWORD` an.

### Reverse Proxy

Stell den TLS-Reverse-Proxy vor Port 8000. Er muss den `Host`-Header und `X-Forwarded-Proto` weitergeben, die Client-Adresse an `X-Forwarded-For` anhängen (für die Sperren nach Fehlversuchen) und darf weder die WebDAV-Methoden (`PROPFIND`, `REPORT`) noch den `Authorization`-Header filtern – beides brauchen CardDAV und die API. Beispiel für nginx:

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name kartei.example.de;
    ssl_certificate     /etc/ssl/kartei/fullchain.pem;
    ssl_certificate_key /etc/ssl/kartei/privkey.pem;
    client_max_body_size 20m;            # CSV-Import

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}

server {
    listen 80;
    server_name kartei.example.de;
    return 301 https://$host$request_uri;
}
```

Läuft der Proxy auf demselben Host, setz `WEB_PORT=127.0.0.1:8000`, damit Port 8000 aus dem Netz nicht erreichbar ist. Wer Port 8000 direkt erreicht, könnte sonst seine Adresse in `X-Forwarded-For` fälschen. Betreibst du Kartei ohne Reverse Proxy, setz `PROXY_HEADERS=0`.

### Netzwerk und Firewall {#netzwerk-und-firewall}

Ohne Einrichtung baut Kartei keine Verbindung nach außen auf: keine Telemetrie, keine Update-Prüfung, keine nachgeladenen Inhalte aus dem Internet. Jedes Ziel unten kommt erst dazu, wenn du die Funktion einrichtest, oder bei Push, wenn ein Benutzer Benachrichtigungen erlaubt. *Test*-Schaltflächen in den Einstellungen verbinden sich vom Container `web` aus, alles andere läuft im Container `exporter`.

**Microsoft 365 und Entra ID** (HTTPS, Port 443):

| Ziel | Wofür | Container |
|---|---|---|
| `login.microsoftonline.com` | Token für Microsoft Graph; Single Sign-on mit Entra ID (Discovery und Token) | `exporter`, `web` |
| `graph.microsoft.com` | Outlook-Sync (Kontakte in die Postfächer) und E-Mail-Versand über Microsoft 365 | `exporter`, `web` (Test-Mail) |

Bei Single Sign-on leitet Kartei außerdem den **Browser** zur Microsoft-Anmeldung weiter. SCIM läuft umgekehrt: Entra ID ruft Kartei auf.

**Weitere Ziele im Internet** (HTTPS, Port 443):

| Ziel | Wofür | Container |
|---|---|---|
| `fcm.googleapis.com`, `*.push.apple.com`, `*.push.services.mozilla.com`, `*.notify.windows.com` | Benachrichtigungen (Push); andere Adressen nimmt Kartei nicht an | `exporter`, `web` (*Test senden*) |
| Die Adressen unter *Einstellungen → Webhooks* | Änderungen an andere Systeme | `exporter`, `web` (Ping) |
| Ein anderer OpenID-Connect-Anbieter (z. B. Okta, Authentik) | Single Sign-on | `web` |

**Im eigenen Netz:**

| Ziel | Protokoll | Container |
|---|---|---|
| PostgreSQL (`db` oder eigener Server) | 5432 | `web`, `exporter` |
| Domain Controller / LDAP-Server | LDAP 389 oder LDAPS 636 | `web` (Anmeldung, Test), `exporter` (Benutzerimport, AD-Sync) |
| SMTP-Server | 25, 465 oder 587 | `exporter`, `web` (Test-Mail) |
| [Relay in der DMZ](#relay-dmz) | HTTPS (`…/push`) | `exporter` |
| Syslog-Server bzw. SIEM | UDP, TCP oder TLS, Port nach Einstellung | `web`, `exporter`; mit `compose.logging.yaml` auch `fluent-bit` |

Dazu kommen DNS-Abfragen über den Resolver des Docker-Hosts. Der Container `db` und das Relay bauen selbst keine Verbindungen auf. Das Relay nimmt nur Verbindungen an, von Kartei (`/push`) und von den Telefonen.

**Proxy:** Die HTTPS-Ziele beachten `HTTPS_PROXY` und `NO_PROXY` aus der `.env`. Interne HTTPS-Ziele wie das Relay gehören dann in `NO_PROXY`. LDAP, SMTP und Syslog gehen nicht über einen HTTP-Proxy und brauchen direkte Freigaben.

**Der Browser** spricht nur mit Kartei selbst; die Content-Security-Policy lässt nichts anderes zu. Ausnahmen sind die Anmeldung bei Benachrichtigungen, die der Browser direkt mit seinem Push-Dienst erledigt, und Links wie der Karten-Link, die erst beim Klick öffnen.

### Erste Anmeldung

1. Öffne `https://kartei.example.de` und melde dich mit `ADMIN_USERNAME` und `ADMIN_PASSWORD` an.
2. Öffne das Benutzermenü (Personensymbol oben rechts) → *Mein Konto* und ändere das Passwort.
3. Entferne `ADMIN_PASSWORD` aus der `.env`. Es wird nicht mehr gebraucht: Kartei verwendet es nur, solange es keinen aktiven Admin gibt.

In die Administration kommst du über das Benutzermenü → *Einstellungen*.

![Benutzermenü mit Einstellungen](../img/de/user-menu-admin.png)

## Betrieb

### Update

1. Mach eine Sicherung (siehe unten).
2. Hol die neue Version und baue neu:

   ```sh
   cd /opt/kartei
   git pull
   docker compose up -d --build
   ```

3. Prüf mit `docker compose ps`, ob `web` wieder „healthy“ ist. Die Migrationen laufen beim Start von `web` automatisch; `exporter` wartet darauf.

### Sicherung {#sicherung}

Kartei sichert seine Datenbank selbst: jeden Tag zur Uhrzeit unter *Einstellungen → Sicherung* (Standard 02:30), aufbewahrt für die dort eingestellten Tage (Standard 14; die neueste Sicherung bleibt immer). Die Datenbank enthält alles: Kontakte, Fotos, Felder, Benutzer, Einstellungen, Verlauf und Protokoll. Die Exportdateien lassen sich jederzeit mit *Jetzt ausführen* neu erzeugen.

![Reiter Sicherung](../img/de/settings-backup.png)

- **Wohin:** Der `exporter` schreibt die Dateien (`kartei-<Datum>-<Uhrzeit>.dump`, das komprimierte Custom-Format von PostgreSQL) nach `/backup`. Standardmäßig ist das das Docker-Volume `backups`. Das funktioniert ohne weitere Einrichtung, liegt aber auf derselben Platte wie die Datenbank. Besser: ein Verzeichnis auf anderem Speicher, z. B. ein NAS-Mount, als `BACKUP_HOST_DIR` in der `.env` (Eigentümer uid 1000: `chown 1000 /mnt/backup/kartei`). Nimm nicht die Export-Freigabe: Wer Exporte lesen darf, bekäme die ganze Datenbank.
- **Geprüft:** Jede Datei wird zurückgelesen (`pg_restore --list`), bevor sie zählt. *Wiederherstellung testen* spielt die neueste Sicherung in eine Testdatenbank (`kartei_restore_test`) ein, zählt Kontakte, Felder, Benutzer und Protokolleinträge, vergleicht sie mit der laufenden Datenbank und löscht die Testdatenbank wieder. Bei einem eigenen PostgreSQL-Server braucht der Datenbankbenutzer dafür das Recht, Datenbanken anzulegen (`CREATEDB`).
- **Überwacht:** Der [Monitoring-Status](#monitoring) meldet `backup` als *warn* nach 26 Stunden ohne Sicherung und als *crit* nach 50 Stunden oder bei einem Fehler, `restore_test` als *warn*, wenn der letzte Test fehlgeschlagen ist.
- **Jetzt sichern** schreibt sofort eine Sicherung (auch bei ausgeschalteter täglicher Sicherung).
- **Sichere einmalig auch die `.env`** (sie enthält den `SECRET_KEY`) und kopiere das Sicherungsverzeichnis vom Host weg, falls es nicht ohnehin auf anderem Speicher liegt.

Kartei verschlüsselt die Dateien nicht; schütze das Sicherungsverzeichnis wie die Datenbank selbst.

Mit einem [eigenen PostgreSQL-Server](#eigener-postgresql-server) funktioniert die eingebaute Sicherung genauso (der `exporter` verbindet sich über `DATABASE_URL`). Du kannst stattdessen auch eure üblichen PostgreSQL-Werkzeuge nehmen und die tägliche Sicherung ausschalten.

### Wiederherstellung

Eine Sicherung spielst du mit dem `pg_restore` aus dem Kartei-Image zurück. Das geht für die mitgelieferte Datenbank und einen eigenen Server gleichermaßen:

```sh
cd /opt/kartei
docker compose stop web exporter
docker compose run --rm --no-deps exporter \
  sh -c 'pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" /backup/kartei-20261107-023000.dump'
docker compose start web exporter
```

`docker compose run --rm --no-deps exporter ls -l /backup` listet die vorhandenen Dateien. Verwende dieselbe `.env` (denselben `SECRET_KEY`) wie das System, von dem die Sicherung stammt. Ältere Sicherungen aus einem Cronjob (`.sql.gz`) spielst du wie bisher ein: `gunzip -c datei.sql.gz | docker compose exec -T db psql -q -U kartei -d kartei` in eine leere Datenbank.

### Logs

```sh
docker compose logs -f web          # Anfragen, Anmeldefehler
docker compose logs -f exporter     # Exporte, Syncs, Prüfungen, Benutzerimport
docker compose logs --since 1h exporter
```

Der `exporter` schreibt pro Export, Sync und Benutzerimport eine Zeile. Die Ergebnisse siehst du außerdem im jeweiligen Reiter der Einstellungen (*Letzter Lauf*).

Die Logzeilen sind JSON, ein Objekt pro Zeile (`ts`, `level`, `logger`, `msg` und Details wie `http` bei Anfragen oder `audit` bei Protokolleinträgen), damit Log-Shipper und SIEM sie auswerten können. Für Klartextzeilen setzt du `LOG_FORMAT=text` in der `.env`; `LOG_LEVEL` (Standard `INFO`) bestimmt die Ausführlichkeit. Logs an ein SIEM weiterleiten: siehe [Monitoring und Protokolle](#monitoring).

### Healthcheck

- `docker compose ps` zeigt den Zustand von `web` (fragt alle 10 Sekunden `/healthz` ab) und `db`.
- Für ein externes Monitoring nimmst du `/readyz` und den ausführlichen Status, siehe [Monitoring und Protokolle](#monitoring).

### Kommandozeile

Einige Aufgaben gibt es auch als Management-Befehl. Ohne `--commit` zeigen sie nur an, was sie tun würden.

```sh
docker compose exec web python manage.py import_csv /export/kontakte.csv [--mapping z.json] [--commit]   # CSV-Import
docker compose exec web python manage.py normalize_phones [--commit]                    # Telefonnummern
docker compose exec web python manage.py changepassword admin                           # lokales Passwort zurücksetzen
docker compose exec web python manage.py reset_2fa admin                                # 2FA eines Benutzers abschalten
```

`reset_2fa` ist für einen verlorenen Authenticator ohne Wiederherstellungscodes, vor allem beim einzigen Admin (sonst setzt ein Admin ihn unter *Benutzer* zurück). Der Benutzer meldet sich danach mit dem Passwort an und richtet die Zwei-Faktor-Anmeldung neu ein, sofort, wenn sie Pflicht ist. Änderungen von der Kommandozeile erscheinen im Protokoll als Benutzer *system*.

## Erste Schritte

Arbeite nach der Installation die *Einstellungen* in dieser Reihenfolge ab:

1. **LDAP / AD:** Server, Dienstkonto, je Rolle eine Gruppe, dann *Speichern & testen* und *Speichern & Benutzer jetzt importieren*. So gibt es die Benutzer schon, bevor du Daten importierst, und Benutzerfelder in den importierten Daten werden zugeordnet.
2. **Felder:** die benötigten Felder anlegen oder per *Felder importieren* aus einer JSON-Datei laden (z. B. `examples/fields-example.json`), danach Bezeichnungen, Sichtbarkeit und Reihenfolge anpassen.
3. **Import:** Wenn du von einem anderen System umziehst, dessen CSV-Export hochladen, Spaltenzuordnung und *Probelauf* prüfen, dann *Import ausführen*.
4. **Allgemein:** Standardsprache, *Öffentliche Adresse*, Aufbewahrung im Papierkorb, Export-Intervall, Telefonnummern (nach dem Import einmal *Bestehende Nummern prüfen*).
5. **Exporte:** die Dateien einrichten, die andere Systeme brauchen, Pfade und Spalten prüfen, Exporte aktivieren und einmal *Jetzt ausführen*.
6. **Active Directory:** Ziel-OU und Zuordnung, *Speichern & Probelauf*, dann aktivieren.
7. **CardDAV** (optional, für Telefone ohne Postfach): aktivieren, Passwort erzeugen, Telefone einrichten.
8. **Outlook / Exchange** (Telefone mit Exchange-Online-Postfach): App-Registrierung in Entra ID, *Speichern & testen*, aktivieren.
9. **E-Mail** und **Prüfung:** SMTP-Server oder Microsoft 365 mit Test-E-Mail, die E-Mail-Texte, danach den Prüfmodus.
10. **API:** bei Bedarf Token für andere Systeme erzeugen.

## Benutzer und Rollen

### Rollen

Kartei hat drei feste Rollen:

| Rolle | Darf |
|---|---|
| Nur Lesen | ansehen, suchen und Listen exportieren; eigene Prüfungen bestätigen; Änderungen und Löschungen vorschlagen |
| Bearbeiter | zusätzlich Kontakte anlegen, bearbeiten, gesammelt bearbeiten, löschen (in den Papierkorb) und wiederherstellen; Vorschläge übernehmen oder ablehnen; Dubletten zusammenführen; *Datenqualität* und letzte Änderungen sehen |
| Admin | zusätzlich endgültig aus dem Papierkorb löschen, Prüfungen für einzelne Kontakte anfordern und alles unter *Einstellungen* |

Zusätzlich lässt sich jedes Feld auf *Bearbeiter & Admin* oder *Nur Admin* beschränken, getrennt fürs Ansehen und Bearbeiten (siehe [Felder](#felder)).

### Lokale und LDAP-Benutzer

| | Lokaler Benutzer | LDAP-Benutzer |
|---|---|---|
| Angelegt durch | einen Admin (*Lokaler Benutzer*) oder die `.env` (erster Admin) | den Benutzerimport oder die erste Anmeldung |
| Passwort | in Kartei (mindestens 10 Zeichen) | im Active Directory |
| Rolle | in der Liste einstellbar | ergibt sich bei jeder Anmeldung und jedem Import aus den AD-Gruppen |
| Aktiv | Kästchen in der Liste | entscheidet das AD: Mitglied einer Rollengruppe und Konto aktiviert |
| Name und E-Mail | pflegt der Admin | kommen aus dem AD (`givenName`, `sn`, `mail`) |

Lokale Benutzer bleiben als Rückfallebene erhalten, falls das Verzeichnis nicht erreichbar ist. Ein lokaler Benutzer hat immer Vorrang: Ein AD-Konto mit demselben Benutzernamen kann sich nicht anmelden.

Eine dritte Art, *SCIM-Benutzer*, legt ein Identity-Provider an und verwaltet sie; siehe [Single Sign-on](#sso).

![Reiter Benutzer](../img/de/settings-users.png)

### Lokale Benutzer verwalten

*Einstellungen → Benutzer*:

- **Anlegen:** *Lokaler Benutzer* → *Benutzername*, *Passwort* (mindestens 10 Zeichen), optional Vor- und Nachname, *E-Mail* und *Rolle* eingeben → *Anlegen*. Für Prüf-E-Mails braucht der Benutzer eine E-Mail-Adresse.
- **Rolle ändern:** in der Spalte *Rolle* auswählen, das wirkt sofort.
- **Passwort zurücksetzen:** Schlüsselsymbol (*Passwort setzen*) → neues Passwort eingeben → *Speichern*.
- **Deaktivieren:** Haken bei *Aktiv* entfernen. Der Benutzer kann sich nicht mehr anmelden, bleibt aber in der Liste und in den Benutzerfeldern der Kontakte (als inaktiv markiert), bis du sie [übergibst](#leavers). Das ist meist besser als Löschen.
- **Zwei-Faktor-Anmeldung:** schalten die Benutzer selbst unter *Mein Konto* ein; die Liste kennzeichnet sie mit **2FA**. Hat jemand Handy und Wiederherstellungscodes verloren, schaltet das Schildsymbol (*Zwei-Faktor-Anmeldung zurücksetzen*) sie nach einer Rückfrage ab, sodass wieder das Passwort reicht (prüf die Anfrage vorher). Gilt für lokale und LDAP-Benutzer. Zur Pflicht machen: *Zwei-Faktor-Anmeldung Pflicht für* unter [Allgemeine Einstellungen](#allgemeine-einstellungen).
- **Löschen:** Papierkorbsymbol, dann im Dialog bestätigen. Das Konto kann sich nicht mehr anmelden, und seine eigenen gespeicherten Filter (auch geteilte) werden gelöscht; erst möglich, wenn kein Kontakt den Benutzer mehr nennt (vorher [übergeben](#leavers)). AD-Benutzer kommen beim nächsten Benutzerimport wieder, solange sie in einer Rollengruppe sind. Dich selbst kannst du nicht löschen.

> Hinweis: Der letzte aktive Admin lässt sich weder herabstufen noch deaktivieren oder löschen (*Der letzte Admin kann nicht entfernt werden*). Der erste Admin aus der `.env` ist ein Superuser (Tooltip *Hauptadministrator (Superuser) – immer Admin*); seine Rolle lässt sich in der Liste nicht ändern.
{: .tip}

### LDAP-Benutzer

Bei LDAP-Benutzern (*Herkunft* `LDAP`) sind *Rolle*, *Aktiv* und das Passwort gesperrt. Das änderst du im AD:

- Benutzer in die Rollengruppen aufnehmen oder daraus entfernen,
- AD-Konto deaktivieren oder aktivieren.

Die Änderung greift bei der nächsten Anmeldung oder beim nächsten Benutzerimport (täglich oder per *Speichern & Benutzer jetzt importieren*). Wer in keiner Rollengruppe mehr ist, wird **deaktiviert, nicht gelöscht** – so bleibt der Name an den Kontakten sichtbar, für die er zuständig war. Kommt er wieder in eine Gruppe, wird er reaktiviert.

### Wenn jemand das Unternehmen verlässt {#leavers}

Deaktivieren (lokale Benutzer) oder aus den Rollengruppen entfernen (LDAP-Benutzer; der nächste Benutzerimport deaktiviert sie). Anmelden geht dann nicht mehr; eine offene Sitzung endet mit der nächsten Anfrage.

- **Der Verlauf bleibt vollständig.** Jeder Eintrag im Protokoll und im Verlauf behält den Namen dessen, der die Änderung gemacht hat – auch nach dem Löschen des Kontos.
- **Kontakte übergeben.** Die Benutzerliste markiert Ausgeschiedene, die noch in Kontakten eingetragen sind (*N Kontakte zu übergeben*). *Übergeben …* (Pfeil-Symbol) zeigt, wie viele Kontakte und offene Überprüfungen betroffen sind; Nachfolge auswählen und bestätigen. Die Nachfolge übernimmt in allen Benutzerfeldern (Verantwortliche, interne Kontakte); offene Überprüfungen gehen an die neue Verantwortliche. Jede Änderung steht im Verlauf des Kontakts, als Übergabe gekennzeichnet. Das geht auch bei aktiven Benutzern, z. B. nach einem Stellenwechsel.
- **Offene Überprüfungen** Ausgeschiedener bleiben bis zur Übergabe offen; Kartei schickt ihnen keine Mails mehr.
- **Vorschläge** von ihnen bleiben offen; Bearbeiter entscheiden wie gewohnt.
- **API-Tokens und Webhooks** gehören Kartei, nicht dem Admin, der sie angelegt hat, und funktionieren weiter.
- **Löschen** lässt sich ein Konto erst, wenn kein Kontakt es mehr nennt (*vorher übergeben*).

![Kontakte einer ausgeschiedenen Person übergeben](../img/de/settings-handover.png)

## Anmeldung über LDAP / AD

Unter *Einstellungen → LDAP / AD* verbindest du Kartei mit dem Active Directory. Die Benutzer melden sich dann mit ihrem AD-Benutzernamen und -Passwort an. Bleibt *Server* leer, ist LDAP aus, und nur lokale Benutzer können sich anmelden.

![Reiter LDAP / AD](../img/de/settings-ldap.png)

### Verbindung

| Einstellung | Beispiel | Hinweise |
|---|---|---|
| *Server* | `ldaps://dc01.example.local` | LDAPS auf Port 636, oder `ldap://dc01.example.local` zusammen mit *StartTLS*. |
| *StartTLS* | | Nur mit `ldap://`, nicht mit `ldaps://` kombinieren. |
| *Dienstkonto (Bind-DN)* | `CN=svc-kartei,OU=Service,DC=example,DC=local` | Ein normaler Domänenbenutzer reicht; er liest nur. |
| *Passwort Dienstkonto* | | Wird verschlüsselt gespeichert. Das Feld bleibt nach dem Speichern leer; lässt du es leer, bleibt das gespeicherte Passwort erhalten. |
| *Benutzer-Suchbasis* | `OU=Users,DC=example,DC=local` | Alle Benutzer, die sich anmelden sollen, müssen darunter liegen. |
| *Benutzerfilter* | `(sAMAccountName=%(user)s)` | Muss `%(user)s` enthalten. Das Attribut im Filter ist gleichzeitig der Benutzername in Kartei. |
| *CA-Zertifikat (PEM, optional)* | `-----BEGIN CERTIFICATE-----…` | Die Stammzertifizierungsstelle der Domänencontroller-Zertifikate, wenn sie von einer internen CA stammen. Ist es gesetzt, wird das Serverzertifikat immer dagegen geprüft. |

> Achtung: Verwende kein unverschlüsseltes `ldap://` ohne *StartTLS* – die Passwörter der Benutzer gingen sonst im Klartext übers Netz.
{: .warn}

### Gruppen und Rollen

Unter *Gruppen → Rollen* trägst du für jede Rolle (*Admin*, *Bearbeiter*, *Nur Lesen*) den Distinguished Name einer AD-Gruppe ein. Leere Felder werden nicht verwendet.

- **Verschachtelte Gruppen zählen:** Wer Mitglied einer Gruppe in der Rollengruppe ist, bekommt die Rolle ebenfalls.
- **Die höchste Rolle gewinnt**, wenn jemand in mehreren Gruppen ist.
- **Ohne Gruppe kein Zugang:** AD-Benutzer, die in keiner der Gruppen sind, können sich nicht anmelden.
- Die Rolle wird bei jeder Anmeldung neu bestimmt; Änderungen im AD wirken also spätestens bei der nächsten Anmeldung.

### Speichern & testen

1. Trag die Einstellungen ein.
2. Gib optional unter *Testbenutzer (optional)* einen Benutzernamen ein.
3. Klick auf *Speichern & testen*.

Das Ergebnis zeigt, ob Verbindung und Anmeldung des Dienstkontos geklappt haben, und für den Testbenutzer den DN und die Rolle, die Kartei vergeben würde (*keine – Anmeldung würde abgelehnt*, wenn keine Gruppe passt). Verschachtelte Gruppen werden dabei genauso aufgelöst wie bei der Anmeldung.

### Benutzer vorab importieren

*Speichern & Benutzer jetzt importieren* legt alle Mitglieder der drei Gruppen (auch verschachtelt) als LDAP-Benutzer an. So kannst du sie schon vor ihrer ersten Anmeldung als *Ansprechpartner intern* auswählen. Der Import läuft außerdem einmal täglich automatisch.

- Deaktivierte AD-Konten werden übersprungen (und damit in Kartei deaktiviert).
- Wer alle Gruppen verlassen hat, wird deaktiviert, nicht gelöscht.
- Ein umbenanntes AD-Konto (neuer `sAMAccountName`) bleibt derselbe Kartei-Benutzer: Kartei erkennt es an seiner `objectGUID` (bzw. `entryUUID`), übernimmt den neuen Namen und passt die Kontakte an, die den Benutzer nennen. Über den Namen wird nur zugeordnet, bis die Verzeichnis-ID bekannt ist (beim ersten Import oder der ersten Anmeldung nach dem Update).
- Lokale Benutzer bleiben unberührt; ein AD-Konto mit dem Namen eines lokalen Benutzers zählt als *lokale übersprungen*.
- Werden gar keine Mitglieder gefunden (z. B. falsche Suchbasis), ändert sich nichts und es erscheint ein Fehler – ein Tippfehler kann also nicht alle Benutzer deaktivieren.
- *Höchstens deaktivieren (% der Verzeichnisbenutzer pro Lauf)* (Standard 20): Würden mehr Benutzer deaktiviert, z. B. nach dem Umbenennen einer Rollengruppe, bricht der Lauf ohne Änderung ab und zeigt die Zahl. Bis zu zwei Benutzer dürfen immer gehen. Ist die Änderung gewollt, erhöhe die Grenze für einen Lauf.

Das Feld unter der Schaltfläche zeigt den letzten Lauf: *neu · aktualisiert · deaktiviert · lokale übersprungen* oder den Fehler.

## Single Sign-on (SCIM und OpenID Connect) {#sso}

*Einstellungen → Single Sign-on* verbindet Kartei mit einem Identity-Provider wie Entra ID, Okta, Authentik oder Keycloak (mit SCIM-Plugin). Der Provider **legt die Benutzer vorab per SCIM an** (mit ihren Gruppen), und sie **melden sich mit OpenID Connect an** – so gelten seine Mehrfaktor-Authentifizierung und Richtlinien, und kein Passwort erreicht Kartei. Lokale Benutzer und LDAP funktionieren weiter.

![Der Reiter Single Sign-on](../img/de/settings-sso.png)

### Bereitstellung (SCIM 2.0)

1. Unter *Bereitstellung (SCIM 2.0)* die *SCIM-Basis-URL* (`https://kartei.example.com/scim/v2`) kopieren und *Token erzeugen* klicken. Das Token wird **einmal** angezeigt; ein neues Token ersetzt das alte. Neben der Schaltfläche zeigt *Letzter Kontakt vom Identitätsanbieter*, wann er Kartei zuletzt aufgerufen hat – ein schneller Check, ob die Bereitstellung läuft.
2. Im Identity-Provider für die App die Bereitstellung mit dieser URL und dem Token als Bearer-Token einrichten (Entra ID: *Unternehmensanwendung → Bereitstellung → Automatisch*, *Mandanten-URL* und *Geheimes Token*). Die Benutzer und Gruppen zuweisen, die Kartei bekommen sollen.
3. Sobald die ersten Gruppen angekommen sind, sie unter *Rollen aus Gruppen* den Rollen *Admin*, *Bearbeiter* und *Nur Lesen* zuordnen und speichern.

- Ein SCIM-Benutzer ist **aktiv**, wenn der Provider es sagt und eine seiner Gruppen eine Rolle hat; die höchste Rolle gilt. Benutzer ohne zugeordnete Gruppe sind inaktiv.
- Name, E-Mail, Rolle und *Aktiv* von SCIM-Benutzern (*Quelle* `SCIM`) sind in der Benutzerliste ausgegraut; das entscheidet der Provider. Sie haben kein Kartei-Passwort.
- Austritte: Deaktiviert oder löscht der Provider einen Benutzer, **deaktiviert** Kartei ihn und löscht ihn nie – so behalten die Historie und die Kontakte, für die er zuständig ist, seinen Namen.
- Benennt der Provider einen Benutzer um (`userName`), ziehen die Kontakte, die ihn nennen, automatisch mit.
- SCIM sieht nur Benutzer, die es selbst angelegt hat: Lokale und LDAP-Benutzer werden nie geändert, und ein SCIM-Benutzer kann keinen schon vorhandenen Namen bekommen.
- Den letzten aktiven Admin deaktiviert oder herabstuft SCIM nie.
- Jede Änderung durch den Provider steht im Protokoll als *SCIM*.

Endpunkte: `/Users` und `/Groups` mit `GET` (Filter `userName eq`, `externalId eq`, `displayName eq`), `POST`, `PUT`, `PATCH` und `DELETE`, dazu `/ServiceProviderConfig`, `/ResourceTypes` und `/Schemas`.

### Anmeldung (OpenID Connect)

| Einstellung | Hinweise |
|---|---|
| *Aussteller-URL (Issuer)* | Kartei liest die Endpunkte aus `<Issuer>/.well-known/openid-configuration`; der Issuer dort muss genau diese URL sein. |
| *Client-ID*, *Client-Geheimnis* | Von der im Provider registrierten App (vertraulicher Web-Client). Das Geheimnis wird verschlüsselt gespeichert. |
| *Scopes* | Standard `openid profile email`. |
| *Claim für die erste Anmeldung* | `preferred_username` (Standard), `upn` oder `email`. |
| *Text der Schaltfläche auf der Anmeldeseite* | Leer = *Mit Single Sign-on anmelden*. |
| *Umleitungs-URI* | Im Provider eintragen: `https://kartei.example.com/api/oidc/callback` (braucht die *Öffentliche Adresse* unter *Allgemein*). |

Issuer-URLs gängiger Provider:

| Provider | Issuer-URL |
|---|---|
| Entra ID | `https://login.microsoftonline.com/<Tenant-ID>/v2.0` (die Tenant-ID, nicht `common` oder `organizations`) |
| Keycloak | `https://id.example.com/realms/<Realm>` |
| Authentik | `https://id.example.com/application/o/<Anwendungs-Slug>/` |
| Okta | `https://<Org>.okta.com` (oder ein eigener Autorisierungsserver) |

Wer sich anmelden kann:

- Nur **aktive SCIM- oder LDAP-Benutzer**, nie lokale Benutzer oder Superuser. Bei der Anmeldung wird niemand angelegt.
- Beim ersten Mal muss der gewählte Claim dem Benutzernamen genau eines SCIM-Benutzers (oder der Verzeichnis-E-Mail eines LDAP-Benutzers) entsprechen. Teiltreffer gibt es nicht.
- Danach speichert Kartei Aussteller und Subject (`sub`) des Kontos; ab dann zählen nur noch diese – ein umbenanntes Konto kommt weiter hinein, ein anderes Konto mit gleichem Namen nicht.
- Bei Entra ID werden Gäste aus anderen Verzeichnissen abgewiesen.
- Die Anmeldung nutzt den Autorisierungscode-Fluss mit PKCE; Kartei prüft Aussteller, Empfänger, Ablauf und Nonce des ID-Tokens. Jede Anmeldung steht im Protokoll.

**Zwei-Faktor-Anmeldung und Single Sign-on:** Die Mehrfaktor-Authentifizierung des Providers ersetzt die von Kartei nicht. Hat ein Konto die Zwei-Faktor-Anmeldung eingeschaltet (oder ist sie [Pflicht](#allgemeine-einstellungen)), fragt Kartei nach dem Provider den Code ab. SCIM-Benutzer haben kein Kartei-Passwort: Zum Einschalten brauchen sie stattdessen eine Single-Sign-on-Anmeldung in den letzten 10 Minuten. Erzwingt der Provider bei jeder Anmeldung an Kartei MFA (z. B. per Richtlinie für bedingten Zugriff), schalte *Mehrfaktor-Authentifizierung des Providers zählt* ein: Dann fragt Kartei nach Single Sign-on keinen Code ab, und *Zwei-Faktor-Anmeldung Pflicht für* gilt für diese Sitzungen nicht. Anmeldungen mit Passwort brauchen weiterhin den Kartei-Code.

## Felder

Bis auf die Stammfelder (Vor- und Nachname, Firmenname, Firmenzuordnung und Bild) legen Admins alle Kontaktfelder unter *Einstellungen → Felder* fest.

![Reiter Felder](../img/de/settings-fields.png)

### Feldliste

- Die Chips *Alle*, *Personen*, *Firmen* filtern die Liste; *Archivierte zeigen* blendet archivierte Felder ein.
- Die Liste ist nach **Abschnitten** gruppiert, in deren Reihenfolge; Felder ohne Abschnitt stehen am Ende unter *Weitere*.
- Zieh eine Zeile am Griff, um die Reihenfolge zu ändern – auch in einen anderen Abschnitt (auf ein Feld oder auf eine Abschnittsüberschrift ziehen). Die Reihenfolge gilt für die Formulare und die Detailansicht.
- Ein Klick auf eine Zeile öffnet rechts den Editor; *Neues Feld* öffnet einen leeren.
- Der kleine graue Text unter der Bezeichnung ist der **Schlüssel** des Felds. Er wird beim Anlegen aus der englischen Bezeichnung gebildet und ändert sich danach nicht mehr. API, Exporte und Import sprechen Felder über diesen Schlüssel an.

### Abschnitte

Abschnitte gruppieren die Felder im Kontaktformular und in der Detailansicht. **Abschnitte** in der Werkzeugleiste öffnet rechts die Abschnittsverwaltung:

![Abschnitte verwalten](../img/de/settings-sections.png)

- Zum Umbenennen änderst du die deutsche oder englische Bezeichnung; gespeichert wird beim Verlassen des Eingabefelds.
- Die Pfeile ändern die Reihenfolge der Abschnitte. Formular und Detailansicht zeigen die Abschnitte in dieser Reihenfolge, die Felder innerhalb eines Abschnitts in der Feldreihenfolge.
- Neue Abschnitte legst du mit den Eingabefeldern unten an (eine Sprache reicht, die andere bekommt denselben Text).
- Der kleine graue Text ist der **Schlüssel** des Abschnitts. Wie bei Feldern wird er beim Anlegen gebildet und ändert sich nicht; Felddateien sprechen Abschnitte über ihn an. Der Abschnitt mit dem Schlüssel `person` (bzw. `company`) erscheint im Kopf des Personen- (bzw. Firmen-)formulars neben dem Namen.
- Einen Abschnitt, den noch aktive Felder verwenden, kannst du nicht einfach löschen: Wähl einen Abschnitt (oder *Weitere*), in den seine Felder wandern, dann *Verschieben und löschen*. Archivierte Felder eines gelöschten Abschnitts landen unter *Weitere*.

Jede Änderung an Abschnitten steht im Protokoll.

### Feldeinstellungen

| Einstellung | Bedeutung |
|---|---|
| *Bezeichnung* (DE/EN) | Beide sind Pflicht. |
| *Hilfetext* (DE/EN) | Erscheint unter dem Eingabefeld und als Tooltip in der Ansicht. |
| *Typ* | Siehe unten. |
| *Gilt für* | *Personen*, *Firmen* oder *Personen & Firmen*. |
| *Minimum*, *Maximum*, *Nachkommastellen* | Bei *Ganzzahl* und *Dezimalzahl*. |
| *Auswahlwerte* | Bei *Einfachauswahl* und *Mehrfachauswahl*: *Wert* (wird gespeichert) und die Beschriftungen DE/EN; Reihenfolge über die Pfeile. |
| *Bearbeiter dürfen beim Eingeben neue Optionen anlegen* | Auswahlfelder: Neue Werte lassen sich direkt im Formular ergänzen (z. B. Schlagworte). |
| *Im Schnellfilter der Liste anbieten* | Auswahl- und Benutzerfelder: Das Feld erscheint im Feldfilter (Trichter) über der Kontaktliste. Schalte es nur für Felder ein, nach denen wirklich gefiltert wird (z. B. Schlagworte, interne Kontakte); im erweiterten Filter stehen ohnehin alle Felder zur Verfügung. |
| *Freitext erlauben (Name ohne eigenen Kontakt)* | Felder vom Typ *Kontakt*: nehmen auch einen eingetippten Namen an. |
| *Format (regulärer Ausdruck)* | Bei *Text*, *Langer Text*, *Telefon*, *E-Mail* und *Webadresse*: Der gesamte Wert muss passen. Schaltflächen fügen gängige Muster ein (*PLZ (DE)*, IBAN …); ein Testwert zeigt *passt* oder *passt nicht*. Geprüft wird im Formular, auf dem Server und beim Import. Leere Werte werden nicht geprüft. |
| *Abschnitt* | Gruppiert die Felder in Formular und Ansicht. Wähl einen vorhandenen Abschnitt oder tipp einen neuen Namen und wähl *Abschnitt … anlegen*; leer = *Weitere*. |
| *Sichtbar für* | *Alle*, *Bearbeiter & Admin* oder *Nur Admin*. |
| *Bearbeitbar durch* | *Bearbeiter & Admin* oder *Nur Admin*. |
| *Pflichtfeld* | Das Feld muss beim Speichern ausgefüllt sein. |
| *Durchsuchbar* | Der Wert wird von der Suche gefunden. |
| *vCard-Zuordnung* | Wohin der Wert in der vCard kommt (CardDAV, Outlook-Sync, vCard-Download). Zuordnungen mit eigener Beschriftung (z. B. *Telefon mit eigener Beschriftung*) brauchen zusätzlich *vCard-Typ / Beschriftung*, etwa `Zentrale`. |
| *Import-Spaltennamen* | Weitere Spaltenüberschriften, die der CSV-Import diesem Feld zuordnet, kommagetrennt (z. B. `Tel.`, `Telefon geschäftlich`). |
| *Von Firma übernehmen aus* | Nur bei Personen: Beim Zuordnen einer Firma bietet das Formular an, den Wert aus dem gewählten Firmenfeld zu übernehmen (z. B. Adresse, Webseite). Wird auch genutzt, wenn Firmenänderungen auf die Mitarbeiter übertragen werden. |

![Feld-Editor](../img/de/settings-field-editor.png)

> Achtung: Nur Felder, die für *Alle* sichtbar sind, landen auf den Telefonen (CardDAV, Outlook-Sync) und in der API. Exporte und der AD-Sync werden getrennt eingerichtet und können jedes Feld enthalten.
{: .warn}

### Feldtypen

| Typ | Verwendung |
|---|---|
| *Text*, *Langer Text* | Freitext; *Langer Text* ist mehrzeilig. |
| *Ganzzahl*, *Dezimalzahl* | Zahlen mit optionalen Grenzen. |
| *Einfachauswahl*, *Mehrfachauswahl* | Feste Werte, im Formular als durchsuchbare Liste. |
| *Telefon*, *E-Mail*, *Webadresse* | Geprüft und anklickbar; Telefonnummern werden vereinheitlicht (siehe [Allgemein](#allgemeine-einstellungen)). |
| *Datum*, *Ja/Nein* | Echte Datums- und Ja/Nein-Werte (auch in Excel richtig typisiert). |
| *Benutzer* | Ein Kartei-Benutzer, z. B. der interne Zuständige. Das **erste** Feld vom Typ *Benutzer* bestimmt, wer den Kontakt prüft. Administratoren und inaktive Benutzer werden nicht angeboten; ein früher eingetragener Wert bleibt erhalten. |
| *Mehrere Benutzer* | Mehrere Kartei-Benutzer, z. B. interne Kontakte. Auch hier werden Administratoren und inaktive Benutzer nicht angeboten. |
| *Kontakt (Person der Firma)* | Verweist auf eine Person derselben Firma, z. B. den Geschäftsführer. Die verknüpfte Person zeigt den Kontakt unter *Verknüpft mit*. Mit der vCard-Zuordnung *Beziehung: Vorgesetzte(r)* (`related_manager`) bedeutet das Feld „berichtet an“: Firmen bekommen dann den Reiter **Organigramm**, der daraus entsteht (der Beispiel-Feldbestand hat es als *Vorgesetzter*). |

Exporte, vCards und der AD-Sync zeigen die Namen der Benutzer und verknüpften Personen, nicht ihre IDs.

### Typ ändern

Solange kein Kontakt einen Wert im Feld hat, ist jeder Typwechsel möglich. Mit Daten sind nur diese Wechsel erlaubt:

- *Text* ↔ *Langer Text*
- *Telefon*, *E-Mail*, *Webadresse* → *Text*
- *Ganzzahl* → *Dezimalzahl*
- *Einfachauswahl* → *Mehrfachauswahl* und *Benutzer* → *Mehrere Benutzer* (vorhandene Werte werden in Listen umgewandelt)
- *Text* → *Kontakt* (Freitext wird eingeschaltet, damit die alten Werte gültig bleiben)

Andere Wechsel lehnt Kartei mit *Typwechsel nicht möglich, da bereits Daten vorhanden sind* ab.

### Archivieren und löschen

- *Archivieren* blendet das Feld nach einer Rückfrage überall aus (Formulare, Kontaktansicht, Suche, Filter, CardDAV, Outlook, Importe). Die Daten bleiben erhalten, *Wiederherstellen* holt es zurück.
- *Löschen* gibt es nur bei archivierten Feldern und fragt vorher nach (*Feld … endgültig löschen?*). Es klappt nur, wenn kein Kontakt, auch keiner im Papierkorb, einen Wert darin hat; sonst erscheint *Feld enthält Daten – bitte archivieren statt löschen*. Löschen lässt sich nicht rückgängig machen.

### Felddefinitionen exportieren und importieren

Felddefinitionen lassen sich als JSON-Datei speichern und laden – etwa um sie von einer Test- in eine Produktivinstallation zu übernehmen, sie zu versionieren oder mit einem Beispiel zu starten.

- **Felder exportieren** lädt alle Felddefinitionen (auch archivierte) als `kartei-fields.json` herunter.
- **Felder importieren** lädt eine solche Datei hoch und zeigt rechts zuerst eine **Vorschau**. Neue oder geänderte Abschnitte stehen oben; jedes Feld der Datei erscheint als *neu*, *geändert* (mit den geänderten Einstellungen), *unverändert* oder *ungültig* (mit Begründung). *Übernehmen* legt die Felder an bzw. ändert sie; *Abbrechen* verwirft den Import.

Dabei gilt:

- Felder werden über ihren **Schlüssel** zugeordnet. Felder, die es in Kartei gibt, aber nicht in der Datei, bleiben unverändert; gelöscht wird nichts.
- Abschnitte werden ebenfalls über ihren Schlüssel zugeordnet: Neue kommen in der Reihenfolge der Datei hinzu, vorhandene übernehmen die Bezeichnungen aus der Datei und behalten ihre Position. Verweist ein Feld auf einen Abschnitt, den es weder in der Datei noch in Kartei gibt, ist es *ungültig*.
- Dateien im älteren Format Version 1 (Abschnittsbezeichnungen je Feld) lassen sich weiter importieren: Jeder Abschnitt wird über seine deutsche oder englische Bezeichnung gefunden oder angelegt.
- Für Typwechsel gelten dieselben Regeln wie im Editor: Ein unzulässiger Wechsel bei einem Feld mit Daten wird als *ungültig* gemeldet und nicht übernommen.
- Neue Felder kommen in der Reihenfolge der Datei hinzu; *Von Firma übernehmen aus* verweist über den Schlüssel auf ein Feld und darf auf ein Feld derselben Datei zeigen.
- Jedes angelegte oder geänderte Feld bekommt einen Eintrag im Protokoll.

### Beispieldateien

Der Ordner `examples` im Kartei-Repository enthält Ausgangspunkte (erklärt in `examples/README.md`):

| Datei | Inhalt |
|---|---|
| `fields-default.json` | Die wenigen Felder, mit denen eine frische Installation startet: Funktion, E-Mail, Telefon, Mobil, Telefon Zentrale, E-Mail Zentrale, Webseite. |
| `fields-example.json` | Ein umfangreicherer, neutraler Feldbestand: Angaben zur Person (Anrede, akademischer Titel, Abteilung, private Kontaktdaten, Assistenz, Vorgesetzte …), zur Firma (Kurzname, Telefon/E-Mail/Fax Zentrale, Geschäftsführung), Geschäftsadresse (von der Firma übernommen), Privatadresse, *Ansprechpartner intern* (*Benutzer*, Pflichtfeld, prüft den Kontakt), *Kontakte intern*, Schlagworte, Kunden- und Vertragsnummer, Notizen. Alles mit deutschen und englischen Bezeichnungen, vCard-Zuordnung und gängigen deutschen und englischen CSV-Spaltennamen als Import-Spaltennamen. |
| `ad-mapping.json` | Eine AD-Attributzuordnung für diese Felder (siehe [Active Directory](#active-directory)). |

Beim ersten Start lädt Kartei `examples/fields-default.json`. Die Umgebungsvariable `INITIAL_FIELDS` verweist auf eine andere Datei (Pfad im Container); ein leerer Wert startet ganz ohne Felder. Das passiert nur einmal, bei einer frischen Datenbank.

Für den umfangreicheren Bestand wählst du *Felder importieren* → `fields-example.json`, prüfst die Vorschau und klickst auf *Übernehmen*. Was du nicht brauchst, archivierst oder änderst du danach.

## Import

Unter *Einstellungen → Import* importierst du Personen und Firmen aus einer CSV-Datei – etwa beim Umzug von einem anderen System oder zur Übernahme einer Liste. Für jede Spalte legst du fest, wohin ihre Werte gehen.

![Reiter Import](../img/de/settings-import.png)

### Import ausführen

1. Enthält die Datei Benutzer (z. B. einen internen Ansprechpartner), leg die Benutzer vorher an oder importiere sie (siehe [Benutzer vorab importieren](#benutzer-vorab-importieren)), damit sie zugeordnet werden können.
2. Sorg dafür, dass die benötigten Felder existieren (siehe [Felder](#felder)). Import-Spaltennamen an den Feldern helfen beim automatischen Vorschlag.
3. *CSV-Datei auswählen*. Kartei liest die Kopfzeile und zeigt die **Spaltenzuordnung**.
4. Prüf die Zuordnung und die Regeln für die Art (siehe unten).
5. Klick auf *Probelauf*. Es wird nichts gespeichert; du siehst die Zahl der Zeilen, neue und aktualisierte Personen und Firmen sowie die Hinweise.
6. Pass bei Bedarf die Zuordnung oder die Quelldaten an und wiederhole den Probelauf.
7. Klick auf *Import ausführen* (geht erst nach einem Probelauf).

**Dateiformat:** UTF-8 (mit oder ohne BOM) oder Windows-1252; Komma, Semikolon oder Tabulator als Trennzeichen (wird erkannt); die erste Zeile enthält die Spaltenüberschriften.

### Spaltenzuordnung

Die Tabelle zeigt für jede Spalte die Überschrift, Beispiele aus den ersten Zeilen und zwei Ziele: eines *bei Personen* und eines *bei Firmen*. Dieselbe Spalte kann je nach Art etwas anderes bedeuten, z. B. eine Spalte „Name“, die bei Personen der Nachname und bei Firmen der Firmenname ist. Mögliche Ziele:

| Ziel | Personen | Firmen |
|---|---|---|
| *Alt-ID* | ✓ | ✓ |
| *Vorname*, *Nachname* | ✓ | – |
| *Firma (Verknüpfung über den Namen)* | ✓ | – |
| *Name* | – | ✓ |
| ein Feld (nur Felder, die für die Art gelten) | ✓ | ✓ |
| *Neues Feld anlegen …* | ✓ | ✓ |
| *(ignorieren)* | ✓ | ✓ |

Kartei schlägt für jede Spalte ein Ziel vor: zuerst gängige Namen der Stammdaten (z. B. `Vorname`/`First name`, `Firma`/`Company`, `ID`), dann das Feld, dessen Schlüssel, Bezeichnung oder **Import-Spaltennamen** zur Überschrift passen (Groß-/Kleinschreibung, Akzente und Satzzeichen zählen nicht). Passt kein Name, schaut Kartei auf die Werte und nimmt das erste noch freie Feld, dessen Typ passt: E-Mail-Adressen, Telefonnummern (beginnend mit `0`, `+` oder `(`), Webadressen, Datumsangaben, Optionen eines Auswahlfelds oder Kartei-Benutzer. Solche Spalten sind mit *nach Inhalt* markiert. Prüf den Vorschlag; leer heißt, die Spalte wird ignoriert.

*Neues Feld anlegen …* öffnet neben der Zuordnung denselben Feldeditor wie unter *Felder*. Vorbelegt sind die Spaltenüberschrift als Bezeichnung und Import-Spaltenname, die gewählte Seite unter *Gilt für* und ein Typ, den Kartei aus den Werten ableitet: E-Mail, Telefon, URL, Datum, langer Text (Zeilenumbrüche), Ganz- oder Dezimalzahl (ohne führende Nullen, PLZ bleiben Text) oder Einfach-/Mehrfachauswahl mit den gefundenen Werten als Optionen, wenn sich wenige Werte wiederholen. Pass alles an (Abschnitt, Sichtbarkeit, vCard-Zuordnung, …) und speichere: Das Feld wird sofort angelegt und ist dann das Ziel der Spalte.

![Neues Feld aus dem Import](../img/de/import-new-field.png)

*Zuordnung exportieren* lädt die Zuordnung (samt Regeln für die Art) als JSON herunter; *Zuordnung importieren* lädt sie für die nächste Datei mit denselben Spalten wieder.

### Person oder Firma?

Kartei bestimmt die Art jeder Zeile in dieser Reihenfolge:

1. **Spalte mit der Art:** Ist sie gesetzt, bedeuten Werte wie `Person`/`Kontakt`/`Contact` Person und `Firma`/`Company`/`Organisation` Firma. Andere Werte ergeben einen Hinweis, dann greifen die nächsten Regeln. Eine Spalte namens `Art`, `Typ` oder `Type` wird vorausgewählt, wenn mindestens die Hälfte ihrer Werte solche Arten sind; sonst eine Spalte, deren Werte fast alle Arten sind.
2. **ID-Präfixe:** *ID beginnt mit … → Firma* und *ID beginnt mit … → Person* prüfen die Spalte, die der *Alt-ID* zugeordnet ist, z. B. `F-` und `P-`.
3. **Sonst:** Zeilen mit Nachname sind Personen; Zeilen ohne Nachname, aber mit Firmenname sind Firmen.

### Was der Import macht

- **Abgleich:** Ist eine Spalte der *Alt-ID* zugeordnet, wird jede Zeile dem Kontakt derselben Art mit derselben Alt-ID zugeordnet, und ein erneuter Import **aktualisiert** diese Kontakte. Ohne Alt-ID legt jeder Import neue Kontakte an.
- **Firmenzuordnung:** Personen werden der Firma zugeordnet, deren Name in der Spalte für *Firma (Verknüpfung über den Namen)* steht. Unbekannte Firmen werden angelegt. Firmen werden vor den Personen importiert.
- **Benutzerfelder** (*Benutzer*, *Mehrere Benutzer*) werden über Benutzername, vollen Namen oder eindeutige Initialen den aktiven Kartei-Benutzern zugeordnet; Administratoren werden nicht zugeordnet. Unbekannte Namen und Administratoren ergeben einen Hinweis und werden weggelassen.
- **Auswahlfelder:** Unbekannte Werte werden als neue Auswahlwerte ergänzt. Mehrere Werte in einer Zelle trennst du mit Komma oder Semikolon.
- **Ungültige Werte** (z. B. eine fehlerhafte E-Mail-Adresse oder ein Wert, der nicht zum Format des Felds passt) werden mit Hinweis übersprungen; der Rest der Zeile wird importiert. Leere Zellen überschreiben keine Feldwerte (eine leere Spalte für Vorname, Nachname oder Firmenname leert diesen Namen aber).
- Zeilen ohne Namen werden übersprungen, ebenso Zeilen, deren Alt-ID zu einem inzwischen zusammengeführten Kontakt gehört.
- Jeder angelegte oder geänderte Kontakt bekommt einen Eintrag *Importiert* in seinem Verlauf.

> Achtung: Ein erneuter Import derselben Datei überschreibt Werte, die inzwischen in Kartei geändert wurden, mit den Werten aus der Datei. Sobald dein Team in Kartei arbeitet, importiere Altdaten nicht mehr.
{: .warn}

### Kommandozeile

Derselbe Import läuft auch auf der Kommandozeile, etwa für große Dateien. Die Datei muss im Container lesbar sein (z. B. unterhalb von `/export`). Ohne `--commit` ist es ein Probelauf; ohne `--mapping` gilt die vorgeschlagene Zuordnung.

```sh
docker compose exec web python manage.py import_csv /export/kontakte.csv --mapping /export/zuordnung.json
docker compose exec web python manage.py import_csv /export/kontakte.csv --mapping /export/zuordnung.json --commit
```

## Exporte

Unter *Einstellungen → Exporte* schreibt Kartei CSV- und Excel-Dateien ins Exportverzeichnis – etwa für Skripte und andere Anwendungen, die Kontakte einlesen, oder für Kolleginnen und Kollegen, die die Liste in einer Tabellenkalkulation öffnen. Jeder Export ist ein Profil mit eigenen Spalten und eigenem Format.

![Reiter Exporte](../img/de/settings-exports.png)

Die Liste zeigt jedes Profil mit *Format*, *Zieldatei*, *Ausführung* und *Letzter Lauf* (Status, Zeitpunkt und Meldung). *Jetzt ausführen* schreibt die Datei sofort.

### Export anlegen oder bearbeiten

1. *Neuer CSV-Export* oder *Neuer Excel-Export*, oder klick auf ein vorhandenes Profil.
2. **Allgemein:**
   - *Name*.
   - *Zieldatei*: absoluter Pfad unterhalb von `/export` mit passender Endung (`.csv` bzw. `.xlsx`), z. B. `/export/kontakte_export.csv`. `{date}` wird durch das aktuelle Datum ersetzt (`2026-10-24`). Fehlende Ordner unterhalb von `/export` legt Kartei automatisch an.
   - *Enthält*: *Personen & Firmen*, *Personen* oder *Firmen*.
   - *Ausführung*: *automatisch* (in jedem Export-Intervall) oder *nur manuell*.
   - *Max. Rückgang (%)*: der Schrumpfschutz (siehe unten).
   - *Nur Einträge mit Feld* und *Werte*: optionaler Filter auf ein Auswahlfeld, z. B. nur Kontakte mit einem bestimmten Schlagwort.
   - *Export aktiv*: Automatische Exporte laufen nur mit diesem Haken.
3. **Spalten:** *Spalte* fügt eine leere Spalte hinzu, *Alle Felder hinzufügen* eine Spalte pro Feld. Leg für jede Spalte *Spaltenüberschrift*, *Wert bei Personen* und *Wert bei Firmen* fest. Quellen sind Stammfelder, Felder und berechnete Werte (*UID*, *Alt-ID*, *Alt-ID, sonst UID*, *Anzeigename*, *Firmenname (der Person)*, *Typ (person/company)*, *Angelegt am*, *Geändert am*). Die Schaltfläche `“”` schaltet eine Spalte auf *Fester Text* um. Die Reihenfolge änderst du am Griff.
4. **Formatoptionen:** siehe unten.
5. *Vorschau* zeigt die ersten 20 Zeilen und die Gesamtzahl.
6. *Speichern*.

![Export-Editor](../img/de/settings-export-editor.png)

> Achtung: *Löschen* im Editor entfernt das Profil nach einer Rückfrage; das lässt sich nicht rückgängig machen. Die zuletzt geschriebene Datei bleibt im Exportverzeichnis liegen.
{: .warn}

### CSV-Optionen

| Option | Standard |
|---|---|
| *Trennzeichen* | `;` (außerdem `,`, Tabulator, senkrechter Strich) |
| *Anführungszeichen* | *nur wenn nötig* (außerdem *immer*, *außer Zahlen*), *Zeichen* `"` |
| *Zeichensatz* | *UTF-8 + BOM (Excel)* (außerdem UTF-8, Windows-1252). Bei Windows-1252 werden Zeichen, die es nicht kennt (z. B. in polnischen oder türkischen Namen), als `?` geschrieben; der Exportstatus nennt dann die Zahl der betroffenen Werte. |
| *Zeilenende* | CRLF (Windows) |
| *Zeilenumbrüche in Werten* | *beibehalten* (in Anführungszeichen) oder *durch Leerzeichen ersetzen* – Letzteres für Skripte, die zeilenweise lesen |
| *Trenner Mehrfachauswahl* | `, ` |
| *Datumsformat*, *Dezimaltrenner* | `31.12.2026`, `1234,56` |
| *Ja / Nein als* | `Ja` / `Nein` |
| *Kopfzeile schreiben* | an |
| *Vor Tabellen-Formeln schützen* | an: Werte, die Excel als Formel ausführen würde (beginnend mit `=`, `@` oder `+`/`-` gefolgt von Text), bekommen ein vorangestelltes `'`. Telefonnummern und Zahlen bleiben unverändert. Nur ausschalten, wenn ein Programm die Datei liest und die Rohwerte braucht. In Excel-Exporten werden Formeln immer als Text geschrieben. |

### Excel-Optionen

*Tabellenblatt*, *Datumsformat* und *Zahlenformat* (Excel-Formatcodes), dazu *Kopfzeile*, *Kopfzeile fett*, *Autofilter*, *Kopfzeile fixieren* und *Spaltenbreite automatisch*. Datum und Zahlen werden als echte Excel-Werte geschrieben, nicht als Text. Die Schriftart ist Tahoma.

### Der Schrumpfschutz

Ein leerer oder abgeschnittener Export kann in nachgelagerten Systemen Kontakte löschen. Kartei schreibt deshalb nicht:

- einen Export mit **0 Zeilen** (*Leerer Export – nicht geschrieben …*),
- einen Export, dessen Zeilenzahl gegenüber dem letzten erfolgreichen Lauf – beim ersten Lauf gegenüber der vorhandenen Datei – um mehr als *Max. Rückgang (%)* gefallen ist (*Zeilenzahl von … auf … gefallen*).

In beiden Fällen bleibt die alte Datei unverändert, und der Status wird *error*. Ist der Rückgang gewollt (z. B. nach einer großen Bereinigung), klick neben *Jetzt ausführen* auf *Erzwingen*: Die Datei wird einmal ohne Prüfung geschrieben.

Außerdem gilt:

- Hat sich der Inhalt nicht geändert, wird die Datei nicht neu geschrieben (*Unverändert – nicht neu geschrieben*).
- Dateien werden zuerst in eine temporäre Datei geschrieben und dann ersetzt; Leser sehen also nie eine halb geschriebene Datei.
- Mit `{date}` im Pfad entsteht jeden Tag eine neue Datei; alte Dateien werden nicht gelöscht.

## Active Directory

Unter *Einstellungen → Active Directory* schreibt Kartei alle Kontakte als AD-Kontaktobjekte (`objectClass: contact`) in eine OU. Jedes System, das Kontakte aus dem Active Directory liest, kann sie nutzen – etwa die Anruferkennung einer Telefonanlage oder das Adressbuch eines Kommunikations-Clients.

![Reiter Active Directory](../img/de/settings-ad.png)

### So arbeitet der Sync

- **Markierung:** Jedes von Kartei angelegte Objekt trägt `kartei:<UID>` in `adminDescription`. Objekte ohne diese Markierung werden nie geändert oder gelöscht.
- **Name:** `cn` und `displayName` sind der Anzeigename des Kontakts. Ist der Name vergeben, hängt Kartei ` (2)`, ` (3)` usw. an.
- **Änderungen:** Geschrieben werden nur geänderte Attribute; umbenannte Kontakte werden im AD umbenannt, in Kartei gelöschte Kontakte im AD gelöscht. Leere Werte entfernen das Attribut.
- **Schutz:** Der Sync schreibt nichts, wenn Kartei keine Kontakte hat oder wenn mehr als *Max. Löschungen (%)* der markierten Objekte gelöscht würden (*100* schaltet den Schutz ab).
- **Zeitplan:** in jedem Export-Intervall, solange *AD-Sync aktiv* angehakt ist, oder wenige Sekunden nach *Jetzt synchronisieren*.

### AD vorbereiten

1. Leg eine neue, leere OU an, z. B. `OU=Kartei,OU=Kontakte,DC=example,DC=local`.
2. Wähl das Schreibkonto: das LDAP-Dienstkonto oder ein eigenes Konto.
3. Delegiere diesem Konto auf der OU die Rechte (*Objektverwaltung zuweisen* → *Benutzerdefinierte Aufgabe* → *Nur folgende Objekte*: Kontakt-Objekte, *Erstellen* und *Löschen* der ausgewählten Objekte → Berechtigung *Vollzugriff*).

### Einrichten

| Einstellung | Hinweise |
|---|---|
| *AD-Sync aktiv* | Setzt einen LDAP-Server unter *LDAP / AD* und eine Ziel-OU voraus. |
| *Ziel-OU (DN)* | Kartei betrachtet nur Objekte direkt in dieser OU. |
| *Konto zum Schreiben (Bind-DN, optional)*, *Passwort des Schreibkontos* | Leer = das Dienstkonto aus *LDAP / AD*. Server, StartTLS und CA-Zertifikat kommen immer von dort. |
| *Enthält* | *Personen & Firmen*, *Personen* oder *Firmen*. |
| *Max. Löschungen (%)* | Standard 10. |
| *AD-Attribute* | Eine Zeile je AD-Attribut: *AD-Attribut*, *Wert bei Personen*, *Wert bei Firmen*, Quellen wie bei den Exporten, `“”` für festen Text. `cn`, `name`, `displayName`, `objectClass`, `adminDescription` und `distinguishedName` setzt Kartei selbst; sie lassen sich nicht zuordnen. |

Die Zuordnung ist anfangs leer. Leg mit *Attribut* eine Zeile für jedes AD-Attribut an, das die lesenden Systeme brauchen, typischerweise `givenName`, `sn`, `title`, `department`, `company`, `telephoneNumber`, `mobile`, `mail`.

*Zuordnung exportieren* lädt die Zuordnung als JSON herunter, *Zuordnung importieren* lädt eine (danach *Speichern*). `examples/ad-mapping.json` ist eine fertige Zuordnung für die Felder aus `examples/fields-example.json`; pass sie an, wenn deine Feldschlüssel anders heißen.

### Probelauf und erster Sync

1. Trag OU, Konto und Zuordnung ein und klick auf *Speichern & Probelauf*. Es wird nichts geschrieben. Du siehst die Zahlen (*neu · geändert · umbenannt · gelöscht · unverändert*), bis zu 20 Beispiele je Aktion (*Würde anlegen*, *Würde umbenennen*, *Würde ändern*, *Würde löschen*) und einen Hinweis, falls der Schutz den Sync stoppen würde.
2. Passt das Ergebnis, hak *AD-Sync aktiv* an und klick auf *Speichern*.
3. Klick auf *Jetzt synchronisieren*. Das Feld *Letzter Lauf* zeigt das Ergebnis und eventuell fehlgeschlagene Objekte.
4. Prüf, ob die lesenden Systeme die Kontakte finden. Durchsuchen sie eine feste OU, nimm die Ziel-OU dort auf.

> Achtung: Verwende eine OU, in die nur Kartei schreibt. Kartei fasst Objekte ohne seine Markierung nie an: Legt ein anderes Werkzeug oder Skript dort ebenfalls Kontakte an, stehen sie neben denen von Kartei, und Kartei-Objekte bekommen bei bereits vergebenen Namen ein ` (2)`.
{: .warn}

## CardDAV

Kartei bringt einen schreibgeschützten CardDAV-Server mit einem Adressbuch mit, das alle Personen und Firmen enthält. Alle Telefone nutzen dasselbe Konto.

> Haben alle Telefonbenutzer ein Exchange-Online-Postfach, deckt der [Outlook-/Exchange-Sync](#outlook-sync) iPhones und Android-Telefone gleichermaßen ab, und CardDAV kann ausgeschaltet bleiben. CardDAV ist für Telefone ohne eigenes Postfach (Sammel- oder Pooltelefone, Benutzer außerhalb der Sync-Gruppe), für Installationen ohne Microsoft 365 und für ein zentrales, schreibgeschütztes Adressbuch statt einer Kopie in jedem Postfach. Außerdem behält es iPhone-Details wie eigene Telefonbezeichnungen, phonetische Namen und Beziehungen, die in Outlook-Kontakten nur als Notiz landen.
{: .tip}

![Reiter CardDAV](../img/de/settings-carddav.png)

### Einrichten

1. *Einstellungen → Telefone & CardDAV*: *Eingebauter CardDAV-Server aktiv* anhaken und *Speichern*.
2. Ändere bei Bedarf den *Benutzername* des Kontos (Standard `carddav`).
3. Klick auf *Passwort erzeugen*. Das Passwort wird **nur jetzt** angezeigt; kopier es in den Passwortsafe.
4. Prüf die Serveradresse unter *Einrichtung auf Telefonen*. Sie ergibt sich aus der *Öffentlichen Adresse* (*Einstellungen → Allgemein*): `https://kartei.example.de/carddav/`.

![CardDAV-Passwort, nur einmal angezeigt](../img/de/settings-carddav-password.png)

*Neues Passwort erzeugen* ersetzt das Passwort sofort; danach braucht jedes Telefon das neue Passwort.

### Auf dem iPhone

1. *Einstellungen → Kontakte → Accounts → Account hinzufügen → Andere → CardDAV-Account hinzufügen*.
2. *Server*: `kartei.example.de` (das iPhone findet `/carddav/` selbst) oder die vollständige Adresse.
3. *Benutzername* und *Passwort* aus Kartei, dann *Weiter*.

Die Kontakte erscheinen als eigener Account in der Kontakte-App und werden automatisch aktualisiert. Änderungen auf dem Telefon sind nicht möglich.

### Was übertragen wird

- Nur Felder, die für *Alle* sichtbar sind und eine *vCard-Zuordnung* haben.
- Fotos der Personen und Logos der Firmen.
- Namen von Benutzern und verknüpften Personen (z. B. *Ansprechpartner intern*) als Text.
- Gelöschte Kontakte verschwinden von den Telefonen.
- **Adressbücher aus gespeicherten Filtern:** Ein als Adressbuch veröffentlichter Filter erscheint als zusätzliches Buch (`/carddav/f-<id>/`) im selben Konto, für alle Telefone. DAVx⁵ (Android) zeigt jedes Buch einzeln; ob und wie das iPhone weitere Bücher eines Kontos zeigt, hängt von der iOS-Version ab – vorher mit einem Gerät ausprobieren. Nur Filter, die mit allen geteilt sind, die Liste *Alle Kontakte* nutzen und nur Felder, die alle sehen, kommen infrage; wird ein Feld später eingeschränkt, verschwindet das Buch. Kommen Kontakte in den Filter oder fallen heraus, laden die Telefone dieses Buch neu. Der Relay liefert diese Bücher auch aus (Relay ab dieser Version).
- Telefone, die es unterstützen (iPhone, DAVx⁵ und die meisten anderen), holen nur, was sich seit ihrem letzten Abgleich geändert hat (`sync-collection`) – das hält den Abgleich auch bei vielen Kontakten schnell. Nach einer Änderung der vCard-Zuordnung, der *Öffentlichen Adresse* oder nach endgültigem Löschen aus dem Papierkorb gleicht jedes Telefon einmal von selbst vollständig ab.

Ist CardDAV deaktiviert, meldet die Adresse „nicht gefunden“, und die Telefone behalten ihren letzten Stand, bis der Account entfernt wird. Android hat kein eingebautes CardDAV – dafür gibt es den [Outlook-/Exchange-Sync](#outlook-sync) oder eine CardDAV-App.

### Relay in der DMZ (optional) {#relay-dmz}

Wenn Telefone das interne Netz nicht erreichen dürfen, betreibst du einen kleinen **CardDAV-Relay** in der DMZ. Kartei schiebt die fertigen vCards dorthin; die Telefone lesen sie vom Relay.

| | Eingebauter Server | Relay in der DMZ |
|---|---|---|
| Telefone verbinden sich mit | Kartei (`https://kartei.example.de/carddav/`) | dem Relay (`https://carddav.example.de/carddav/`) |
| Verbindung intern ↔ DMZ | keine | Kartei (`exporter`) → Relay, nur HTTPS; der Relay baut nie selbst eine Verbindung auf |
| Daten auf dem DMZ-Host | keine | die fertigen vCards (iOS- und Android-Variante), der CardDAV-Benutzername und der **Hash** des Passworts – sonst nichts, kein Zugriff auf Datenbank oder LDAP. Gelöschte Karten bleiben 30 Tage als leere Markierung stehen, damit die Telefone die Löschung mitbekommen; Telefone, die länger nicht abgeglichen haben, gleichen einmal vollständig ab. |

Der Relay ist dasselbe Image mit anderen Einstellungen (`docker build --target relay`, ohne Frontend). Er speichert die Karten in einer eigenen SQLite-Datei, bietet dasselbe schreibgeschützte CardDAV wie Kartei (Adresse `/carddav/`, Erkennung über `/.well-known/carddav`, Sperre nach falschen Passwörtern) und hat keine weiteren Seiten: kein Admin, keine Anmeldung, keine Listen.

**Firewall:** Erlaube nur *Kartei-Host → Relay-Host, TCP 443* (bzw. den Port des Reverse Proxys vor dem Relay) und *Telefone/Internet → Relay, 443*. Nichts aus der DMZ nach innen.

**Einrichten**

1. Kopier auf dem DMZ-Host das Repository (oder nur `Dockerfile`, `backend/`, `compose.relay.yaml`), dann `cp .env.relay.example .env.relay` und setz `SECRET_KEY` und `ALLOWED_HOSTS` (den Hostnamen, den die Telefone nutzen).
2. In Kartei unter *Einstellungen → Telefone & CardDAV → Externer Relay (DMZ)*: Trag die *Relay-URL* ein (`https://carddav.example.de`, nur HTTPS) und klick auf *Token erzeugen*. Kartei speichert das Push-Token verschlüsselt und zeigt nur seinen SHA-256-Wert. Kopier diesen Wert in die `.env.relay` als `RELAY_PUSH_TOKEN_SHA256`. Das Token selbst kommt nie auf den DMZ-Host.
3. Starte den Relay: `docker compose -f compose.relay.yaml up -d --build`. Er lauscht auf Port 8080 (`RELAY_PORT`); setz einen TLS-Reverse-Proxy davor, eingerichtet wie der für Kartei (`Authorization`, `PROPFIND`/`REPORT` und `X-Forwarded-For` durchreichen, `client_max_body_size 20m`). Die SQLite-Datei liegt im Volume `relaydata`.
4. *TLS*: Mit *TLS-Zertifikat prüfen* (Standard) prüft Kartei das Zertifikat des Relays gegen die System-CAs oder, falls eingetragen, gegen das *CA-Zertifikat* (PEM) deiner internen CA. Schalte die Prüfung nur für Tests ab.
5. Klick auf *Speichern & testen*: Kartei erreicht den Relay und prüft das Token. Dann *Zum Relay übertragen* anhaken, *Max. Löschungen (%)* einstellen und *Speichern*.
6. Nimm den Haken bei *Eingebauter CardDAV-Server aktiv* heraus. Kartei meldet unter `/carddav/` dann „nicht gefunden“, so nutzen Telefone nicht versehentlich den internen Server. (Beides gleichzeitig geht auch, z. B. während einer Umstellung.)
7. Richte die Telefone mit der Adresse des Relays ein. Benutzername und Passwort sind die aus diesem Reiter; *Neues Passwort erzeugen* erreicht den Relay mit der nächsten Übertragung.

**So funktioniert die Übertragung:** Bei jedem Export-Intervall (und etwa 10 Sekunden nach *Jetzt synchronisieren*) fragt der `exporter` den Relay, welche Karten er hat (UID und Version), schickt neue und geänderte Karten in Paketen von etwa 2 MB und die UIDs zum Löschen, und immer den aktuellen Benutzernamen und Passwort-Hash. Jeder Lauf vergleicht mit dem tatsächlichen Stand des Relays; auf dem Relay verlorene oder zusätzliche Karten werden also beim nächsten Lauf korrigiert. *Letzter Lauf* zeigt das Ergebnis.

**Schutz:** Kartei überträgt nichts, wenn es keine Kontakte hat oder wenn in einem Lauf mehr als *Max. Löschungen (%)* der Karten auf dem Relay gelöscht würden (100 = aus). Der Lauf wird dann als Fehler gemeldet, und der Relay behält seinen Stand. Sind die Löschungen gewollt, erhöh die Grenze für einen Lauf.

**Fehlersuche**

| Status / Symptom | Ursache |
|---|---|
| *Der Relay hat das Push-Token abgelehnt* | `RELAY_PUSH_TOKEN_SHA256` auf dem Relay-Host passt nicht zum Wert in Kartei (nach Änderung der `.env.relay` den Relay neu starten). |
| `certificate verify failed` | Dem Zertifikat des Relays wird nicht vertraut: CA-Zertifikat eintragen oder den Hostnamen in der URL prüfen. |
| `timed out`, `Connection refused`, `Name or service not known` | Firewall-Regel intern → DMZ, DNS-Name oder Reverse Proxy des Relays. |
| `HTTP 400` / `HTTP 413` | Der Reverse Proxy vor dem Relay begrenzt die Anfragegröße (`client_max_body_size 20m` setzen) oder verändert die Anfrage. |
| Telefone bekommen 401 | Falsches Passwort, oder der Relay hat den Zugang noch nicht erhalten (siehe *Letzter Lauf*). 20 falsche Passwörter von einer Adresse sperren sie für 15 Minuten. |
| Relay antwortet auf alles mit 400 | Der Hostname fehlt in `ALLOWED_HOSTS` in der `.env.relay`. |

Der Relay schreibt jede Anfrage ins Container-Log (`docker compose -f compose.relay.yaml logs`). Für einen Neuanfang stoppst du ihn und löschst das Volume `relaydata`; die nächste Übertragung füllt es wieder.

## Telefonbuch für Tischtelefone {#phonebook}

Tischtelefone laden die Kontakte als *Online-Telefonbuch* (Remote Phonebook), und Telefonanlagen fragen Kartei, wer anruft. Wie bei CardDAV enthält es, was *Nur-Lesen*-Benutzer sehen, und nur Felder mit einer Telefon-vCard-Zuordnung (geschäftlich, mobil, privat, Assistenz, eigene; kein Fax).

![Einstellungen des Telefonbuchs](../img/de/settings-phonebook.png)

1. *Einstellungen → Telefone & CardDAV*, Abschnitt *Telefonbuch für Tischtelefone*: **Passwort erzeugen** (wird nur einmal angezeigt) und den Benutzernamen notieren (Standard `telefon`).
2. Optional unter *Erlaubte Adressen* auf das Telefon-Netz beschränken, z. B. `10.0.5.0/24`.
3. *Telefonbuch und Rufnummernsuche an* anhaken und **Speichern**.
4. Die Adresse für die Telefonmarke mit Benutzername und Passwort als Online-Telefonbuch eintragen (Provisionierung oder Weboberfläche des Telefons):

| Telefone | Adresse | Hinweis |
|---|---|---|
| Yealink | `https://kartei.example.de/phonebook/yealink.xml` | bei großen Listen die Such-Adresse `…/yealink.xml?q=#SEARCH` (das Telefon schickt, was eingetippt wurde) |
| Snom | `…/phonebook/snom.xml` | ein Eintrag pro Nummer: *Name – Firma (Mobil)* |
| Grandstream | `…/phonebook/grandstream.xml` | Vorname, Nachname, Firma, Nummern nach Art |
| SwyxWare | `…/phonebook/swyx.csv` | Datei für den Import ins Globale Telefonbuch, siehe unten |

Alle drei verstehen `?q=` mit einem Teil von Name, Firma oder Nummer. Ohne geht das ganze Telefonbuch hinaus; bei Zehntausenden Kontakten sind das mehrere MB, zu viel für die meisten Telefone: dann die Such-Adresse nutzen. Telefone, die stattdessen LDAP lesen (z. B. Gigaset), können den [Active-Directory-Sync](#active-directory) nutzen.

**SwyxWare.** Swyx zeigt Anrufernamen aus seinem *Globalen Telefonbuch*, auf jedem SwyxIt!-Client und Swyx-Telefon. `swyx.csv` ist das Telefonbuch im Importformat von Swyx: eine Zeile pro Nummer (`"Name";"Nummer";"Beschreibung"`, alles in Anführungszeichen, Nummern ohne Leerzeichen), Namen im Swyx-Stil (`Muster,Erika`) und eindeutig, wie Swyx es verlangt (bei mehreren Nummern mit deren Bezeichnung, z. B. `Muster,Erika (Mobil)`); die Beschreibung enthält Firma und Bezeichnung. Im Browser mit der Telefonbuch-Anmeldung herunterladen, dann in der Swyx Administration beim Globalen Telefonbuch den Import starten, die Datei wählen und bestehende Einträge aktualisieren lassen. Alle vorhandenen Einträge vor dem Import zu löschen, nur wählen, wenn das Globale Telefonbuch nichts außer den Kartei-Kontakten enthält. Die Datei ist UTF-8; zeigt eine ältere SwyxWare Umlaute falsch an, `swyx.csv?charset=windows-1252` verwenden. `?q=` geht auch hier, z. B. für eine Firma. Einen dokumentierten automatischen Import bietet Swyx nicht; nach größeren Änderungen den Import wiederholen.

**Rufnummernsuche** für Telefonanlagen (3CX, Starface, Asterisk …): `GET /phonebook/lookup?number=+495111000` mit derselben Anmeldung liefert `Name · Firma` als Text, mit `&format=json` `{"found": true, "name", "company", "kind", "uid"}`. Unbekannte Nummern ergeben `404`. Nummern werden in jeder Schreibweise verglichen (`+49…`, `0049…`, `0…`); ist die genaue Nummer unbekannt, gewinnt die längste gespeicherte Nummer, mit der sie beginnt – eine unbekannte Durchwahl zeigt so noch die Firma. Ein nicht kodiertes `+` in der Adresse wird auch verstanden.

Kartei hält das Telefonbuch im Speicher und schaut höchstens einmal pro Minute nach Änderungen; eine Suche dauert so auch bei 50 000 Kontakten unter einer Millisekunde, eine neue oder geänderte Nummer ist nach spätestens einer Minute da. Fehlgeschlagene Anmeldungen stehen im Protokoll (Kanal *phonebook*) und zählen zur üblichen Sperre.

## Outlook-/Exchange-Sync {#outlook-sync}

Kartei schreibt alle Kontakte über Microsoft Graph in einen Kontaktordner (Standard `Kartei`) im Postfach jedes Mitglieds einer Entra-Gruppe. Die Outlook-App für iOS und Android speichert diesen Ordner im Telefonbuch – das ergibt Anruferkennung auf iPhones und Android-Telefonen ohne CardDAV.

Voraussetzungen: Exchange-Online-Postfächer (Microsoft 365) und eine App-Registrierung in Entra ID.

![Reiter Outlook / Exchange](../img/de/settings-outlook.png)

### App in Entra ID registrieren

1. Entra Admin Center → *App-Registrierungen* → *Neue Registrierung*, z. B. Name „Kartei Kontakte“, einzelner Mandant, ohne Umleitungs-URI.
2. *API-Berechtigungen* → *Berechtigung hinzufügen* → *Microsoft Graph* → *Anwendungsberechtigungen*: `Contacts.ReadWrite` und `GroupMember.Read.All`. Danach *Administratorzustimmung erteilen*.
3. *Zertifikate & Geheimnisse* → *Neuer geheimer Clientschlüssel*. Kopier den Wert und notier dir das Ablaufdatum.
4. Notier auf der Übersichtsseite die *Verzeichnis-ID (Mandant)* und die *Anwendungs-ID (Client)*.
5. Leg die Gruppe der Benutzer an (oder wähl sie aus), deren Telefone die Kontakte bekommen sollen, und notier ihre Objekt-ID. Verschachtelte Gruppen werden aufgelöst.

### Zugriff auf die Gruppe beschränken

`Contacts.ReadWrite` als Anwendungsberechtigung erlaubt den Zugriff auf **alle** Postfächer des Mandanten. Beschränke ihn in Exchange Online auf die Postfächer der Gruppe – entweder mit RBAC für Anwendungen oder mit einer Application Access Policy (setzt eine E-Mail-aktivierte Sicherheitsgruppe voraus):

```powershell
Connect-ExchangeOnline
New-ApplicationAccessPolicy -AppId <client-id> -PolicyScopeGroupId kartei-sync@example.de `
  -AccessRight RestrictAccess -Description "Kartei Kontaktsync"
Test-ApplicationAccessPolicy -AppId <client-id> -Identity jemand@example.de
```

### Kartei einrichten

1. *Einstellungen → Outlook / Exchange*: *Mandanten-ID (Tenant)*, *Anwendungs-ID (Client)*, *Geheimer Clientschlüssel* und *Gruppen-ID (Objekt-ID der Entra-Gruppe)* eintragen. Der Schlüssel wird verschlüsselt gespeichert; das Feld bleibt nach dem Speichern leer.
2. Trag bei Bedarf unter *Name des Kontaktordners (alle Kontakte)* einen anderen Ordnernamen ein. Sollen alle Benutzer zusätzlich persönliche Ordner bekommen, trag Namen unter *Ordner: meine Kontakte (zuständig)* und *Ordner: meine internen Kontakte* ein (leer = aus).
3. *Speichern & testen*: Kartei meldet sich an und ermittelt die Gruppenmitglieder mit Postfach (*Anmeldung erfolgreich – n Postfächer in der Gruppe*, dazu bis zu fünf Adressen). Es wird nichts geschrieben.
4. *Outlook-Sync aktiv* anhaken und *Speichern* (geht nur, wenn alle vier Werte ausgefüllt sind).
5. *Jetzt synchronisieren* startet den ersten Lauf. *Letzter Lauf* zeigt Postfächer, neue, geänderte und entfernte Kontakte, Fotos und Dauer sowie Fehler.

Auf dem Telefon (iPhone oder Android) installieren die Benutzer die Outlook-App, melden sich mit ihrem Dienstkonto an und schalten *Kontakte speichern* ein (*Einstellungen* → Konto → *Kontakte speichern*). Mit Intune lässt sich diese Einstellung erzwingen.

> Das in iOS eingebaute Konto (*Einstellungen → Mail → Accounts → Exchange*) synchronisiert meist nur den Standardordner *Kontakte*, nicht den eigenen Ordner von Kartei. Nimm die Outlook-App und prüf es vor dem Ausrollen mit einem Testtelefon.
{: .tip}

### Verhalten

- Übertragen werden nur Felder, die für *Alle* sichtbar sind, gemäß ihrer vCard-Zuordnung. Werte, für die Outlook kein Feld hat (Fax, Telefon Assistenz, eigene Beziehungen, mehr als drei E-Mail-Adressen), landen in den Notizen.
- Fotos werden mit übertragen.
- Der Ordner gehört Kartei: Kontakte, die Benutzer dort selbst anlegen, werden beim nächsten Lauf entfernt.
- Wer die Gruppe verlässt, verliert den Ordner beim nächsten Lauf.
- **Persönliche Ordner** liegen nur im eigenen Postfach, niemand sonst sieht sie:
  - *meine Kontakte*: Kontakte, bei denen der Benutzer in einem Einzel-Benutzerfeld steht (zuständige Person);
  - *meine internen Kontakte*: Kontakte, bei denen der Benutzer in einem Mehrfach-Benutzerfeld steht.

  Kartei ordnet ein Postfach über E-Mail-Adresse, UPN oder den Teil vor dem `@` (AD-Kontoname) einem Kartei-Benutzer zu. Postfächer ohne passenden Kartei-Benutzer bekommen nur den Ordner mit allen Kontakten.
- **Ordner aus gespeicherten Filtern:** Bearbeiter können einen gespeicherten Filter als Outlook-Ordner veröffentlichen (siehe Benutzerhandbuch, *Gespeicherte Filter*). Alle Postfach-Inhaber, die den Filter sehen, bekommen einen Ordner mit seinem Namen und den Kontakten, die der Filter ihnen zeigt (ihre eigenen Listen *Verantwortlich*/*Intern*, nur Felder ihrer Rolle). Wird ein Filter zurückgezogen, umbenannt oder nicht mehr mit jemandem geteilt, verschwindet sein Ordner beim nächsten Lauf. Ein Filter kann nicht den Namen des Haupt- oder eines persönlichen Ordners tragen. Höchstens 10 Filter können veröffentlicht sein (Outlook-Ordner und Adressbücher zusammen).
- Drosselungen durch Microsoft fängt Kartei mit automatischen Wiederholungen ab; ein großer erster Lauf kann etwas dauern.

> Achtung: Änderst du später einen Ordnernamen oder leerst den Namen eines persönlichen Ordners, legt Kartei einen neuen Ordner an und lässt den alten in den Postfächern liegen. Leg den Namen vor dem ersten Sync fest.
{: .warn}

## Prüfung

Der Zuständige jedes Kontakts (das erste Feld vom Typ *Benutzer*, z. B. *Ansprechpartner intern* im Beispiel-Feldbestand) wird von Zeit zu Zeit gebeten zu prüfen, ob der Kontakt noch stimmt. Wie Prüfende antworten und wie Bearbeiter über Vorschläge entscheiden, steht im [Benutzerhandbuch](user.html).

![Reiter Prüfung im Modus Fortlaufend](../img/de/settings-review-rolling.png)

### Prüfmodus

| Modus | Prüfungen starten |
|---|---|
| *Nur manuell* | nur über die Schaltflächen unten, oder für einen einzelnen Kontakt mit *Prüfung anfordern* (Admins) |
| *Fortlaufend (pro Kontakt)* | automatisch für jeden Kontakt, dessen letzte Prüfung (oder, falls nie geprüft, dessen Anlage) länger zurückliegt als *Fällig nach … Monaten seit der letzten Prüfung* |
| *Jährlich an einem Stichtag* | für alle Kontakte einmal im Jahr am *Stichtag (jedes Jahr)* |

Jeder Kontakt hat höchstens eine offene Prüfung. Kontakte ohne aktiven Zuständigen können nicht geprüft werden.

> Tipp: Importierte Kontakte gelten als am Importtag angelegt. Im Modus *Fortlaufend* werden sie also erst nach Ablauf des Intervalls fällig. Willst du sofort eine erste Runde, nimm *Alle Kontakte prüfen lassen*.
{: .tip}

### Starten und beobachten

- *Fällige jetzt prüfen lassen* (nur im Modus *Fortlaufend*) und *Alle Kontakte prüfen lassen* speichern die Einstellungen und starten die Prüfungen sofort. Die Meldung zeigt, wie viele gestartet wurden, schon liefen oder keinen Ansprechpartner haben.
- **Stand** zeigt die offenen Prüfungen, wie viele noch nicht per E-Mail benachrichtigt und wie viele schon erinnert wurden, die fälligen Kontakte (fortlaufend) bzw. den nächsten Stichtag (jährlich) und bis zu 20 Kontakte ohne Ansprechpartner intern als Links. Weise ihnen einen Zuständigen zu (z. B. mit *Mehrere bearbeiten*).
- *Erinnern nach … Tagen (0 = nie)*: Wer offene Prüfungen hat, bekommt alle N Tage eine Erinnerung, bis alles erledigt ist.

### E-Mails

Prüfende bekommen pro Export-Intervall eine Sammel-E-Mail mit Links zu ihren Kontakten, in ihrer eigenen Sprache. Voraussetzungen:

- der E-Mail-Versand ist eingerichtet (*Einstellungen → E-Mail*),
- der Prüfende hat eine E-Mail-Adresse,
- die *Öffentliche Adresse* ist gesetzt (*Einstellungen → Allgemein*), sonst sind die Links in den E-Mails unvollständig.

Ohne E-Mail-Adresse oder eingerichteten Versand sind die Prüfungen trotzdem in der App sichtbar (Liste *Zu prüfen*). Die Texte aller E-Mails kannst du unter [E-Mail](#e-mail) anpassen.

### Vorschlags-E-Mails

Unter *Vorschläge* schickt *Bearbeiter per E-Mail über neue und geänderte Vorschläge informieren* den Bearbeitern eine Sammel-E-Mail mit neuen und geänderten Vorschlägen. *Empfänger*: kommagetrennte Adressen; leer = alle aktiven Bearbeiter und Admins mit E-Mail-Adresse (niemand bekommt Post zu den eigenen Vorschlägen).

### Benachrichtigungen (Push)

Benutzer bekommen neue Prüfungen, wartende Vorschläge und Entscheidungen über ihre Vorschläge auch als Benachrichtigung aufs Handy oder in den Browser (siehe Benutzerhandbuch, *Benachrichtigungen*). Einzurichten ist nichts: Kartei erzeugt seinen Schlüssel (VAPID) beim ersten Gebrauch selbst und speichert ihn verschlüsselt. Es braucht kein Apple- oder Google-Konto. Voraussetzungen:

- Kartei läuft über **HTTPS**. Browser erlauben Benachrichtigungen nur dort (Ausnahme: `localhost`).
- Der Container `exporter` erreicht die Push-Dienste der Browser per HTTPS (Port 443): `fcm.googleapis.com` (Chrome, Edge auf Android), `*.push.apple.com` (Safari, iPhone), `*.push.services.mozilla.com` (Firefox), `*.notify.windows.com` (Edge unter Windows). Über einen Proxy: `HTTPS_PROXY` in der `.env` setzen (siehe [Netzwerk und Firewall](#netzwerk-und-firewall)).
- Die *Öffentliche Adresse* (*Einstellungen → Allgemein*) sollte gesetzt sein. Apple verlangt eine Kontaktangabe und bekommt diese Adresse (sonst die Absenderadresse der E-Mails).

Kartei schickt nur Anzahl und Link, keine Kontaktdaten. Die Nachricht ist bis zum Gerät verschlüsselt, der Push-Dienst kann sie nicht lesen. Benachrichtigungen gehen unabhängig vom E-Mail-Versand raus, auch wenn die Vorschlags-E-Mails aus sind; Erinnerungen gibt es nur per E-Mail. Wird `SECRET_KEY` geändert, erzeugt Kartei einen neuen Schlüssel, und die Geräte melden sich beim nächsten Öffnen der App neu an.

## E-Mail

Unter *Einstellungen → E-Mail* legst du fest, wie Kartei seine E-Mails (neue Prüfungen, Erinnerungen, Vorschläge) verschickt und was darin steht. Solange kein Versandweg vollständig eingerichtet ist, verschickt Kartei keine E-Mails.

![Reiter E-Mail](../img/de/settings-mail.png)

### Versand

Unter dem Hinweis wählst du einen von zwei Versandwegen:

**SMTP-Server**

| Einstellung | Hinweise |
|---|---|
| *SMTP-Server*, *Port* | z. B. `smtp.example.de`, 587 |
| *Verschlüsselung* | *STARTTLS* (Port 587), *SSL/TLS* (Port 465) oder *keine* |
| *Benutzername (optional)*, *Passwort* | nur, wenn der Server eine Anmeldung verlangt; das Passwort wird verschlüsselt gespeichert |
| *Absender* | z. B. `Kartei <kartei@example.de>`; Pflicht |

**Microsoft 365 (Exchange Online, OAuth2)**

Kartei versendet über Microsoft Graph (`sendMail`) mit OAuth2 – ohne Passwort und ohne Basic Auth. Dafür nutzt es die App-Registrierung aus dem Reiter [Outlook / Exchange](#outlook-sync) (Mandanten-ID, Anwendungs-ID, Clientschlüssel); der Outlook-Sync selbst muss dafür nicht aktiv sein.

1. Gib der App-Registrierung die Microsoft-Graph-Anwendungsberechtigung `Mail.Send` und erteile die Administratorzustimmung.
2. Beschränke die Berechtigung auf das sendende Postfach, z. B. mit einer Application Access Policy für eine E-Mail-aktivierte Sicherheitsgruppe, die nur dieses Postfach enthält (wie beim Outlook-Sync gezeigt), oder mit RBAC für Anwendungen. Ohne Beschränkung darf die App im Namen jedes Postfachs im Mandanten senden.
3. Trag das *Sendende Postfach* ein, z. B. `kartei@example.de`. Die E-Mails gehen von diesem Postfach aus und landen nicht in dessen Gesendeten Elementen.

### Test

Trag unter *Empfänger für die Test-E-Mail* eine Adresse ein und klick auf *Speichern & Test senden*. Fehler zeigt Kartei so an, wie der SMTP-Server bzw. Microsoft 365 sie liefert.

### E-Mail-Texte

Unter *E-Mail-Texte* passt du Betreff und Text jeder E-Mail an, getrennt nach Sprache:

1. Wähl die *E-Mail* (*Neue Prüfungen*, *Erinnerung*, *Neue Vorschläge (an Bearbeiter)*) und die *Sprache*.
2. Bearbeite *Betreff* und *Text*. Leer gelassene Teile nutzen den Standardtext.
3. Klick auf *Speichern*.

Platzhalter:

| Platzhalter | Wird ersetzt durch |
|---|---|
| `{name}` | den Vornamen (oder Benutzernamen) des Empfängers; bei festen Vorschlags-Empfängern eine allgemeine Anrede |
| `{n}` | die Anzahl der Kontakte bzw. Vorschläge |
| `{items}` | die Liste der Kontakte bzw. Vorschläge mit Links |
| `{url}` | den Link zur Liste in Kartei (*Zu prüfen* bzw. *Vorschläge*) |

Jeder Empfänger bekommt den Text in seiner Sprache (oder in der Standardsprache, wenn er keine gewählt hat). Texte mit unbekanntem Platzhalter oder einzelner geschweifter Klammer lehnt Kartei beim Speichern ab (*Unbekannter Platzhalter oder einzelne geschweifte Klammer*). Ist ein gespeicherter Text trotzdem unbrauchbar, verschickt Kartei den Standardtext. *Standardtext* verwirft deine Änderungen für die gewählte E-Mail und Sprache.

> Tipp: Die Links in den E-Mails werden aus der *Öffentlichen Adresse* unter *Allgemein* gebildet. Setz sie, bevor die ersten E-Mails rausgehen.
{: .tip}

## Allgemeine Einstellungen {#allgemeine-einstellungen}

![Reiter Allgemein](../img/de/settings-general.png)

| Einstellung | Bedeutung |
|---|---|
| *Standardsprache* | Sprache für alle, die unter *Mein Konto* keine eigene gewählt haben, und für E-Mails an feste Empfänger. Die Anmeldeseite folgt der Browsersprache. |
| *Zwei-Faktor-Anmeldung Pflicht für* | *Niemanden (freiwillig)*, *Administratoren* oder *Alle*. Betroffene ohne sie sehen nach der Anmeldung nur die Einrichtung (Authenticator-App, Passwort, Wiederherstellungscodes) und können sie nicht abschalten; das gilt auch für dich. Alle anderen können sie weiterhin unter *Mein Konto* einschalten. |
| *Öffentliche Adresse* | z. B. `https://kartei.example.de`. Für Links in E-Mails, in vCards (`SOURCE`) und für die CardDAV-Adresse. |
| *Kartenlink* | Link neben Adressen in der Kontaktansicht. `{address}` wird durch Straße, PLZ, Ort und Land ersetzt. Standard: Google Maps (`https://www.google.com/maps/search/?api=1&query={address}`); z. B. `https://www.openstreetmap.org/search?query={address}` für OpenStreetMap. Kartei baut nur den Link und spricht den Kartendienst nie selbst an; der Browser öffnet ihn beim Klick. Leer: kein Link. Die Adressfelder erkennt Kartei an ihrer vCard-Zuordnung (Adresse geschäftlich und privat). |
| *Logo auf der Telefonliste* | *Kartei-Logo* (Standard), *Eigenes Logo* oder *Kein Logo*: steht oben auf der Telefonliste, im PDF und beim Drucken. *Logo hochladen …* nimmt ein PNG oder JPEG (höchstens 512 KB) und wählt es aus; *Entfernen* kehrt zum Kartei-Logo zurück. |
| *Papierkorb automatisch leeren nach (Tagen)* | Kontakte im Papierkorb werden nach so vielen Tagen endgültig gelöscht. *0* = nie (Standard). |
| *Aufbewahrung (Monate)* | Kontakte, die so lange weder geändert noch geprüft wurden, erscheinen unter *Datenqualität → Aufbewahrung abgelaufen*; Bearbeiter behalten sie dort oder verschieben sie in den Papierkorb. Automatisch gelöscht wird nichts. *0* = aus (Standard). Üblich sind z. B. 36. |
| *Beim endgültigen Löschen den Verlauf anonymisieren* | An (Standard): Ein endgültig gelöschter Kontakt verliert auch im Verlauf und im Protokoll Name und Werte; siehe [Datenschutz](#datenschutz). |
| *Export-Intervall (Minuten)* | Takt aller Hintergrundaufgaben (siehe [Hintergrundaufgaben](#hintergrundaufgaben)). Standard 15, mindestens 1. |

### Telefonnummern

Mit *Telefonnummern beim Speichern vereinheitlichen* werden nationale Nummern mit der *Standard-Ländervorwahl* international gespeichert:

- `0511 1000-12` → `+49 511 1000-12`; auch `0049 …` und `+49 (0)…` werden umgewandelt.
- Die Gruppierung, die jemand eingetippt hat, bleibt erhalten; Klammern und Schrägstriche werden zu Leerzeichen.
- Interne Durchwahlen ohne führende 0 oder + bleiben, wie sie sind.

So können Telefone und Systeme zur Anruferkennung eingehende Anrufe zuverlässig zuordnen.

Nummern, die vorher gespeichert wurden (z. B. nach dem Import), wandelst du so um:

1. Klick auf *Bestehende Nummern prüfen*. Die Einstellungen werden gespeichert, und Kartei zeigt, wie viele Kontakte sich ändern würden, mit Beispielen.
2. Klick auf *n Kontakte jetzt vereinheitlichen*. Jeder geänderte Kontakt bekommt einen Eintrag im Verlauf.

![Ergebnis der Nummernprüfung](../img/de/settings-general-phones.png)

## Datenqualität und Dubletten

Admins und Bearbeiter finden *Datenqualität* und *Dubletten* im Benutzermenü und auf der Startseite:

- **Datenqualität** listet Kontakte ohne Zuständigen, mit ungültigen Werten (z. B. nach einer neuen Formatregel), Personen ohne E-Mail und Telefon, Personen ohne Firma, Firmen ohne Personen sowie nie oder überfällig geprüfte Kontakte.
- **Dubletten** listet Paare mit gleicher E-Mail-Adresse, Telefonnummer oder gleichem Namen, die sich zusammenführen oder verwerfen lassen.

Beides beschreibt das [Benutzerhandbuch](user.html). Hast du die Formatregel oder das Pflichtfeld-Häkchen eines Felds geändert, schau unter *Ungültige Werte* nach: Vorhandene Daten werden nicht automatisch angepasst.

Von Bearbeitern gelöschte Kontakte landen im Papierkorb (Benutzermenü → *Papierkorb*). Beim Löschen einer Firma können Bearbeiter wählen, ob ihre Personen mitgehen. Nur Admins können *Endgültig löschen*, nach einer Rückfrage, die warnt, dass sich das nicht rückgängig machen lässt; ansonsten gilt die Aufbewahrungsdauer unter *Allgemein*.

## API

Andere Systeme können die Kontakte über eine REST-API mit einem Token lesen und mit einem Schreib-Token auch anlegen, ändern und löschen. Token sehen dieselben Felder wie ein Benutzer mit der Rolle Nur Lesen (Felder, die für *Alle* sichtbar sind). Die vollständige Referenz für Entwickler (Endpunkte, Delta-Abgleich, Werttypen, Fehler, Beispiele, OpenAPI-Datei) steht in `docs/API.md` im Kartei-Repository (auf Englisch).

![Reiter API](../img/de/settings-api.png)

### Token verwalten

1. *Einstellungen → API*: *Name* eingeben (z. B. „Telefonanlage“), die *Berechtigung* wählen und auf *Token erzeugen* klicken:
   - *Nur lesen* (Standard): Das System kann Kontakte nur lesen.
   - *Lesen und schreiben*: Das System kann Kontakte auch anlegen, ändern und löschen.
2. Das Token (`kt_…`) wird **nur jetzt** angezeigt, zusammen mit seiner Berechtigung. Kopier es in das andere System.
3. Die Liste zeigt die *Berechtigung* jedes Tokens und wann es *Erstellt* und *Zuletzt benutzt* wurde.
4. Das Papierkorbsymbol (*Widerrufen*) fragt nach und löscht dann das Token. Systeme, die es nutzen, verlieren sofort den Zugriff.

Die Berechtigung lässt sich später nicht ändern: Erzeug ein neues Token mit der anderen Berechtigung und widerruf das alte.

![Neues API-Token, nur einmal angezeigt](../img/de/settings-api-token.png)

Kartei speichert nur einen Hash des Tokens; ein verlorenes Token lässt sich nicht noch einmal anzeigen. Erzeug ein neues und widerruf das alte.

### Endpunkte

```sh
curl -H "Authorization: Bearer kt_…" https://kartei.example.de/api/v1/contacts
curl -H "Authorization: Bearer kt_…" "https://kartei.example.de/api/v1/contacts?updated_since=2026-10-24T08:00:00%2B00:00"
curl -H "Authorization: Bearer kt_…" https://kartei.example.de/api/v1/contacts/<uid>
```

| Anfrage | Antwort |
|---|---|
| `GET /api/v1/contacts` | `{"cursor", "full": true, "contacts": [...]}` mit allen Kontakten |
| `GET /api/v1/contacts?updated_since=<cursor>` | nur die seitdem geänderten Kontakte, dazu `deleted` (zu entfernende UIDs). Ist der Cursor älter als die Aufbewahrung im Papierkorb, kommt die vollständige Liste mit `"full": true`. |
| `GET /api/v1/contacts/<uid>` | ein Kontakt, oder 404 |

Jeder Kontakt hat `uid`, `kind` (`person`/`company`), `legacy_id`, `first_name`, `last_name`, `name`, `display_name`, `company` (UID) und `company_name`, `data` (Feldschlüssel → Wert; Benutzerfelder enthalten Benutzernamen, Kontaktfelder UIDs) und `updated_at`.

**Delta-Sync:** Merk dir den `cursor` jeder Antwort und gib ihn beim nächsten Mal als `updated_since` mit. Das `+` der Zeitzone musst du als `%2B` codieren.

Mit einem Token *Nur lesen* ist nur `GET` erlaubt; alles andere ergibt 403. Ein falsches Token ergibt 401; nach 20 Fehlversuchen innerhalb von 15 Minuten von einer Adresse antwortet die API 15 Minuten lang mit 429.

### Schreib-Token

Ein Token *Lesen und schreiben* arbeitet wie ein **Bearbeiter, der nur die Felder sieht, die für *Alle* sichtbar sind**:

| Anfrage | Wirkung |
|---|---|
| `POST /api/v1/contacts` | legt eine Person oder Firma an (`kind`, Namen, `company`, `data`) |
| `PATCH /api/v1/contacts/<uid>` | ändert nur die mitgeschickten Schlüssel; `null` leert ein Feld. Mit `version` ergibt ein zwischenzeitlich geänderter Kontakt 409, statt ihn zu überschreiben. |
| `DELETE /api/v1/contacts/<uid>` | verschiebt den Kontakt in den Papierkorb; `?with_persons=1` verschiebt bei einer Firma auch ihre Personen |

- Felder, die nur Admins bearbeiten dürfen, ergeben den Fehler `forbidden`; Felder, die nicht für *Alle* sichtbar sind, `unknown_field`. Werte in diesen Feldern bleiben unverändert.
- Ungültige Werte ergeben 400 mit einem Fehler pro Feld, wie im Formular der Weboberfläche.
- Jede Änderung steht im Verlauf des Kontakts und im Protokoll mit dem Benutzer **`api:<Token-Name>`**. Gib Token deshalb eindeutige Namen (z. B. „CRM-Sync“).
- Telefonnummern werden normalisiert, neue Optionen offener Auswahlfelder ergänzt, und offene Prüfungen folgen einem geänderten Verantwortlichen – wie in der Weboberfläche.
- Gelöschte Kontakte kannst du wie gewohnt aus dem Papierkorb wiederherstellen.

Gib ein Schreib-Token nur Systemen, die wirklich Daten ändern müssen, und bewahr es so sicher auf wie ein Passwort.

### Webhooks

Statt Kartei alle paar Minuten abzufragen, können andere Systeme sofort benachrichtigt werden: Ein **Webhook** schickt jede Änderung an einem Kontakt als HTTPS-Anfrage an die Adresse des Systems, signiert mit einem geheimen Schlüssel.

![Webhooks im Reiter API](../img/de/settings-webhooks.png)

1. Trag unter *Webhooks* einen *Namen* und die *Adresse (URL)* ein, die dir das empfangende System nennt.
2. Wähl bei Bedarf die *Ereignisse* (angelegt, geändert, gelöscht, wiederhergestellt); keine Auswahl heißt alle.
3. *Webhook anlegen* zeigt den **geheimen Schlüssel** einmal an. Trag ihn im empfangenden System ein; damit prüft es, dass die Anfragen wirklich von Kartei kommen.
4. *Test-Ereignis senden* (Papierflieger) schickt sofort eine Testanfrage und zeigt das Ergebnis.

- Der Inhalt ist der Kontakt mit den Feldern, die für *Alle* sichtbar sind – wie in der REST-API. Die Entwicklerdokumentation (`docs/API.md`, *Webhooks*) beschreibt die Anfrage und die Prüfung der Signatur.
- Kartei stellt innerhalb von etwa 10 Sekunden zu. Fehlgeschlagene Zustellungen werden etwa einen Tag lang wiederholt; die Tabelle zeigt das letzte Ergebnis und wie viele Zustellungen warten oder aufgegeben wurden.
- *Aktiv* schaltet einen Webhook ab, ohne ihn zu löschen; das Schlüsselsymbol erzeugt einen neuen geheimen Schlüssel (der alte gilt sofort nicht mehr).
- Anlegen, Ändern und Löschen von Webhooks steht im Protokoll.

## Protokoll

*Einstellungen → Protokoll* listet jede Änderung mit Zeitpunkt, Benutzer, Aktion, Objekt und den geänderten Werten (alter Wert durchgestrichen → neuer Wert).

![Reiter Protokoll](../img/de/settings-audit.png)

- **Filtern** nach Bereich: *Alle Bereiche*, *Kontakt*, *Feld*, *Benutzer*, *Einstellungen*, *Export*, *API-Token*, *Anmeldungen*.
- **Suchen** in Objektnamen und Benutzernamen (*Objekt oder Benutzer suchen …*).
- Es werden je 100 Einträge geladen; *Ältere laden* holt weitere.

Was protokolliert wird:

| Bereich | Einträge |
|---|---|
| Kontakt | Anlegen, Ändern, Löschen, Wiederherstellen, endgültiges Löschen (auch durch das automatische Leeren), Import, Massenänderungen, Zusammenführen, Vorschläge und Entscheidungen, Prüfungen, Vereinheitlichung von Telefonnummern |
| Feld | Anlegen, Ändern, Archivieren, Löschen, Umsortieren, Feldimport, vom CSV-Import angelegte Felder; beim Eingeben neu angelegte Auswahlwerte |
| Benutzer | Anlegen, Ändern (Rolle, Aktiv, Name), Passwortänderungen (maskiert), Löschen, Änderungen durch den AD-Benutzerimport |
| Einstellungen | jede Änderung (Passwörter und Schlüssel als `***` maskiert), neues CardDAV-Passwort, *Jetzt synchronisieren*, gestartete Prüfungen, Umwandlung der Telefonnummern |
| Export | Änderungen an Exportprofilen und jeder Listenexport durch Benutzer (mit Zeilenzahl) |
| API-Token | Erzeugen (mit Berechtigung), Widerrufen |
| Anmeldungen | Anmeldung (mit Verfahren: Passwort, LDAP, Single Sign-on), Abmeldung, fehlgeschlagene Anmeldung (mit Grund), abgelehnter CardDAV- oder API-Zugang, verweigerter Zugriff auf eine Admin- oder Bearbeiter-Funktion |

Zu jedem Eintrag wird außerdem die IP-Adresse des Aufrufers gespeichert; nur Admins sehen sie, in der Spalte *Benutzer*.

![Anmeldungen im Protokoll](../img/de/audit-signins.png)

Anmeldeeinträge enthalten IP-Adressen und werden nach den Tagen gelöscht, die unter *Einstellungen → Monitoring & Protokolle → Anmeldeeinträge aufbewahren* eingestellt sind (Standard 90; 0 = für immer). Ein abgelehnter CardDAV- oder API-Zugang wird je Adresse und 15 Minuten einmal protokolliert, damit ein Telefon mit altem Passwort das Protokoll nicht füllt. Alle anderen Einträge bleiben erhalten.

Nicht protokolliert werden die einzelnen Läufe von Exporten und Syncs (deren Ergebnis zeigt der jeweilige Reiter, das Log des `exporter` und der [Monitoring-Status](#monitoring)). Automatische Aktionen erscheinen als Benutzer *system*, Änderungen über ein Schreib-Token als `api:<Token-Name>`. Das Protokoll an ein SIEM senden: siehe [Syslog an das SIEM](#monitoring).

Jeder Kontakt hat außerdem einen eigenen Reiter *Verlauf*, siehe [Benutzerhandbuch](user.html).

## Monitoring und Protokolle {#monitoring}

*Einstellungen → Monitoring & Protokolle* zeigt den Zustand von Kartei und seinen Hintergrundaufgaben, gibt Monitoring-Systemen Zugriff darauf und sendet Protokolleinträge an dein SIEM.

![Reiter Monitoring & Protokolle](../img/de/settings-monitoring.png)

### Endpunkte

| Adresse | Zugriff | Antwort |
|---|---|---|
| `/healthz` | offen | `{"status": "ok"}`: der Webprozess läuft (ohne Datenbankprüfung). Für Container- und Loadbalancer-Prüfungen. |
| `/readyz` | offen | `{"status": "ok"}` (HTTP 200), wenn die Datenbank erreichbar und migriert ist, sonst `{"status": "fail"}` mit HTTP **503**. |
| `/api/monitoring/status` | Token **und** erlaubte Adresse | alle Prüfungen und Kennzahlen als JSON; `?format=prtg` im Format des PRTG-Sensors *HTTP-Daten (erweitert)* |

Der ausführliche Status braucht beides:

1. **Token:** *Token erzeugen* zeigt ihn einmal an (`kmon_…`); er wird als `Authorization: Bearer kmon_…` mitgeschickt. *Neuen Token erzeugen* ersetzt ihn.
2. **Erlaubte Adressen:** eine IP-Adresse oder ein Netz pro Zeile, z. B. `10.0.5.20` oder `10.0.6.0/24`. Leer heißt: niemand. Hinter dem Reverse Proxy zählt die Adresse aus `X-Forwarded-For` (siehe [Sicherheit](#sicherheit)).

Fehlender oder falscher Token: HTTP 401; Adresse nicht erlaubt: HTTP 403. Mehr verrät keine der beiden Antworten.

```sh
curl -H "Authorization: Bearer kmon_…" https://kartei.example.de/api/monitoring/status
```

```json
{"status": "warn", "version": "0.5.0-beta", "at": "…",
 "checks": [{"name": "database", "status": "ok", "detail": "", "age_s": null},
            {"name": "exporter", "status": "ok", "detail": "", "age_s": 42},
            {"name": "export:Telefonbuch", "status": "warn", "detail": "…", "age_s": 11000}],
 "metrics": {"persons": 1840, "companies": 412, "login_failures_1h": 0, "…": 0}}
```

`status` ist das schlechteste Ergebnis aller Prüfungen: `ok`, `warn` oder `crit`.

| Prüfung | warn | crit |
|---|---|---|
| `database` | – | nicht erreichbar oder Migrationen ausstehend |
| `exporter` | seit 2 Exportintervallen kein Lebenszeichen | seit 3 Intervallen oder noch nie |
| `export:<Name>` (automatische Exporte) | seit 3 Intervallen nicht gelaufen | letzter Lauf fehlgeschlagen (z. B. vom Schrumpfschutz gestoppt) |
| `outlook`, `active_directory`, `carddav_relay` (wenn aktiv) | seit 3 Intervallen nicht gelaufen | letzter Lauf fehlgeschlagen |
| `ldap_users` (täglicher Import) | seit 3 Tagen nicht gelaufen | letzter Lauf fehlgeschlagen |
| `webhook:<Name>` | letzte Zustellung fehlgeschlagen | – |
| `syslog` (wenn aktiv) | – | Versand in der letzten Stunde fehlgeschlagen |
| `export_disk` | unter 10 % frei auf `/export` | unter 5 % frei |

Kennzahlen: Kontakte (`persons`, `companies`, `recycle_bin`), aktive Benutzer je Rolle, offene Prüfungen und Vorschläge, Anmeldungen und Fehlversuche der letzten Stunde und des letzten Tages, abgelehnte CardDAV-/API-Zugriffe, Protokolleinträge pro Tag, die Syslog-Zähler sowie aus dem täglichen Datenqualitäts-Stand der Anteil der innerhalb des Intervalls geprüften Kontakte (`reviewed_ok_percent`) und, mit Aufbewahrungsdauer, die Kontakte darüber hinaus (`retention_due`).

**Beispiele:**

- **Checkmk:** eine Regel *Check HTTP web service* für `/readyz` (erwartet 200) und eine für die Status-URL mit dem Header `Authorization: Bearer kmon_…`, die in der Antwort nach `"status": "ok"` sucht (oder `"warn"` als Warnung zulässt).
- **Zabbix:** ein Item *HTTP agent* auf die Status-URL mit dem Header und abhängige Items mit JSONPath, z. B. `$.status`, `$.checks[?(@.name=='exporter')].status.first()`, `$.metrics.login_failures_1h`. Trigger auf `status <> "ok"`.
- **PRTG:** ein Sensor *HTTP-Daten (erweitert)* auf `…/api/monitoring/status?format=prtg` mit dem Header. Jede Prüfung wird ein Kanal (0 ok, 1 warn, 2 crit, mit gesetzten Grenzwerten), jede Kennzahl ebenfalls.
- **Uptime Kuma** und ähnliche: ein HTTP-Monitor auf `/readyz`.

### Syslog an das SIEM

Kartei sendet jeden Protokolleintrag (siehe [Protokoll](#protokoll)) direkt an dein SIEM:

![Syslog-Einstellungen](../img/de/settings-syslog.png)

1. *An Syslog senden* anhaken, *Host* und *Port* eintragen und das *Protokoll* wählen: UDP, TCP oder TLS. Bei TLS das CA-Zertifikat einfügen, wenn das SIEM eine interne CA nutzt (leer = System-CAs), und *Serverzertifikat prüfen* eingeschaltet lassen.
2. *Facility* (Standard `local0`) und *Was gesendet wird* wählen: nur Protokolleinträge oder zusätzlich Warnungen und Fehler der Anwendung.
3. *Speichern & Testereignis senden* schickt ein Testereignis und zeigt das Ergebnis.

Jedes Ereignis ist eine RFC-5424-Nachricht (TCP und TLS mit Octet Counting, RFC 6587). Die Nachricht ist die JSON-Logzeile:

```text
<132>1 2026-11-06T14:36:46.215+00:00 web kartei 11 audit - {"ts": "…", "level": "WARNING", "logger": "kartei.audit",
  "msg": "login_failed session mallory", "audit": {"event": "login_failed", "area": "session", "object_id": "", "object": "mallory",
  "user": "mallory", "ip": "203.0.113.45", "changes": {"reason": [null, "invalid_credentials"]}}}
```

- MSGID ist `audit` für Protokolleinträge und `app` für Meldungen der Anwendung.
- Fehlgeschlagene Anmeldungen, abgelehnte und verweigerte Zugriffe haben den Schweregrad *warning*, alles andere *info*.
- Bei Kontakten werden nur die Namen der geänderten Felder gesendet, keine Werte. Benutzer, Einstellungen und Anmeldungen enthalten alten und neuen Wert; Passwörter und Schlüssel sind maskiert.
- Der Versand bremst Kartei nie aus. Ist das SIEM nicht erreichbar, werden Ereignisse zwischengespeichert (bis zu 10.000 je Prozess) und nachgesendet; Fehler zeigt der Status. Eine neue Einstellung gilt sofort im Prozess, der sie gespeichert hat, in den anderen innerhalb einer Minute.

### Container-Logs an das SIEM (Fluent Bit)

Sollen zusätzlich die vollständigen Container-Logs (Anfragen, Fehler, Datenbank) weitergeleitet werden, startest du den optionalen Fluent-Bit-Container mit der Ergänzung `compose.logging.yaml`:

```sh
# .env
COMPOSE_FILE=compose.yaml:compose.logging.yaml
SIEM_HOST=siem.example.de
SIEM_PORT=6514
SIEM_MODE=tls        # udp, tcp oder tls
SIEM_TLS=on          # zusammen mit SIEM_MODE=tls
```

```sh
docker compose up -d
```

Docker übergibt die Logs von `web`, `exporter` und `db` an Fluent Bit, das jede Zeile als RFC-5424-Syslog sendet; die Zeilen von Kartei kommen als JSON an, die der Datenbank als Text. `docker compose logs` funktioniert weiterhin. Weitere Einstellungen in der `.env.example`: `SIEM_TLS_VERIFY`, eine eigene CA (`SIEM_CA_HOST_FILE` und `SIEM_CA_FILE`), `SIEM_HOSTNAME`, `SIEM_FACILITY`.

> Kartei sendet seine Protokolleinträge selbst (vorheriger Abschnitt), deshalb überspringt Fluent Bit sie, damit nichts doppelt ankommt. Nutzt du nur Fluent Bit, setz `SIEM_SKIP_LOGGERS=^$`, dann werden sie mit weitergeleitet.
{: .tip}

## Datenschutz {#datenschutz}

Kartei enthält personenbezogene Daten. Zwei Funktionen helfen bei den Rechten der betroffenen Personen (DSGVO):

**Datenauskunft (Art. 15).** Am Kontakt öffnet das Dokumentsymbol (*Datenauskunft*, nur Admins) eine Aufstellung über alles, was Kartei zum Kontakt speichert – auch Felder, die nur Admins sehen –, den vollständigen Verlauf, Vorschläge und Prüfungen sowie **wohin die Daten gehen**: Telefone (CardDAV, Relay), Outlook / Exchange, Active Directory, die Exporte, die den Kontakt enthalten, API-Token und Webhooks, jeweils mit den betroffenen Feldern bzw. Spalten. *Drucken / PDF* druckt sie oder speichert sie als PDF für die Person. Die Erstellung steht im Verlauf des Kontakts.

![Datenauskunft](../img/de/report.png)

**Löschung (Art. 17).** Löschen verschiebt einen Kontakt zunächst in den Papierkorb. *Endgültig löschen* (oder das automatische Leeren unter *Allgemein*) entfernt ihn dauerhaft. Mit *Beim endgültigen Löschen den Verlauf anonymisieren* (Standard: an) behalten seine Einträge in Verlauf und Protokoll danach nur, wer wann was getan hat; Name und alle Werte werden entfernt (angezeigt als *(anonymisiert)*). Schalte das nur ab, wenn du die Werte aus einem dokumentierten Grund brauchst.

> Bereits weitergegebene Daten (Exportdateien, andere Systeme über API oder Webhooks) löscht Kartei nicht selbst: Der nächste Export enthält den Kontakt nicht mehr, Telefone und Outlook entfernen ihn beim nächsten Abgleich; andere Systeme müssen ihn selbst löschen (das Webhook-Ereignis `contact.deleted` sagt es ihnen).
{: .tip}

## Sicherheit

- **`SECRET_KEY`:** Das LDAP-Passwort, das Passwort des AD-Schreibkontos, der Outlook-Clientschlüssel und das SMTP-Passwort werden mit einem aus dem `SECRET_KEY` abgeleiteten Schlüssel verschlüsselt gespeichert. Ändert sich der Schlüssel, sind diese Werte verloren (sie gelten als leer) und müssen neu eingegeben werden; außerdem werden alle Benutzer abgemeldet. Halte den `SECRET_KEY` stabil und in der Sicherung.
- **Nur einmal angezeigt:** Das CardDAV-Passwort, die API-Token und der Monitoring-Token werden nur als Hash gespeichert. Sie erscheinen einmal beim Erzeugen; danach lassen sie sich nur ersetzen.
- **Sperren nach Fehlversuchen:** Nach 10 fehlgeschlagenen Anmeldungen für einen Benutzernamen, 20 verschiedenen fehlgeschlagenen CardDAV-Anmeldungen bzw. 20 verschiedenen ungültigen API-Token ist die Absenderadresse 15 Minuten gesperrt. Dieselbe falsche Anmeldung wiederholt (ein Telefon oder Skript mit altem Passwort) zählt nur einmal und sperrt so nicht alle anderen hinter derselben Adresse aus. Die Zähler gelten für alle Serverprozesse gemeinsam. Hinter dem Reverse Proxy ist die Adresse der letzte Eintrag von `X-Forwarded-For`, der nur von `TRUSTED_PROXIES` geglaubt wird; sorg dafür, dass der Proxy ihn anhängt (ohne Proxy: `PROXY_HEADERS=0`).
- **Geheimnisse beim Start:** Kartei startet nicht mit dem Beispiel-`SECRET_KEY` aus der `.env.example` oder einem kürzeren als 32 Zeichen und legt den ersten Admin nicht mit dem Beispielpasswort oder einem kürzeren als 10 Zeichen an.
- **HSTS:** Lass den Reverse Proxy `Strict-Transport-Security` senden (z. B. `max-age=31536000`), damit Browser nur noch HTTPS verwenden.
- **OpenID Connect:** Ordne Konten über ein Claim zu, das Benutzer beim Identity Provider nicht selbst ändern können (Entra ID: `upn` oder `preferred_username`). Beim Claim `email` wird eine Adresse abgelehnt, die der Provider als nicht bestätigt kennzeichnet.
- **Nur HTTPS:** Cookies sind als *Secure* markiert. Lass `SECURE_COOKIES=1` im Betrieb.
- **Sicherheits-Header:** Kartei schickt mit jeder Antwort eine Content-Security-Policy (Skripte nur von Kartei selbst, kein Einbetten in fremde Seiten), eine Permissions-Policy und `Cross-Origin-Resource-Policy: same-origin`. Dein Reverse Proxy muss sie nicht ergänzen. Fügt er eine eigene Content-Security-Policy hinzu, wenden Browser beide an, es gilt also die strengere.
- **Zwei-Faktor-Anmeldung:** Schalte sie für jedes Admin-Konto ein, vor allem für das lokale aus der `.env` (*Mein Konto*), oder mach sie für Administratoren zur Pflicht (*Allgemeine Einstellungen*). CardDAV, REST-API und Webhooks betrifft sie nicht.
- **Minimale Rechte:** Das LDAP-Dienstkonto braucht nur Leserechte. Gib dem AD-Schreibkonto nur Rechte auf der Ziel-OU, beschränke die Outlook-App auf die Postfächer der Gruppe und `Mail.Send` auf das sendende Postfach.
- **Sichtbarkeit der Felder:** CardDAV, Outlook-Sync und API sehen nur Felder, die für *Alle* sichtbar sind. Exporte und der AD-Sync enthalten, was du einrichtest – schütze die Exportfreigabe entsprechend.
- **Notfallzugang:** Djangos eigene Admin-Seiten (`/django-admin/`) sind abgeschaltet. Dort meldet man sich ohne zweiten Faktor, Sperre und Protokoll an, und Änderungen umgehen die Prüfungen von Kartei. Nur im Notfall: `DJANGO_ADMIN=1` in die `.env`, `docker compose up -d`, als Superuser das Nötige erledigen, danach die Zeile entfernen und erneut `docker compose up -d`. Bei vergessenem Passwort reicht meist `docker compose exec web python manage.py changepassword admin`.

## Fehlersuche

| Problem | Ursache und Lösung |
|---|---|
| *Bad Request (400)* beim Aufruf | Der Hostname fehlt in `ALLOWED_HOSTS`. Ergänzen und `docker compose up -d` ausführen. |
| *Forbidden (403)* / CSRF-Fehler beim Anmelden oder Speichern | `CSRF_TRUSTED_ORIGINS` passt nicht genau zur Adresse im Browser (Schema, Host, Port), oder der Proxy sendet kein `X-Forwarded-Proto: https`. |
| Anmeldung klappt, aber man landet wieder auf der Anmeldeseite | Zugriff über reines HTTP: Das Secure-Cookie wird nicht gespeichert. HTTPS verwenden (oder `SECURE_COOKIES=0` nur für lokale Tests). |
| *Zu viele Versuche – bitte 15 Minuten warten* | 10 Fehlversuche für diesen Benutzernamen. Warten oder `web` neu starten, das setzt die Zähler zurück. |
| AD-Benutzer kann sich nicht anmelden | In keiner Rollengruppe (prüfen mit *Speichern & testen* und *Testbenutzer*), Konto deaktiviert, oder es gibt einen lokalen Benutzer mit demselben Namen. `docker compose logs web` ansehen. |
| LDAP-Test: *Can't contact LDAP server* | Server oder Port nicht erreichbar, oder das Zertifikat ist nicht vertrauenswürdig: Stammzertifikat unter *CA-Zertifikat* eintragen. |
| Benutzerimport: *Keine Benutzer in den Gruppen gefunden* | Die *Benutzer-Suchbasis* enthält die Gruppenmitglieder nicht, oder die Gruppen-DNs sind falsch. Es wurde nichts geändert. |
| Exportstatus *error*: *Zeilenzahl von … gefallen* / *Leerer Export …* | Der Schrumpfschutz hat gegriffen. Daten und Filter prüfen; ist der Rückgang gewollt, *Erzwingen*. |
| Exportfehler *Permission denied* | Das Exportverzeichnis ist für UID 1000 nicht beschreibbar, oder eine Netzwerkfreigabe ist nicht eingehängt (nach dem Einhängen die Container neu starten). |
| Exporte oder Syncs laufen nicht | Läuft `exporter` (`docker compose ps`)? `docker compose logs exporter`, *Export-Intervall* sowie *Export aktiv* / *Ausführung* prüfen. |
| AD-Sync: *… Kontakten würden gelöscht (Grenze … %)* | Der Schutz hat gegriffen. Mit *Speichern & Probelauf* prüfen; sind die Löschungen gewollt, *Max. Löschungen (%)* vorübergehend erhöhen. |
| AD-Sync: *Insufficient access* bei den Fehlern | Dem Schreibkonto fehlen Rechte auf der Ziel-OU. |
| Outlook: `HTTP 401` / `invalid_client` | Clientschlüssel falsch oder abgelaufen. Neuen Schlüssel erzeugen und eintragen. |
| Outlook: `HTTP 403` / *Access is denied* | Administratorzustimmung fehlt, oder das Postfach liegt außerhalb der Application Access Policy. |
| Outlook: *Die Gruppe hat keine Mitglieder mit Postfach* | Falsche Gruppen-ID, oder die Mitglieder haben kein Exchange-Online-Postfach. |
| iPhone verbindet sich nicht | CardDAV nicht aktiv, falsches Passwort (neues erzeugen), Proxy blockiert `PROPFIND`/`REPORT` oder den `Authorization`-Header, oder 20 Fehlversuche (15 Minuten warten). |
| Prüf-E-Mails kommen nicht an | Der Versand ist nicht vollständig eingerichtet (mit *Speichern & Test senden* prüfen), der Prüfende hat keine E-Mail-Adresse, oder `exporter` läuft nicht. Mailfehler stehen im Log des `exporter`. |
| Microsoft-365-Versand: `HTTP 403` | Der App fehlt die Anwendungsberechtigung `Mail.Send` (mit Administratorzustimmung), oder das sendende Postfach liegt außerhalb der Application Access Policy. |
| Geänderter E-Mail-Text wird nicht verwendet | Ein unbrauchbarer gespeicherter Text (z. B. nach einem Update) fällt auf den Standardtext zurück; das Log des `exporter` zeigt eine Warnung. Öffne *E-Mail-Texte* und speichere den Text neu. |
| Links in E-Mails oder die CardDAV-Adresse stimmen nicht | *Öffentliche Adresse* unter *Allgemein* setzen. |
| Gespeicherte Passwörter funktionieren plötzlich nicht mehr | Der `SECRET_KEY` hat sich geändert. LDAP-, AD-, Outlook- und SMTP-Passwort neu eingeben. |
| CSV-Import scheitert mit *413* | Der Reverse Proxy begrenzt die Upload-Größe (`client_max_body_size`). |
| Admin-Passwort vergessen | `docker compose exec web python manage.py changepassword <benutzername>` |
