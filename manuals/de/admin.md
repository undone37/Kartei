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
| Telefone ohne Postfach (z. B. Sammeltelefone) oder ohne Microsoft 365 | schreibgeschütztes CardDAV-Adressbuch (iPhone; Android braucht eine CardDAV-App) | *Einstellungen → CardDAV* |
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
| `PROXY_HEADERS` | `1` (Standard): Die Absenderadresse für die Sperren nach Fehlversuchen kommt aus dem letzten Eintrag von `X-Forwarded-For`, den der Reverse Proxy anhängt. Auf `0` setzen, wenn Kartei ohne Reverse Proxy erreichbar ist. |
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

### Sicherung

Sichere die Datenbank täglich per Cronjob auf dem Host, dazu einmalig die `.env` (sie enthält den `SECRET_KEY`):

```sh
# crontab von root, z. B. um 02:15
15 2 * * * cd /opt/kartei && docker compose exec -T db pg_dump -U kartei kartei | gzip > /backup/kartei-$(date +\%F).sql.gz
```

Die Datenbank enthält alles: Kontakte, Fotos, Felder, Benutzer, Einstellungen, Verlauf und Protokoll. Die Exportdateien lassen sich jederzeit mit *Jetzt ausführen* neu erzeugen.

Mit einem [eigenen PostgreSQL-Server](#eigener-postgresql-server) sicherst du die Datenbank mit euren üblichen PostgreSQL-Werkzeugen oder mit einem Client-Container (seine Version muss mindestens der des Servers entsprechen):

```sh
docker run --rm postgres:18 pg_dump "postgres://kartei:PASSWORT@pg.example.de:5432/kartei?sslmode=require" | gzip > /backup/kartei-$(date +%F).sql.gz
```

### Wiederherstellung

```sh
cd /opt/kartei
docker compose stop web exporter
docker compose exec -T db dropdb -U kartei kartei
docker compose exec -T db createdb -U kartei -O kartei kartei
gunzip -c /backup/kartei-2026-10-24.sql.gz | docker compose exec -T db psql -q -U kartei -d kartei
docker compose start web exporter
```

Verwende dieselbe `.env` (denselben `SECRET_KEY`) wie das System, von dem die Sicherung stammt.

### Logs

```sh
docker compose logs -f web          # Anfragen, Anmeldefehler
docker compose logs -f exporter     # Exporte, Syncs, Prüfungen, Benutzerimport
docker compose logs --since 1h exporter
```

Der `exporter` schreibt pro Export, Sync und Benutzerimport eine Zeile. Die Ergebnisse siehst du außerdem im jeweiligen Reiter der Einstellungen (*Letzter Lauf*).

### Healthcheck

- `docker compose ps` zeigt den Zustand von `web` (fragt alle 10 Sekunden `/api/session` ab) und `db`.
- Für ein externes Monitoring prüfst du `https://kartei.example.de/api/session` (HTTP 200 ohne Anmeldung).
- `exporter` hat keinen Healthcheck. Behalte den Stand der Exporte (*Einstellungen → Exporte*, Spalte *Letzter Lauf*) und der Syncs im Blick.

### Kommandozeile

Einige Aufgaben gibt es auch als Management-Befehl. Ohne `--commit` zeigen sie nur an, was sie tun würden.

```sh
docker compose exec web python manage.py import_csv /export/kontakte.csv [--mapping z.json] [--commit]   # CSV-Import
docker compose exec web python manage.py normalize_phones [--commit]                    # Telefonnummern
docker compose exec web python manage.py changepassword admin                           # lokales Passwort zurücksetzen
```

Änderungen von der Kommandozeile erscheinen im Protokoll als Benutzer *system*.

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

![Reiter Benutzer](../img/de/settings-users.png)

### Lokale Benutzer verwalten

*Einstellungen → Benutzer*:

- **Anlegen:** *Lokaler Benutzer* → *Benutzername*, *Passwort* (mindestens 10 Zeichen), optional Vor- und Nachname, *E-Mail* und *Rolle* eingeben → *Anlegen*. Für Prüf-E-Mails braucht der Benutzer eine E-Mail-Adresse.
- **Rolle ändern:** in der Spalte *Rolle* auswählen, das wirkt sofort.
- **Passwort zurücksetzen:** Schlüsselsymbol (*Passwort setzen*) → neues Passwort eingeben → *Speichern*.
- **Deaktivieren:** Haken bei *Aktiv* entfernen. Der Benutzer kann sich nicht mehr anmelden, bleibt aber in der Liste und in den Benutzerfeldern der Kontakte (als inaktiv markiert), bis du sie [übergibst](#leavers). Das ist meist besser als Löschen.
- **Zwei-Faktor-Anmeldung:** schalten die Benutzer selbst unter *Mein Konto* ein; die Liste kennzeichnet sie mit **2FA**. Hat jemand Handy und Wiederherstellungscodes verloren, schaltet das Schildsymbol (*Zwei-Faktor-Anmeldung zurücksetzen*) sie nach einer Rückfrage ab, sodass wieder das Passwort reicht (prüf die Anfrage vorher). Gilt für lokale und LDAP-Benutzer.
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
- Lokale Benutzer bleiben unberührt; ein AD-Konto mit dem Namen eines lokalen Benutzers zählt als *lokale übersprungen*.
- Werden gar keine Mitglieder gefunden (z. B. falsche Suchbasis), ändert sich nichts und es erscheint ein Fehler – ein Tippfehler kann also nicht alle Benutzer deaktivieren.

Das Feld unter der Schaltfläche zeigt den letzten Lauf: *neu · aktualisiert · deaktiviert · lokale übersprungen* oder den Fehler.

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
| *Kontakt (Person der Firma)* | Verweist auf eine Person derselben Firma, z. B. den Geschäftsführer. |

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
| *Als neues Textfeld anlegen* | ✓ | ✓ |
| *(ignorieren)* | ✓ | ✓ |

Kartei schlägt für jede Spalte ein Ziel vor: zuerst gängige Namen der Stammdaten (z. B. `Vorname`/`First name`, `Firma`/`Company`, `ID`), dann das Feld, dessen Schlüssel, Bezeichnung oder **Import-Spaltennamen** zur Überschrift passen (Groß-/Kleinschreibung, Akzente und Satzzeichen zählen nicht). Prüf den Vorschlag; leer heißt, die Spalte wird ignoriert.

*Als neues Textfeld anlegen* legt beim Import ein Textfeld mit der Spaltenüberschrift als Bezeichnung (und als Import-Spaltenname) an. Typ und Einstellungen passt du danach unter *Felder* an.

*Zuordnung exportieren* lädt die Zuordnung (samt Regeln für die Art) als JSON herunter; *Zuordnung importieren* lädt sie für die nächste Datei mit denselben Spalten wieder.

### Person oder Firma?

Kartei bestimmt die Art jeder Zeile in dieser Reihenfolge:

1. **Spalte mit der Art:** Ist sie gesetzt, bedeuten Werte wie `Person`/`Kontakt`/`Contact` Person und `Firma`/`Company`/`Organisation` Firma. Andere Werte ergeben einen Hinweis, dann greifen die nächsten Regeln. Eine Spalte namens `Art`, `Typ` oder `Type` wird vorausgewählt.
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
| *Zeichensatz* | *UTF-8 + BOM (Excel)* (außerdem UTF-8, Windows-1252) |
| *Zeilenende* | CRLF (Windows) |
| *Zeilenumbrüche in Werten* | *beibehalten* (in Anführungszeichen) oder *durch Leerzeichen ersetzen* – Letzteres für Skripte, die zeilenweise lesen |
| *Trenner Mehrfachauswahl* | `, ` |
| *Datumsformat*, *Dezimaltrenner* | `31.12.2026`, `1234,56` |
| *Ja / Nein als* | `Ja` / `Nein` |
| *Kopfzeile schreiben* | an |

### Excel-Optionen

*Tabellenblatt*, *Datumsformat* und *Zahlenformat* (Excel-Formatcodes), dazu *Kopfzeile*, *Kopfzeile fett*, *Autofilter*, *Kopfzeile fixieren* und *Spaltenbreite automatisch*. Datum und Zahlen werden als echte Excel-Werte geschrieben, nicht als Text.

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

1. *Einstellungen → CardDAV*: *Eingebauter CardDAV-Server aktiv* anhaken und *Speichern*.
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
2. In Kartei unter *Einstellungen → CardDAV → Externer Relay (DMZ)*: Trag die *Relay-URL* ein (`https://carddav.example.de`, nur HTTPS) und klick auf *Token erzeugen*. Kartei speichert das Push-Token verschlüsselt und zeigt nur seinen SHA-256-Wert. Kopier diesen Wert in die `.env.relay` als `RELAY_PUSH_TOKEN_SHA256`. Das Token selbst kommt nie auf den DMZ-Host.
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
2. Trag bei Bedarf unter *Name des Kontaktordners* einen anderen Ordnernamen ein.
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
- Drosselungen durch Microsoft fängt Kartei mit automatischen Wiederholungen ab; ein großer erster Lauf kann etwas dauern.

> Achtung: Änderst du später den Ordnernamen (*Name des Kontaktordners*), legt Kartei einen neuen Ordner an und lässt den alten in den Postfächern liegen. Leg den Namen vor dem ersten Sync fest.
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

## Allgemeine Einstellungen

![Reiter Allgemein](../img/de/settings-general.png)

| Einstellung | Bedeutung |
|---|---|
| *Standardsprache* | Sprache für alle, die unter *Mein Konto* keine eigene gewählt haben, und für E-Mails an feste Empfänger. Die Anmeldeseite folgt der Browsersprache. |
| *Öffentliche Adresse* | z. B. `https://kartei.example.de`. Für Links in E-Mails, in vCards (`SOURCE`) und für die CardDAV-Adresse. |
| *Papierkorb automatisch leeren nach (Tagen)* | Kontakte im Papierkorb werden nach so vielen Tagen endgültig gelöscht. *0* = nie (Standard). |
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

- **Filtern** nach Bereich: *Alle Bereiche*, *Kontakt*, *Feld*, *Benutzer*, *Einstellungen*, *Export*, *API-Token*.
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

Nicht protokolliert werden Anmeldungen und die einzelnen Läufe von Exporten und Syncs (deren Ergebnis zeigt der jeweilige Reiter und das Log des `exporter`). Automatische Aktionen erscheinen als Benutzer *system*, Änderungen über ein Schreib-Token als `api:<Token-Name>`.

Jeder Kontakt hat außerdem einen eigenen Reiter *Verlauf*, siehe [Benutzerhandbuch](user.html).

## Datenschutz {#datenschutz}

Kartei enthält personenbezogene Daten. Zwei Funktionen helfen bei den Rechten der betroffenen Personen (DSGVO):

**Datenauskunft (Art. 15).** Am Kontakt öffnet das Dokumentsymbol (*Datenauskunft*, nur Admins) eine Aufstellung über alles, was Kartei zum Kontakt speichert – auch Felder, die nur Admins sehen –, den vollständigen Verlauf, Vorschläge und Prüfungen sowie **wohin die Daten gehen**: Telefone (CardDAV, Relay), Outlook / Exchange, Active Directory, die Exporte, die den Kontakt enthalten, API-Token und Webhooks, jeweils mit den betroffenen Feldern bzw. Spalten. *Drucken / PDF* druckt sie oder speichert sie als PDF für die Person. Die Erstellung steht im Verlauf des Kontakts.

![Datenauskunft](../img/de/report.png)

**Löschung (Art. 17).** Löschen verschiebt einen Kontakt zunächst in den Papierkorb. *Endgültig löschen* (oder das automatische Leeren unter *Allgemein*) entfernt ihn dauerhaft. Mit *Beim endgültigen Löschen den Verlauf anonymisieren* (Standard: an) behalten seine Einträge in Verlauf und Protokoll danach nur, wer wann was getan hat; Name und alle Werte werden entfernt (angezeigt als *(anonymisiert)*). Schalte das nur ab, wenn du die Werte aus einem dokumentierten Grund brauchst.

> Bereits weitergegebene Daten (Exportdateien, andere Systeme über API oder Webhooks) löscht Kartei nicht selbst: Der nächste Export enthält den Kontakt nicht mehr, Telefone und Outlook entfernen ihn beim nächsten Abgleich; andere Systeme müssen ihn selbst löschen (das Webhook-Ereignis `contact.deleted` sagt es ihnen).
{: .tip}

## Sicherheit

- **`SECRET_KEY`:** Das LDAP-Passwort, das Passwort des AD-Schreibkontos, der Outlook-Clientschlüssel und das SMTP-Passwort werden mit einem aus dem `SECRET_KEY` abgeleiteten Schlüssel verschlüsselt gespeichert. Ändert sich der Schlüssel, sind diese Werte verloren (sie gelten als leer) und müssen neu eingegeben werden; außerdem werden alle Benutzer abgemeldet. Halte den `SECRET_KEY` stabil und in der Sicherung.
- **Nur einmal angezeigt:** Das CardDAV-Passwort und die API-Token werden nur als Hash gespeichert. Sie erscheinen einmal beim Erzeugen; danach lassen sie sich nur ersetzen.
- **Sperren nach Fehlversuchen:** Nach 10 fehlgeschlagenen Anmeldungen für einen Benutzernamen, 20 fehlgeschlagenen CardDAV-Anmeldungen bzw. 20 fehlgeschlagenen API-Anfragen ist die Absenderadresse 15 Minuten gesperrt. Hinter dem Reverse Proxy ist das der letzte Eintrag von `X-Forwarded-For`; sorg dafür, dass der Proxy ihn anhängt und Port 8000 nicht direkt erreichbar ist (ohne Proxy: `PROXY_HEADERS=0`).
- **Nur HTTPS:** Cookies sind als *Secure* markiert. Lass `SECURE_COOKIES=1` im Betrieb.
- **Zwei-Faktor-Anmeldung:** Schalte sie für jedes Admin-Konto ein, vor allem für das lokale aus der `.env` (*Mein Konto*). CardDAV, REST-API und Webhooks betrifft sie nicht.
- **Minimale Rechte:** Das LDAP-Dienstkonto braucht nur Leserechte. Gib dem AD-Schreibkonto nur Rechte auf der Ziel-OU, beschränke die Outlook-App auf die Postfächer der Gruppe und `Mail.Send` auf das sendende Postfach.
- **Sichtbarkeit der Felder:** CardDAV, Outlook-Sync und API sehen nur Felder, die für *Alle* sichtbar sind. Exporte und der AD-Sync enthalten, was du einrichtest – schütze die Exportfreigabe entsprechend.
- **Notfallzugang:** `/django-admin/` ist eine versteckte Rückfallebene für Superuser. Nutze sie nur im Notfall; Änderungen dort umgehen die Prüfungen von Kartei und landen nicht im Protokoll.

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
