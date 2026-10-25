---
title: Administrator manual
lang: en
role: admin
other: /de/admin.html
---

# Administrator manual

This manual is for the IT administrators who install, configure and run Kartei. It covers the Docker setup, operation (updates, backup, logs) and every tab of the *Settings* area. Everyday work with contacts (searching, editing, reviews, proposals, the recycle bin) is described in the [user manual](user.html).

## Overview

Kartei is the central contact directory for persons and companies. Admins define the fields, contacts are maintained in the web app, and Kartei passes the data on to other systems:

| Target | How | Configured under |
|---|---|---|
| Phones with an Exchange Online mailbox (iPhone and Android) | contact folder in each mailbox, stored on the phone by the Outlook app | *Settings → Outlook / Exchange* |
| Phones without a mailbox (e.g. shared phones), or without Microsoft 365 | read-only CardDAV address book (iPhone; Android needs a CardDAV app) | *Settings → CardDAV* |
| Systems that read contacts from Active Directory (e.g. caller ID of a phone system, address books of communication clients) | AD contact objects in one OU | *Settings → Active Directory* |
| Scripts, other applications, spreadsheet users | CSV/XLSX files in a directory | *Settings → Exports* |
| Other systems (e.g. intranet, phone system) | REST API with tokens (read only, or read and write) | *Settings → API* |

### Services

Kartei runs as three Docker containers (Compose project `kartei`):

| Service | Purpose |
|---|---|
| `web` | Django backend and the web app on port 8000 (gunicorn). On every start it runs the database migrations and creates the initial admin from `.env` if needed. |
| `exporter` | Runs all background jobs in a loop (see below). Same image as `web`. |
| `db` | PostgreSQL 18. The data lives in the Docker volume `pgdata`. Not started if Kartei uses a [dedicated PostgreSQL server](#dedicated-postgresql). |

Both `web` and `exporter` mount the export directory of the host as `/export`.

Optionally, a fourth container, the CardDAV relay, runs on a separate host in the DMZ (`compose.relay.yaml`); see [Relay in the DMZ](#relay-dmz).

### Background jobs

The `exporter` service runs one pass every *Export interval* (*Settings → General*, default 15 minutes):

| Job | Runs |
|---|---|
| Exports with schedule *automatic* | every pass; a file is only rewritten when its content changed |
| Recycle-bin purge | every pass, if a retention period is set |
| Reviews: start scheduled reviews, send review emails, reminders and proposal emails | every pass |
| Outlook sync | every pass if enabled; *Sync now* is picked up within about 10 seconds |
| AD contact sync | every pass if enabled; *Sync now* is picked up within about 10 seconds |
| Push to the CardDAV relay in the DMZ | every pass if enabled; *Sync now* is picked up within about 10 seconds |
| AD user import | once every 24 hours, if an LDAP server and at least one role group are set |

If a pass fails, the error is written to the log and the next pass starts after 5 minutes.

> Tip: Settings changes take effect immediately. You never need to restart a container after changing something in the web app.
{: .tip}

## Installation

### Requirements

- A Linux host with Docker and the Docker Compose plugin.
- A DNS name for Kartei (e.g. `kartei.example.de`) and a TLS certificate for it.
- A reverse proxy for HTTPS (e.g. nginx, Apache, Traefik). HTTPS is required: session cookies are only sent over HTTPS, and the web app can only be installed as an app (PWA) over HTTPS.
- Optional: a network share for the exports, mounted on the host.

### Configure `.env`

Only a few bootstrap values come from the environment. Everything else is configured in the web app and stored in the database.

```sh
cd /opt/kartei            # the checked-out repository
cp .env.example .env
```

| Variable | Meaning |
|---|---|
| `SECRET_KEY` | Long random string. Signs sessions and **encrypts the stored passwords** (LDAP, AD writing account, Outlook client secret, SMTP). Never change it later (see [Security](#security)). |
| `ALLOWED_HOSTS` | Host names under which Kartei is reached, comma-separated, without scheme: `kartei.example.de,localhost`. |
| `CSRF_TRUSTED_ORIGINS` | Full origins including scheme (and port, if not standard): `https://kartei.example.de`. |
| `POSTGRES_PASSWORD` | Password of the database user `kartei` in the bundled `db` container. |
| `DATABASE_URL`, `COMPOSE_FILE` | Only for a [dedicated PostgreSQL server](#dedicated-postgresql). |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Initial local admin. Created at start only if there is no active admin at all and the username is not taken yet. |
| `EXPORT_HOST_DIR` | Host directory mounted as `/export` (default `./export_out`). |
| `WEB_PORT` | Published port of `web` (default `8000`). `127.0.0.1:8000` publishes it on the loopback interface only. |
| `SECURE_COOKIES` | `1` (default). Set to `0` only for local tests over plain HTTP. |
| `PROXY_HEADERS` | `1` (default): the client address for the rate limits is taken from the last `X-Forwarded-For` entry, which the reverse proxy appends. Set to `0` if Kartei is reached without a reverse proxy. |
| `LOG_LEVEL` | Log level of `web` and `exporter` (default `INFO`). |
| `KARTEI_SOURCE_URL` | Link to the source code at the bottom of the user menu (default: the Kartei repository). If you run a modified version, point it to your code: the AGPL requires offering it to the users. |

Generate the secret like this:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

> Warning: Store `.env` in your password safe or backup. Without the same `SECRET_KEY`, a restored database loses its stored passwords.
{: .warn}

### Export directory

Exports are only written below `/export` inside the containers, which is `EXPORT_HOST_DIR` on the host. The containers run as user ID 1000, so this directory must be writable for UID 1000.

The directory can be a local directory or a network share that you mount on the host, for example:

```sh
# .env
EXPORT_HOST_DIR=/srv/kartei-export
```

> Warning: If the directory is a mount point, it must be mounted before the containers start. If it is mounted later (or remounted), restart the containers with `docker compose restart web exporter`, otherwise they keep writing into the directory below the mount point.
{: .warn}

### Dedicated PostgreSQL server (optional) {#dedicated-postgresql}

By default the stack starts its own PostgreSQL 18 container (`db`). If your organization runs PostgreSQL centrally, as a single server, a cluster or a managed cloud database, Kartei can use it instead.

**What the database needs**

- PostgreSQL 14 or newer (Kartei is tested with 18).
- An empty database with UTF-8 encoding, owned by a login role for Kartei. No superuser rights and no extensions are needed: Kartei creates and updates its tables itself on every start of `web`.

  ```sql
  CREATE ROLE kartei LOGIN PASSWORD 'a-long-random-password';
  CREATE DATABASE kartei OWNER kartei ENCODING 'UTF8';
  ```

- Network access from the Docker host to the server, and a `pg_hba.conf` entry for this role (preferably `hostssl … scram-sha-256`).
- Connections: each Kartei installation keeps up to about 15 connections open (`web`: 3 processes with 4 threads, plus `exporter`); idle ones are closed after 10 minutes.

**Configure Kartei**

Add two lines to `.env`:

```sh
DATABASE_URL=postgres://kartei:a-long-random-password@pg.example.de:5432/kartei?sslmode=verify-full&sslrootcert=system
COMPOSE_FILE=compose.yaml:compose.external-db.yaml
```

Then start (or restart) as usual with `docker compose up -d`. `compose.external-db.yaml` leaves out the `db` container and passes `DATABASE_URL` to `web` and `exporter`; `POSTGRES_PASSWORD` is not used.

| Part of `DATABASE_URL` | Notes |
|---|---|
| `kartei:password@` | Role and password. Percent-encode special characters in the password, e.g. `@` as `%40`, `:` as `%3A`, `/` as `%2F`. |
| `pg.example.de:5432` | Host and port of the server or of the cluster's write endpoint. |
| `/kartei` | Database name. |
| `?sslmode=…` | TLS: `verify-full` checks the certificate and the host name (recommended), `require` only encrypts, `disable` turns TLS off. |
| `&sslrootcert=…` | The CA for `verify-full`/`verify-ca`: `system` uses the CAs trusted by the container (public certificates, e.g. cloud databases); for an internal CA, give the path of a mounted file (see below). |

Further PostgreSQL connection parameters can be appended the same way, e.g. `connect_timeout=5` or `application_name=kartei`.

**Internal CA:** mount the CA certificate into both containers with a small extra file, e.g. `compose.local.yaml`:

```yaml
services:
  web:
    volumes: ["/etc/kartei/pg-ca.pem:/certs/pg-ca.pem:ro"]
  exporter:
    volumes: ["/etc/kartei/pg-ca.pem:/certs/pg-ca.pem:ro"]
```

and use it in `.env`: `COMPOSE_FILE=compose.yaml:compose.external-db.yaml:compose.local.yaml` and `…?sslmode=verify-full&sslrootcert=/certs/pg-ca.pem`.

**Clusters:** Kartei connects to one address. Point `DATABASE_URL` at the cluster's write endpoint: a virtual IP or DNS name that follows the primary (e.g. with Patroni), HAProxy, or the endpoint of a managed database. After a failover, Kartei checks each reused connection before using it and reconnects, so at most the requests running at that moment fail. PgBouncer works in session and transaction pooling mode.

**Moving from the bundled container to a dedicated server**

1. Create the role and the empty database on the new server (see above).
2. Stop Kartei and copy the data:

   ```sh
   cd /opt/kartei
   docker compose stop web exporter
   docker compose exec -T db pg_dump -U kartei --no-owner kartei \
     | docker run --rm -i postgres:18 psql -q "postgres://kartei:PASSWORD@pg.example.de:5432/kartei?sslmode=require"
   ```

3. Set `DATABASE_URL` and `COMPOSE_FILE` in `.env` as above and run `docker compose up -d`. The old `db` container is no longer started; once everything works, remove it and its data with `docker compose -f compose.yaml rm -s db` and `docker volume rm kartei_pgdata`.

Backup and restore of a dedicated server are usually done by its operators. For your own dumps, see [Backup](#backup).

### Start

```sh
docker compose up -d --build
docker compose ps          # web should become "healthy"
```

On the first start, `web` creates the database tables, a few default fields and the initial admin from `ADMIN_USERNAME`/`ADMIN_PASSWORD`.

### Reverse proxy

Put the TLS reverse proxy in front of port 8000. It must pass the `Host` header and `X-Forwarded-Proto`, append the client address to `X-Forwarded-For` (used for the rate limits), and it must not filter the WebDAV methods (`PROPFIND`, `REPORT`) or the `Authorization` header, which CardDAV and the API need. Example for nginx:

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name kartei.example.de;
    ssl_certificate     /etc/ssl/kartei/fullchain.pem;
    ssl_certificate_key /etc/ssl/kartei/privkey.pem;
    client_max_body_size 20m;            # CSV import

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

With the proxy on the same host, set `WEB_PORT=127.0.0.1:8000` so that port 8000 is not reachable from the network. Clients that could reach port 8000 directly could otherwise fake their address in `X-Forwarded-For`. If you run Kartei without a reverse proxy, set `PROXY_HEADERS=0`.

### First sign-in

1. Open `https://kartei.example.de` and sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD`.
2. Open the user menu (person icon, top right) → *My account* and change the password.
3. Remove `ADMIN_PASSWORD` from `.env`. It is not needed any more: Kartei only uses it while there is no active admin.

You reach the admin area through the user menu → *Settings*.

![User menu with Settings](../img/en/user-menu-admin.png)

## Operation

### Updating

1. Make a backup (see below).
2. Fetch the new version and rebuild:

   ```sh
   cd /opt/kartei
   git pull
   docker compose up -d --build
   ```

3. Check that `web` is healthy again: `docker compose ps`. Migrations run automatically when `web` starts; `exporter` waits for it.

### Backup

Back up the database daily from a host cron job, plus `.env` once (it holds `SECRET_KEY`):

```sh
# crontab of root, e.g. at 02:15
15 2 * * * cd /opt/kartei && docker compose exec -T db pg_dump -U kartei kartei | gzip > /backup/kartei-$(date +\%F).sql.gz
```

The database contains everything: contacts, photos, fields, users, settings, history and audit log. Export files can be recreated at any time with *Run now*.

With a [dedicated PostgreSQL server](#dedicated-postgresql), back up the database with your usual PostgreSQL tooling, or with a client container (its version must be at least the server's):

```sh
docker run --rm postgres:18 pg_dump "postgres://kartei:PASSWORD@pg.example.de:5432/kartei?sslmode=require" | gzip > /backup/kartei-$(date +%F).sql.gz
```

### Restore

```sh
cd /opt/kartei
docker compose stop web exporter
docker compose exec -T db dropdb -U kartei kartei
docker compose exec -T db createdb -U kartei -O kartei kartei
gunzip -c /backup/kartei-2026-10-24.sql.gz | docker compose exec -T db psql -q -U kartei -d kartei
docker compose start web exporter
```

Use the same `.env` (same `SECRET_KEY`) as the system the backup came from.

### Logs

```sh
docker compose logs -f web          # requests, sign-in errors
docker compose logs -f exporter     # exports, syncs, reviews, user import
docker compose logs --since 1h exporter
```

The `exporter` writes one line per export, sync and user import. Their results are also shown in the respective settings tab (*Last run*).

### Health check

- `docker compose ps` shows the health of `web` (it polls `/api/session` every 10 seconds) and of `db`.
- For external monitoring, check `https://kartei.example.de/api/session` (HTTP 200 without sign-in).
- `exporter` has no health check. Watch the status of the exports (*Settings → Exports*, column *Last run*) and of the syncs.

### Command line

Some tasks are also available as management commands. Without `--commit` they only show what they would do.

```sh
docker compose exec web python manage.py import_csv /export/contacts.csv [--mapping m.json] [--commit]   # CSV import
docker compose exec web python manage.py normalize_phones [--commit]                    # phone numbers
docker compose exec web python manage.py changepassword admin                           # reset a local password
```

Changes made on the command line appear as user *system* in the audit log.

## First steps

After installing, work through *Settings* in this order:

1. **LDAP / AD:** server, service account, one group per role, then *Save & test* and *Save & import users now*. The users then exist before you import data, so user fields in the imported data can be matched.
2. **Fields:** define the fields you need, or *Import fields* from a JSON file (e.g. `examples/fields-example.json`), then adjust labels, visibility and order.
3. **Import:** if you migrate from another system, upload its CSV export, check the column mapping and the *Dry run*, then *Run import*.
4. **General:** default language, *Public URL*, recycle-bin retention, export interval, phone-number normalization (*Check existing numbers* once after the import).
5. **Exports:** set up the files other systems need, check paths and columns, enable the exports and *Run now* once.
6. **Active Directory:** target OU and mapping, *Save & dry run*, then enable.
7. **CardDAV** (optional, for phones without a mailbox): enable, generate the password, set up the phones.
8. **Outlook / Exchange** (phones with an Exchange Online mailbox): app registration in Entra ID, *Save & test*, enable.
9. **Email** and **Review:** SMTP server or Microsoft 365 with a test mail, the email texts, then the review mode.
10. **API:** create tokens for other systems if needed.

## Users and roles

### Roles

Kartei has three fixed roles:

| Role | Can |
|---|---|
| Read only | view, search and export lists; confirm own reviews; propose changes and deletions |
| Maintainer | also create, edit, bulk-edit, delete (to the recycle bin) and restore contacts; accept or reject proposals; merge duplicates; see *Data quality* and recent changes |
| Admin | also delete permanently from the recycle bin, request reviews for single contacts, and everything under *Settings* |

In addition, each field can be restricted to *Maintainer & Admin* or *Admin only*, separately for viewing and editing (see [Fields](#fields)).

### Local and LDAP users

| | Local user | LDAP user |
|---|---|---|
| Created by | an admin (*Local user*) or `.env` (initial admin) | the user import or the first sign-in |
| Password | in Kartei (at least 10 characters) | in Active Directory |
| Role | set in the list | derived from the AD groups at every sign-in and import |
| Active | checkbox in the list | AD decides: membership in a role group and an enabled account |
| Name and email | set by the admin | taken from AD (`givenName`, `sn`, `mail`) |

Local users remain available as a fallback when the directory is unavailable. A local user always takes precedence: an AD account with the same username cannot sign in.

![Users tab](../img/en/settings-users.png)

### Manage local users

*Settings → Users*:

- **Create:** *Local user* → enter *Username*, *Password* (at least 10 characters), optionally first and last name, *Email* and *Role* → *Create*. Users need an email address to receive review emails.
- **Change role:** select it in the *Role* column; it takes effect at once.
- **Reset password:** key icon (*Set password*) → enter the new password → *Save*.
- **Deactivate:** clear *Active*. The user can no longer sign in, but stays in the list and in user fields of contacts (marked as inactive). Prefer this to deleting.
- **Delete:** trash icon, then confirm in the dialog. The account can no longer sign in, and its own saved filters (shared ones too) are deleted; contacts keep the user name in responsible fields. AD users come back with the next user import while they are in a role group. You cannot delete yourself.

> Note: The last active admin cannot be demoted, deactivated or deleted (*The last admin cannot be removed*). The initial admin from `.env` is a superuser (tooltip *Main administrator (superuser) – always admin*); its role cannot be changed in the list.
{: .tip}

### LDAP users

For LDAP users (*Source* `LDAP`), *Role*, *Active* and the password are greyed out. Change them in AD:

- add or remove the user in the role groups,
- disable or enable the AD account.

The change takes effect at the next sign-in or at the next user import (daily, or *Save & import users now*). Users who are no longer in any role group are **deactivated, not deleted**, so their name still appears in the contacts they are responsible for. If they are added to a group again, they are reactivated.

## LDAP / AD sign-in

*Settings → LDAP / AD* connects Kartei to Active Directory. Users then sign in with their AD username and password. With an empty *Server*, LDAP is off and only local users can sign in.

![LDAP / AD tab](../img/en/settings-ldap.png)

### Connection

| Setting | Example | Notes |
|---|---|---|
| *Server* | `ldaps://dc01.example.local` | LDAPS on port 636, or `ldap://dc01.example.local` together with *StartTLS*. |
| *StartTLS* | | Only with `ldap://`. Do not combine with `ldaps://`. |
| *Service account (bind DN)* | `CN=svc-kartei,OU=Service,DC=example,DC=local` | A normal domain user is enough; it only reads. |
| *Service account password* | | Stored encrypted. The field stays empty after saving; leave it empty to keep the stored password. |
| *User search base* | `OU=Users,DC=example,DC=local` | All users who should sign in must be below it. |
| *User filter* | `(sAMAccountName=%(user)s)` | Must contain `%(user)s`. The attribute in the filter is also the Kartei username. |
| *CA certificate (PEM, optional)* | `-----BEGIN CERTIFICATE-----…` | The root CA of your domain controllers' certificates, if they come from an internal CA. If set, the server certificate is always verified against it. |

> Warning: Do not use unencrypted `ldap://` without *StartTLS*: the users' passwords would cross the network in plain text.
{: .warn}

### Groups and roles

Under *Groups → roles*, enter the distinguished name of one AD group for each role (*Admin*, *Maintainer*, *Read only*). Fields left empty are not used.

- **Nested groups count:** a user who is a member of a group inside the role group gets the role as well.
- **The highest role wins** if a user is in several groups.
- **No group, no access:** AD users who are in none of the groups cannot sign in.
- The role is re-derived at every sign-in, so changes in AD take effect at the next sign-in at the latest.

### Save & test

1. Enter the settings.
2. Optionally enter a username under *Test user (optional)*.
3. Click *Save & test*.

The result shows whether the connection and the bind of the service account worked, and for the test user the DN and the role Kartei would assign (*none – sign-in would be refused* if no group matches). Nested groups are resolved, exactly as at sign-in.

### Import users in advance

*Save & import users now* creates all members of the three groups (including nested groups) as LDAP users, so they can be selected as *Internal contact* before their first sign-in. The import runs automatically once a day.

- Disabled AD accounts are skipped (and thereby deactivated in Kartei).
- Users who have left all groups are deactivated, not deleted.
- Local users are never touched; an AD account with the same name as a local user is counted as *local skipped*.
- If no members are found at all (e.g. wrong search base), nothing is changed and an error is shown, so a typo cannot deactivate everybody.

The box below the button shows the last run: *new · updated · deactivated · local skipped*, or the error.

## Fields

Apart from the core fields (first and last name, company name, company link and image), all contact fields are defined by admins under *Settings → Fields*.

![Fields tab](../img/en/settings-fields.png)

### Field list

- The chips *All*, *People*, *Companies* filter the list; *Show archived* also shows archived fields.
- The list is grouped by **section**, in the order of the sections; fields without a section are listed under *Other* at the end.
- Drag a row by its handle to change the order, also into another section (drop it on a field or on a section heading). The order applies to the forms and the detail view.
- Click a row to open the editor on the right; *New field* opens an empty editor.
- The small grey text under the label is the field's **key**. It is generated from the English label when the field is created and does not change afterwards. The API, exports and the import refer to fields by this key.

### Sections

Sections group the fields in the contact form and the detail view. **Sections** in the toolbar opens the section manager on the right:

![Section manager](../img/en/settings-sections.png)

- Rename a section by editing its German or English label; the change is saved when you leave the box.
- The arrows change the order of the sections. The form and the detail view show the sections in this order, and the fields within a section in field order.
- Add a section with the boxes at the bottom (one language is enough; the other one gets the same text).
- The small grey text is the section's **key**. Like a field key it is generated when the section is created and does not change; field files refer to sections by it. The section with the key `person` (or `company`) is shown in the header block of the person (or company) form, next to the name.
- A section that active fields still use can't simply be deleted: choose a section (or *Other*) to move its fields to, then *Move and delete*. Archived fields of a deleted section move to *Other*.

Every change to a section is recorded in the audit log.

### Field settings

| Setting | Meaning |
|---|---|
| *Label* (DE/EN) | Both are required. |
| *Help text* (DE/EN) | Shown below the input and as a tooltip in the detail view. |
| *Type* | See below. |
| *Applies to* | *People*, *Companies* or *People & companies*. |
| *Minimum*, *Maximum*, *Decimal places* | For *Integer* and *Decimal*. |
| *Options* | For *Single select* and *Multi select*: *Value* (stored) and the labels DE/EN; order with the arrows. |
| *Editors may add new options while typing* | Select fields: editors can add new options directly in the form (e.g. keywords). |
| *Offer in the list's quick filter* | Choice and user fields: the field appears in the field filter (funnel) above the contact list. Switch it on only for fields people really filter by (e.g. keywords, internal contacts); every field is still available in the advanced filter. |
| *Allow free text (a name without its own contact)* | *Contact* fields: also accepts a typed name. |
| *Format (regular expression)* | For *Text*, *Long text*, *Phone*, *Email* and *URL*: the whole value must match. Buttons insert common patterns (*ZIP (DE)*, IBAN, …); a test value shows *matches* or *no match*. Checked in the form, on the server and by the import. Empty values are not checked. |
| *Section* | Groups fields in the form and detail view. Choose an existing section, or type a new name and pick *Create section …*; empty = *Other*. |
| *Visible to* | *Everyone*, *Maintainer & Admin* or *Admin only*. |
| *Editable by* | *Maintainer & Admin* or *Admin only*. |
| *Required* | The field must be filled when saving. |
| *Searchable* | The value is found by the search. |
| *vCard mapping* | Where the value goes in vCards (CardDAV, Outlook sync, vCard download). Mappings with a custom label (e.g. *Phone with custom label*) also need *vCard type / label*, e.g. `Zentrale`. |
| *Import column names* | Further column headers that the CSV import maps to this field, comma-separated (e.g. `Tel.`, `Business phone`). |
| *Copy from company field* | Persons only: when a company is assigned, the form offers to copy this value from the selected company field (e.g. address, website). Also used when company changes are carried over to the employees. |

![Field editor](../img/en/settings-field-editor.png)

> Warning: Only fields visible to *Everyone* reach the phones (CardDAV, Outlook sync) and the API. Exports and the AD sync are configured separately and can contain any field.
{: .warn}

### Field types

| Type | Use |
|---|---|
| *Text*, *Long text* | Free text; *Long text* is multi-line. |
| *Integer*, *Decimal* | Numbers with optional limits. |
| *Single select*, *Multi select* | Fixed options, searchable list in the form. |
| *Phone*, *Email*, *URL* | Validated, clickable; phone numbers are normalized (see [General](#general-settings)). |
| *Date*, *Yes/No* | Real date and checkbox values (also typed correctly in Excel). |
| *User* | One Kartei user, e.g. the internal person responsible. The **first** *User* field of a contact determines who reviews it. Administrators and inactive users are not offered; a value set earlier stays. |
| *Multiple users* | Several Kartei users, e.g. internal contacts. Here too, administrators and inactive users are not offered. |
| *Contact (person of the company)* | Links a person of the same company, e.g. the managing director. |

Exports, vCards and the AD sync show the names of users and linked persons, not their IDs.

### Changing the type

As long as no contact has a value in the field, any type change is possible. With data, only these changes are allowed:

- *Text* ↔ *Long text*
- *Phone*, *Email*, *URL* → *Text*
- *Integer* → *Decimal*
- *Single select* → *Multi select* and *User* → *Multiple users* (existing values are converted to lists)
- *Text* → *Contact* (free text is switched on so the old values stay valid)

Other changes are refused with *Type change not possible because data exists*.

### Archive and delete

- *Archive* hides the field everywhere (forms, contact view, search, filters, CardDAV, Outlook, imports) after a confirmation. The data is kept, and *Restore* brings it back.
- *Delete* is only offered for archived fields and asks first (*Delete the field … permanently?*). It only works if no contact, including those in the recycle bin, has a value in it; otherwise *Field contains data – archive it instead*. Deleting cannot be undone.

### Export and import field definitions

Field definitions can be saved and loaded as a JSON file, for example to copy them from a test to a production installation, to keep them under version control, or to start from an example.

- **Export fields** downloads all field definitions (archived ones too) as `kartei-fields.json`.
- **Import fields** uploads such a file and first shows a **preview** on the right. New or changed sections are listed first; each field of the file is listed as *new*, *changed* (with the changed settings), *unchanged* or *invalid* (with the reason). *Apply* creates and changes the fields; *Cancel* discards the import.

Rules:

- Fields are matched by their **key**. Fields that exist in Kartei but not in the file stay unchanged; nothing is deleted.
- Sections are matched by their key as well: new ones are added in the order of the file, existing ones get the labels from the file and keep their position. A field that refers to a section that is neither in the file nor in Kartei is *invalid*.
- Files of the older format version 1 (section labels per field) can still be imported: each section is found by its German or English label, or created.
- Type changes follow the same rules as in the editor: an incompatible change of a field that contains data is reported as *invalid* and not applied.
- The order of new fields follows the file; *Copy from company field* refers to fields by key and may point to a field in the same file.
- Every created or changed field gets an entry in the audit log.

### Example files

The `examples` folder of the Kartei repository contains starting points (see `examples/README.md` there):

| File | Content |
|---|---|
| `fields-default.json` | The few fields a fresh installation starts with: job title, email, phone, mobile, main phone, main email, website. |
| `fields-example.json` | A fuller, neutral field set: person details (salutation, academic title, department, private contact data, assistant, manager, …), company details (short name, main phone/email/fax, managing director), business address copied from the company, home address, *Internal contact* (*User*, required, the reviewer), *Internal contacts*, keywords, customer and contract number, notes. All with German and English labels, vCard mapping and common German and English CSV column names as import column names. |
| `ad-mapping.json` | An AD attribute mapping for these fields (see [Active Directory](#active-directory)). |

On the first start, Kartei loads `examples/fields-default.json`. The environment variable `INITIAL_FIELDS` points to another file (path inside the container); an empty value starts without fields. This only happens once, on a fresh database.

To use the fuller set, choose *Import fields* → `fields-example.json`, check the preview and *Apply*. Afterwards archive or adapt what you do not need.

## Import

*Settings → Import* imports persons and companies from a CSV file, for example when you migrate from another system or take over a list. You decide per column where its values go.

![Import tab](../img/en/settings-import.png)

### Run the import

1. If the file contains users (e.g. an internal contact), create or import the users first (see [Import users in advance](#import-users-in-advance)) so they can be matched.
2. Make sure the fields you need exist (see [Fields](#fields)). Import column names on the fields help the automatic suggestion.
3. *Choose CSV file*. Kartei reads the header and shows the **column mapping**.
4. Check the mapping and the kind rules (see below).
5. Click *Dry run*. Nothing is saved; you see the number of rows, new and updated persons and companies, and the warnings.
6. Adjust the mapping or the source data if needed and repeat the dry run.
7. Click *Run import* (only possible after a dry run).

**File format:** UTF-8 (with or without BOM) or Windows-1252; comma, semicolon or tab as delimiter (detected automatically); the first row contains the column headers.

### Column mapping

For every column, the table shows the header, examples from the first rows and two targets: one *for people* and one *for companies*. The same column can mean different things, e.g. a "Name" column that is the last name of a person and the name of a company. Targets:

| Target | People | Companies |
|---|---|---|
| *Legacy ID* | ✓ | ✓ |
| *First name*, *Last name* | ✓ | – |
| *Company (linked by name)* | ✓ | – |
| *Name* | – | ✓ |
| a field (only fields that apply to the kind) | ✓ | ✓ |
| *Create as new text field* | ✓ | ✓ |
| *(ignore)* | ✓ | ✓ |

Kartei suggests a target for each column: common names of the core data (e.g. `Vorname`/`First name`, `Firma`/`Company`, `ID`), then the field whose key, label or **import column names** match the header (case, accents and punctuation are ignored). Check the suggestion; empty means the column is ignored.

*Create as new text field* creates a text field named after the column header when the import runs (with the header as import column name). Change its type and settings afterwards under *Fields* if needed.

*Export mapping* downloads the mapping (including the kind rules) as JSON; *Import mapping* loads it again for the next file with the same columns.

### Person or company?

Kartei decides the kind of each row in this order:

1. **Column with the kind:** if set, values like `Person`/`Kontakt`/`Contact` mean person and `Firma`/`Company`/`Organisation` mean company. Other values produce a warning and fall back to the next rules. A column named `Type`, `Art` or `Kind` is preselected.
2. **ID prefixes:** *ID starts with … → company* and *ID starts with … → person* look at the column mapped to *Legacy ID*, e.g. `F-` and `P-`.
3. **Otherwise:** rows with a last name are persons; rows without a last name but with a company name are companies.

### What the import does

- **Matching:** if a column is mapped to *Legacy ID*, each row is matched with the contact of the same kind and legacy ID, and importing the file again **updates** those contacts. Without a legacy ID, every import creates new contacts.
- **Company link:** persons are linked to the company with the name in the column mapped to *Company (linked by name)*. Unknown companies are created. Companies are imported before persons.
- **User fields** (*User*, *Multiple users*) are matched against active Kartei users by username, full name or unique initials; administrators are not assigned. Unknown names and administrators produce a warning and are left out.
- **Select fields:** unknown values are added as new options. Several values in one cell are separated by comma or semicolon.
- **Invalid values** (e.g. a wrong email address, a value that does not match the field's format) are skipped with a warning; the rest of the row is imported. Empty cells do not overwrite field values (but an empty first name, last name or company name column does clear that name).
- Rows without a name are skipped. Rows whose legacy ID belongs to a contact that was merged into another one are skipped too.
- Every created or changed contact gets an *Imported* entry in its history.

> Warning: Importing the same file again overwrites values that were changed in Kartei in the meantime with the values from the file. Do not re-import old data once your team works in Kartei.
{: .warn}

### Command line

The same import runs on the command line, for example for large files. The file must be readable inside the container (e.g. below `/export`). Without `--commit` it is a dry run; without `--mapping` the suggested mapping is used.

```sh
docker compose exec web python manage.py import_csv /export/contacts.csv --mapping /export/mapping.json
docker compose exec web python manage.py import_csv /export/contacts.csv --mapping /export/mapping.json --commit
```

## Exports

*Settings → Exports* writes CSV and Excel files to the export directory, for example for scripts and other applications that import contacts, or for colleagues who open the list in a spreadsheet program. Each export is a profile with its own columns and format.

![Exports tab](../img/en/settings-exports.png)

The list shows each profile with *Format*, *Target file*, *Schedule* and *Last run* (status, time and message). *Run now* writes the file immediately.

### Create or edit an export

1. *New CSV export* or *New Excel export*, or click an existing profile.
2. **General:**
   - *Name*.
   - *Target file*: absolute path below `/export` with the matching extension (`.csv` or `.xlsx`), e.g. `/export/kontakte_export.csv`. `{date}` is replaced with the current date (`2026-10-24`). Missing folders below `/export` are created automatically.
   - *Contains*: *People & companies*, *People* or *Companies*.
   - *Schedule*: *automatic* (every export interval) or *manual only*.
   - *Max. drop (%)*: the shrink guard (see below).
   - *Only entries with field* and *Values*: optional filter on a select field, e.g. only contacts with a certain keyword.
   - *Export enabled*: automatic exports only run when this is ticked.
3. **Columns:** *Column* adds an empty column, *Add all fields* adds one column per field. For each column, set the *Column header*, the *Value for people* and the *Value for companies*. Sources are core fields, fields and computed values (*UID*, *Legacy ID*, *Legacy ID, else UID*, *Display name*, *Company name (of person)*, *Type (person/company)*, *Created at*, *Changed at*). The `“”` button switches a column to *Fixed text*. Drag the handle to change the order.
4. **Format options:** see below.
5. *Preview* shows the first 20 rows and the total row count.
6. *Save*.

![Export editor](../img/en/settings-export-editor.png)

> Warning: *Delete* in the editor removes the profile after a confirmation; it cannot be undone. The last written file stays in the export directory.
{: .warn}

### CSV options

| Option | Default |
|---|---|
| *Delimiter* | `;` (also `,`, tab, pipe) |
| *Quoting* | *only when needed* (also *always*, *all but numbers*), *Quote char* `"` |
| *Encoding* | *UTF-8 + BOM (Excel)* (also UTF-8, Windows-1252) |
| *Line ending* | CRLF (Windows) |
| *Line breaks in values* | *keep* (in quotes) or *replace with space* — use the latter for scripts that read line by line |
| *Multi-select separator* | `, ` |
| *Date format*, *Decimal separator* | `31.12.2026`, `1234,56` |
| *Yes / No as* | `Ja` / `Nein` |
| *Write header row* | on |

### Excel options

*Sheet name*, *Date format* and *Number format* (Excel format codes), plus *Header row*, *Bold header*, *Autofilter*, *Freeze header row* and *Auto column width*. Dates and numbers are written as real Excel values, not as text.

### The shrink guard

An empty or truncated export can delete contacts in downstream systems. Kartei therefore refuses to write:

- an export with **0 rows** (*Empty export – not written …*),
- an export whose row count dropped by more than *Max. drop (%)* compared with the last successful run, or with the existing file on the first run (*Row count dropped from … to …*).

In both cases the old file stays as it is and the status turns to *error*. If the drop is intended (e.g. after a large cleanup), click *Force* next to *Run now*: the file is written once without the check.

Further behaviour:

- If the content has not changed, the file is not rewritten (*Unchanged – not rewritten*).
- Files are written to a temporary file first and then replaced, so readers never see a half-written file.
- With `{date}` in the path, a new file is created each day; old files are not deleted.

## Active Directory

*Settings → Active Directory* writes all contacts as AD contact objects (`objectClass: contact`) into one OU. Every system that reads contacts from Active Directory can use them, for example the caller ID of a phone system or the address book of a communication client.

![Active Directory tab](../img/en/settings-ad.png)

### How the sync works

- **Marker:** every object Kartei creates carries `kartei:<UID>` in `adminDescription`. Objects without this marker are never changed or deleted.
- **Name:** `cn` and `displayName` are the contact's display name. If the name is taken, Kartei adds ` (2)`, ` (3)` and so on.
- **Changes:** only changed attributes are written; renamed contacts are renamed in AD; contacts that were deleted in Kartei are deleted in AD. Empty values remove the attribute.
- **Guard:** the sync writes nothing if Kartei has no contacts, or if more than *Max. deletions (%)* of the marked objects would be deleted (*100* switches the guard off).
- **Schedule:** every export interval while *AD sync enabled* is ticked, or within seconds after *Sync now*.

### Prepare AD

1. Create a new, empty OU, e.g. `OU=Kartei,OU=Kontakte,DC=example,DC=local`.
2. Choose the writing account: the LDAP service account or a separate account.
3. Delegate on the OU to this account (*Delegate Control* → *Create a custom task to delegate* → *Only the following objects in the folder*: contact objects, *Create selected objects in this folder* and *Delete selected objects in this folder* → permissions *Full Control*).

### Configure

| Setting | Notes |
|---|---|
| *AD sync enabled* | Requires an LDAP server under *LDAP / AD* and a target OU. |
| *Target OU (DN)* | Kartei only looks at objects directly in this OU. |
| *Account for writing (bind DN, optional)*, *Password of the writing account* | Empty = the service account from *LDAP / AD*. Server, StartTLS and CA certificate always come from *LDAP / AD*. |
| *Contains* | *People & companies*, *People* or *Companies*. |
| *Max. deletions (%)* | Default 10. |
| *AD attributes* | One row per AD attribute: *AD attribute*, *Value for people*, *Value for companies*, sources as in the exports, `“”` for fixed text. `cn`, `name`, `displayName`, `objectClass`, `adminDescription` and `distinguishedName` are set by Kartei and cannot be mapped. |

The mapping starts empty. Add a row with *Attribute* for each AD attribute the reading systems need, typically `givenName`, `sn`, `title`, `department`, `company`, `telephoneNumber`, `mobile`, `mail`.

*Export mapping* downloads the mapping as JSON, *Import mapping* loads one (then *Save*). `examples/ad-mapping.json` is a ready mapping for the fields of `examples/fields-example.json`; adapt it if your field keys differ.

### Dry run and first sync

1. Enter OU, account and mapping, then click *Save & dry run*. Nothing is written. You see the counts (*new · changed · renamed · deleted · unchanged*), up to 20 examples per action (*Would create*, *Would rename*, *Would change*, *Would delete*), and a note if the guard would stop the sync.
2. If the result looks right, tick *AD sync enabled* and click *Save*.
3. Click *Sync now*. The box *Last run* shows the result and any objects that failed.
4. Check that the systems reading the contacts find them. If they search a fixed OU, add the target OU there.

> Warning: Use an OU that only Kartei writes to. Kartei never touches objects without its marker: if another tool or script also creates contacts there, they appear next to Kartei's contacts, and Kartei's objects get names with ` (2)` where a name is already taken.
{: .warn}

## CardDAV

Kartei includes a read-only CardDAV server with one address book that contains all persons and companies. All phones use the same account.

> If every phone user has an Exchange Online mailbox, the [Outlook / Exchange sync](#outlook-sync) covers iPhones and Android phones alike, and CardDAV can stay disabled. CardDAV is for phones without a personal mailbox (shared or pool phones, users outside the sync group), for installations without Microsoft 365, and when one central read-only address book is preferred over a copy in every mailbox. It also keeps iPhone-specific details such as custom phone labels, phonetic names and relations, which Outlook contacts only hold as notes.
{: .tip}

![CardDAV tab](../img/en/settings-carddav.png)

### Set up

1. *Settings → CardDAV*: tick *Built-in CardDAV server enabled* and click *Save*.
2. Optionally change the *Username* (default `carddav`).
3. Click *Generate password*. The password is shown **only now**; copy it to your password safe.
4. Check the server address under *Phone setup*. It is built from the *Public URL* (*Settings → General*): `https://kartei.example.de/carddav/`.

![CardDAV password shown once](../img/en/settings-carddav-password.png)

*Generate new password* replaces the password at once; every phone then needs the new password.

### On the iPhone

1. *Settings → Contacts → Accounts → Add Account → Other → Add CardDAV Account*.
2. *Server*: `kartei.example.de` (the iPhone finds `/carddav/` by itself) or the full address.
3. *User Name* and *Password* from Kartei, then *Next*.

The contacts appear as a separate account in the Contacts app and are updated automatically. Changes on the phone are not possible.

### What is synced

- Only fields visible to *Everyone* that have a *vCard mapping*.
- Photos of persons and logos of companies.
- Names of users and linked persons (e.g. *Internal contact*) as text.
- Deleted contacts disappear from the phones.
- Phones that support it (iPhone, DAVx⁵ and most other clients) only fetch what changed since their last sync (`sync-collection`), which keeps syncs fast with many contacts. After a change to the vCard mapping, the *Public URL* or contacts deleted permanently from the recycle bin, each phone does one full sync on its own.

If CardDAV is disabled, the address returns "not found" and the phones keep their last state until the account is removed. Android has no built-in CardDAV; use the [Outlook / Exchange sync](#outlook-sync) or a CardDAV app.

### Relay in the DMZ (optional) {#relay-dmz}

If phones must not reach the internal network, run a small **CardDAV relay** in the DMZ. Kartei pushes the finished vCards there; the phones read them from the relay.

| | Built-in server | Relay in the DMZ |
|---|---|---|
| Phones connect to | Kartei (`https://kartei.example.de/carddav/`) | the relay (`https://carddav.example.de/carddav/`) |
| Connection inside ↔ DMZ | none | Kartei (`exporter`) → relay, HTTPS only; the relay never connects anywhere |
| Data on the DMZ host | none | the rendered vCards (iOS and Android variant), the CardDAV username and the password **hash**: nothing else, no database or LDAP access. Deleted cards are kept as empty markers for 30 days so phones learn about the deletion; phones that haven't synced for longer do one full sync. |

The relay is the same image started with other settings (`docker build --target relay`, no frontend). It stores the cards in its own SQLite file, serves the same read-only CardDAV as Kartei (address `/carddav/`, discovery `/.well-known/carddav`, rate limit for wrong passwords) and has no other pages: no admin, no sign-in, no listing.

**Firewall:** allow only *Kartei host → relay host, TCP 443* (or the port of the relay's reverse proxy), plus *phones/internet → relay, 443*. Nothing from the DMZ to the inside.

**Set up**

1. On the DMZ host, copy the repository (or just `Dockerfile`, `backend/`, `compose.relay.yaml`), then `cp .env.relay.example .env.relay` and set `SECRET_KEY` and `ALLOWED_HOSTS` (the host name the phones use).
2. In Kartei, *Settings → CardDAV → External relay (DMZ)*: enter the *Relay URL* (`https://carddav.example.de`, HTTPS only) and click *Generate token*. Kartei keeps the push token encrypted and shows only its SHA-256 value. Copy that value into `.env.relay` as `RELAY_PUSH_TOKEN_SHA256`. The DMZ host never sees the token itself.
3. Start the relay: `docker compose -f compose.relay.yaml up -d --build`. It listens on port 8080 (`RELAY_PORT`); put a TLS reverse proxy in front of it, configured like the one for Kartei (pass `Authorization`, `PROPFIND`/`REPORT`, `X-Forwarded-For`, `client_max_body_size 20m`). The SQLite file lives in the volume `relaydata`.
4. *TLS*: with *Verify TLS certificate* on (default), Kartei checks the relay's certificate against the system CAs or, if given, the *CA certificate* (PEM) of your internal CA. Switch verification off only for tests.
5. Click *Save & test*: Kartei reaches the relay and checks the token. Then tick *Push to the relay*, set *Max. deletions (%)* and *Save*.
6. Untick *Built-in CardDAV server enabled*. Kartei's own `/carddav/` then answers "not found", so phones can't use the inside server by mistake. (Leaving both on is possible, e.g. during a migration.)
7. Set up the phones with the relay address. Username and password are the ones from this tab; *Generate new password* reaches the relay with the next push.

**How the push works:** at every export interval (and within about 10 seconds after *Sync now*), the `exporter` asks the relay which cards it has (uid and version), sends the new and changed cards in requests of about 2 MB and the uids to delete, and always sends the current username and password hash. Every run compares against the relay's real state, so cards lost or added on the relay are corrected on the next run. *Last run* shows the result.

**Guards:** nothing is pushed if Kartei has no contacts, or if more than *Max. deletions (%)* of the cards on the relay would be deleted in one run (100 = off). The run is then reported as an error and the relay keeps its state. If the deletions are intended, raise the limit for one run.

**Troubleshooting**

| Status / symptom | Cause |
|---|---|
| *The relay rejected the push token* | `RELAY_PUSH_TOKEN_SHA256` on the relay host doesn't match the value in Kartei (restart the relay after changing `.env.relay`). |
| `certificate verify failed` | The relay's certificate isn't trusted: add the CA certificate, or check the host name in the URL. |
| `timed out`, `Connection refused`, `Name or service not known` | Firewall rule inside → DMZ, DNS name or reverse proxy of the relay. |
| `HTTP 400` / `HTTP 413` | The reverse proxy in front of the relay limits the request size (set `client_max_body_size 20m`) or changes the request. |
| Phones get 401 | Wrong password, or the relay hasn't received the login yet (see *Last run*). 20 wrong passwords from one address lock it out for 15 minutes. |
| Relay answers 400 for everything | The host name isn't in `ALLOWED_HOSTS` in `.env.relay`. |

The relay logs every request to the container log (`docker compose -f compose.relay.yaml logs`). To start over, stop it and remove the volume `relaydata`; the next push fills it again.

## Outlook / Exchange sync {#outlook-sync}

Kartei writes all contacts through Microsoft Graph into a contact folder (default `Kartei`) in the mailbox of every member of an Entra group. The Outlook app for iOS and Android stores this folder in the phone's address book, which gives caller ID on iPhones and Android phones without CardDAV.

Requirements: Exchange Online mailboxes (Microsoft 365) and an app registration in Entra ID.

![Outlook / Exchange tab](../img/en/settings-outlook.png)

### Register the app in Entra ID

1. Entra admin center → *App registrations* → *New registration*, e.g. name "Kartei Contacts", single tenant, no redirect URI.
2. *API permissions* → *Add a permission* → *Microsoft Graph* → *Application permissions*: `Contacts.ReadWrite` and `GroupMember.Read.All`. Then *Grant admin consent*.
3. *Certificates & secrets* → *New client secret*. Copy the value and note the expiry date.
4. Note the *Directory (tenant) ID* and the *Application (client) ID* on the overview page.
5. Create (or choose) the group of users whose phones should get the contacts and note its object ID. Nested groups are resolved.

### Limit access to the group

`Contacts.ReadWrite` as an application permission allows access to **all** mailboxes of the tenant. Limit it in Exchange Online to the group's mailboxes, either with RBAC for Applications or with an application access policy (requires a mail-enabled security group):

```powershell
Connect-ExchangeOnline
New-ApplicationAccessPolicy -AppId <client-id> -PolicyScopeGroupId kartei-sync@example.de `
  -AccessRight RestrictAccess -Description "Kartei contact sync"
Test-ApplicationAccessPolicy -AppId <client-id> -Identity someone@example.de
```

### Configure Kartei

1. *Settings → Outlook / Exchange*: enter *Tenant ID*, *Application (client) ID*, *Client secret* and *Group ID (object ID of the Entra group)*. The secret is stored encrypted; the field stays empty after saving.
2. Optionally change the *Contact folder name*.
3. *Save & test*: Kartei signs in and lists the group members with a mailbox (*Sign-in successful – n mailboxes in the group*, plus up to five addresses). Nothing is written.
4. Tick *Outlook sync enabled* and click *Save* (only possible when all four values are filled in).
5. *Sync now* starts the first run. *Last run* shows mailboxes, new, changed and removed contacts, photos and duration, plus failures.

On the phone (iPhone or Android), users install the Outlook app, sign in with their work account and enable *Save contacts* (*Settings* → account → *Save contacts*). With Intune you can enforce this setting.

> The account built into iOS (*Settings → Mail → Accounts → Exchange*) usually syncs only the default *Contacts* folder, not Kartei's own folder. Use the Outlook app and check with one test phone before rolling out.
{: .tip}

### Behaviour

- Only fields visible to *Everyone* are synced, according to their vCard mapping. Values Outlook has no field for (fax, assistant phone, custom relations, more than three email addresses) go into the notes.
- Photos are synced too.
- The folder belongs to Kartei: contacts that users add there themselves are removed at the next run.
- Members who leave the group lose the folder at the next run.
- Throttling by Microsoft is handled with automatic retries; a large first run can take a while.

> Warning: If you rename the *Contact folder name*, Kartei creates a new folder and leaves the old one in the mailboxes. Choose the name before the first sync.
{: .warn}

## Reviews

The responsible user of each contact (the first field of type *User*, e.g. *Internal contact* in the example field set) is asked from time to time to check that the contact is still correct. How reviewers answer and how maintainers decide on proposals is described in the [user manual](user.html).

![Review tab in rolling mode](../img/en/settings-review-rolling.png)

### Review mode

| Mode | Reviews start |
|---|---|
| *Manual only* | only through the buttons below, or for a single contact with *Request review* (admins) |
| *Rolling (per contact)* | automatically for each contact whose last review (or, if never reviewed, its creation) is older than *Due … months after the last review* |
| *Yearly on a set date* | for all contacts once a year on the *Date (every year)* |

Each contact has at most one open review. Contacts without an active responsible user cannot be reviewed.

> Tip: Imported contacts count as created on the day of the import, so in *Rolling* mode they become due only after the interval. Use *Review all contacts* if you want a first round right away.
{: .tip}

### Start and monitor

- *Review due contacts now* (only in rolling mode) and *Review all contacts* save the settings and start the reviews at once. The message shows how many were started, already open, or have no internal contact.
- **Status** shows the open reviews, how many have not been emailed yet, how many were reminded, the due contacts (rolling) or the next date (yearly), and up to 20 contacts without an internal contact with links. Assign a responsible user to them (e.g. with bulk edit).
- *Remind after … days (0 = never)*: reviewers with open reviews get a reminder every N days until they are done.

### Emails

Reviewers get one digest email per export interval with links to their contacts, in their own language. Requirements:

- email sending is set up (*Settings → Email*),
- the reviewer has an email address,
- the *Public URL* is set (*Settings → General*), otherwise the links in the emails are incomplete.

Without an email address or a configured email transport, the reviews are still visible in the app (list *To review*). The texts of all emails can be changed under [Email](#email).

### Proposal emails

Under *Proposals*, *Email maintainers about new and edited proposals* sends maintainers a digest of new and edited proposals. *Recipients*: comma-separated addresses; empty = all active maintainers and admins with an email address (nobody gets mail about their own proposals).

## Email

*Settings → Email* sets how Kartei sends its emails (new reviews, reminders, proposals) and what they say. As long as no transport is complete, Kartei sends no emails.

![Email tab](../img/en/settings-mail.png)

### Sending

Under the hint, choose one of two transports:

**SMTP server**

| Setting | Notes |
|---|---|
| *SMTP server*, *Port* | e.g. `smtp.example.de`, 587 |
| *Encryption* | *STARTTLS* (port 587), *SSL/TLS* (port 465) or *none* |
| *Username (optional)*, *Password* | only if the server requires authentication; the password is stored encrypted |
| *Sender* | e.g. `Kartei <kartei@example.de>`; required |

**Microsoft 365 (Exchange Online, OAuth2)**

Kartei sends through Microsoft Graph (`sendMail`) with OAuth2 – no password, no basic authentication. It uses the app registration entered on the [Outlook / Exchange](#outlook-sync) tab (tenant ID, client ID, client secret); the Outlook sync itself does not have to be enabled.

1. In the app registration, add the Microsoft Graph application permission `Mail.Send` and grant admin consent.
2. Limit the permission to the sending mailbox, e.g. with an application access policy for a mail-enabled security group that contains only this mailbox (as shown for the Outlook sync), or with RBAC for Applications. Without a restriction, the app may send as any mailbox of the tenant.
3. Enter the *Sending mailbox*, e.g. `kartei@example.de`. Emails are sent from this mailbox and are not stored in its sent items.

### Test

Enter an address under *Recipient for the test email* and click *Save & send test*. Errors are shown as the SMTP server or Microsoft 365 returns them.

### Email texts

Under *Email texts* you can adapt subject and text of each email, per language:

1. Choose the *Email* (*New reviews*, *Reminder*, *New proposals (to maintainers)*) and the *Language*.
2. Edit *Subject* and *Text*. Parts you leave empty use the default text.
3. Click *Save*.

Placeholders:

| Placeholder | Is replaced with |
|---|---|
| `{name}` | the recipient's first name (or username); for fixed proposal recipients a general greeting |
| `{n}` | the number of contacts or proposals |
| `{items}` | the list of contacts or proposals with their links |
| `{url}` | the link to the list in Kartei (*To review* or *Proposals*) |

Each recipient gets the text in their own language (the default language if they have not chosen one). Texts with an unknown placeholder or a single curly brace are rejected when saving (*Unknown placeholder or a single curly brace*). If a stored text cannot be used anyway, Kartei sends the default text. *Default text* discards your changes for the selected email and language.

> Tip: The links in the emails are built from the *Public URL* under *General*. Set it before the first emails go out.
{: .tip}

## General settings

![General tab](../img/en/settings-general.png)

| Setting | Meaning |
|---|---|
| *Default language* | Language for users who have not chosen one in *My account*, and for emails to fixed recipients. The sign-in page follows the browser language. |
| *Public URL* | e.g. `https://kartei.example.de`. Used for links in emails, in vCards (`SOURCE`) and for the CardDAV address. |
| *Empty recycle bin automatically after (days)* | Contacts in the recycle bin are deleted permanently after this many days. *0* = never (default). |
| *Anonymise the history when deleting permanently* | On (default): a contact deleted permanently also loses its name and values in its history and the audit log; see [Data protection](#data-protection). |
| *Export interval (minutes)* | Interval of all background jobs (see [Background jobs](#background-jobs)). Default 15, minimum 1. |

### Phone numbers

With *Normalize phone numbers on save*, national numbers are stored in international form with the *Default country code*:

- `0511 1000-12` → `+49 511 1000-12`; `0049 …` and `+49 (0)…` are converted as well.
- The grouping the user typed is kept; brackets and slashes become spaces.
- Internal extensions without a leading 0 or + stay as they are.

Phones and caller-ID systems can then match incoming calls reliably.

To convert numbers saved before (e.g. after the import):

1. Click *Check existing numbers*. The settings are saved, and Kartei shows how many contacts would change, with examples.
2. Click *Normalize n contacts now*. Each changed contact gets a history entry.

![Result of the phone-number check](../img/en/settings-general-phones.png)

## Data quality and duplicates

Admins and maintainers find *Data quality* and *Duplicates* in the user menu and on the dashboard:

- **Data quality** lists contacts without a responsible user, with invalid values (e.g. after a new format rule), persons without email and phone, persons without company, companies without persons, and contacts never reviewed or overdue.
- **Duplicates** lists pairs with the same email, phone number or name, which can be merged or dismissed.

Both are described in the [user manual](user.html). After changing a field's format rule or required flag, check *Invalid values*: existing data is not changed automatically.

Contacts deleted by maintainers go to the recycle bin (user menu → *Recycle bin*). When a company is deleted, the maintainer can choose to move its persons along. Only admins can *Delete permanently*, after a confirmation that warns it cannot be undone; otherwise the retention under *General* applies.

## API

Other systems can read the contacts through a REST API with a token and, with a write token, also create, change and delete them. Tokens see the same fields as a Read only user (fields visible to *Everyone*). The complete reference for developers (endpoints, delta sync, value types, errors, examples, OpenAPI file) is `docs/API.md` in the Kartei repository.

![API tab](../img/en/settings-api.png)

### Manage tokens

1. *Settings → API*: enter a *Name* (e.g. "Phone system"), choose the *Permission* and click *Create token*:
   - *Read only* (default): the system can only read contacts.
   - *Read and write*: the system can also create, change and delete contacts.
2. The token (`kt_…`) is shown **only now**, together with its permission. Copy it into the other system.
3. The list shows each token's *Permission*, when it was *Created* and *Last used*.
4. The trash icon (*Revoke*) asks first, then deletes the token. Systems using it lose access at once.

The permission can't be changed later: create a new token with the other permission and revoke the old one.

![New API token, shown once](../img/en/settings-api-token.png)

Kartei stores only a hash of the token; a lost token cannot be shown again. Create a new one and revoke the old one.

### Endpoints

```sh
curl -H "Authorization: Bearer kt_…" https://kartei.example.de/api/v1/contacts
curl -H "Authorization: Bearer kt_…" "https://kartei.example.de/api/v1/contacts?updated_since=2026-10-24T08:00:00%2B00:00"
curl -H "Authorization: Bearer kt_…" https://kartei.example.de/api/v1/contacts/<uid>
```

| Request | Answer |
|---|---|
| `GET /api/v1/contacts` | `{"cursor", "full": true, "contacts": [...]}` with all contacts |
| `GET /api/v1/contacts?updated_since=<cursor>` | only contacts changed since then, plus `deleted` (UIDs to remove). If the cursor is older than the recycle-bin retention, the full list comes back with `"full": true`. |
| `GET /api/v1/contacts/<uid>` | one contact, or 404 |

Each contact has `uid`, `kind` (`person`/`company`), `legacy_id`, `first_name`, `last_name`, `name`, `display_name`, `company` (UID) and `company_name`, `data` (field key → value; user fields contain usernames, contact fields UIDs) and `updated_at`.

**Delta sync:** store the `cursor` of each response and pass it as `updated_since` next time. Encode `+` in the time zone as `%2B`.

With a *Read only* token only `GET` is allowed; anything else returns 403. A wrong token returns 401; after 20 failures within 15 minutes from one address, the API answers 429 for 15 minutes.

### Write tokens

A *Read and write* token works like a **Maintainer who only sees the fields visible to *Everyone***:

| Request | Effect |
|---|---|
| `POST /api/v1/contacts` | creates a person or company (`kind`, names, `company`, `data`) |
| `PATCH /api/v1/contacts/<uid>` | changes only the keys sent; `null` clears a field. With `version`, a contact changed in the meantime returns 409 instead of being overwritten. |
| `DELETE /api/v1/contacts/<uid>` | moves the contact to the recycle bin; `?with_persons=1` also moves a company's persons |

- Fields that only admins may edit return the error `forbidden`; fields not visible to *Everyone* return `unknown_field`. Values in those fields stay untouched.
- Invalid values return 400 with an error per field, like the form in the web interface.
- Every change appears in the contact's history and in the audit log with the user **`api:<token name>`**. Give tokens clear names (e.g. "CRM sync").
- Phone numbers are normalized, new options of open select fields are added, and open reviews follow a changed responsible user, just like in the web interface.
- Deleted contacts can be restored from the recycle bin as usual.

Only give a write token to systems that really need to change data, and keep it as safe as a password.

### Webhooks

Instead of asking Kartei every few minutes, other systems can be notified right away: a **webhook** sends each change to a contact as an HTTPS request to the system's address, signed with a secret.

![Webhooks on the API tab](../img/en/settings-webhooks.png)

1. Under *Webhooks* enter a *Name* and the *Address (URL)* the receiving system gives you.
2. Optionally select the *Events* (created, updated, deleted, restored); none selected means all.
3. *Add webhook* shows the **secret** once. Enter it in the receiving system; it uses it to check that requests really come from Kartei.
4. *Send test event* (paper plane) sends a test request right away and shows the result.

- The content is the contact with the fields visible to *Everyone*, as in the REST API. The developer documentation (`docs/API.md`, *Webhooks*) describes the request and how to verify the signature.
- Kartei delivers within about 10 seconds. Failed deliveries are retried for about a day; the table shows the last result and how many deliveries are waiting or were given up.
- *Active* switches a webhook off without losing it; the key symbol creates a new secret (the old one stops working at once).
- Creating, changing and deleting webhooks is recorded in the audit log.

## Audit log

*Settings → Audit log* lists every change with time, user, action, object and the changed values (old value struck through → new value).

![Audit log tab](../img/en/settings-audit.png)

- **Filter** by area: *All areas*, *Contact*, *Field*, *User*, *Settings*, *Export*, *API token*.
- **Search** in object names and usernames (*Search object or user …*).
- 100 entries are loaded at a time; *Load older* loads more.

What is logged:

| Area | Entries |
|---|---|
| Contact | create, change, delete, restore, permanent delete (also by the automatic purge), import, bulk changes, merges, proposals and decisions, reviews, phone-number normalization |
| Field | create, change, archive, delete, reorder, field import, fields created by the CSV import; new options added while typing |
| User | create, change (role, active, name), password changes (masked), delete, changes by the AD user import |
| Settings | every change (passwords and secrets masked as `***`), new CardDAV password, *Sync now*, review starts, phone-number conversion |
| Export | changes to export profiles, and every list export by a user (with row count) |
| API token | create (with permission), revoke |

Not logged: sign-ins, and the individual runs of exports and syncs (their result is shown in the respective tab and in the `exporter` log). Automatic actions appear as user *system*, changes through a write token as `api:<token name>`.

Each contact also has its own history tab, see the [user manual](user.html).

## Data protection {#data-protection}

Kartei holds personal data. Two functions help with the rights of the people in it (GDPR):

**Access report (Art. 15).** On a contact, the document symbol (*Access report*, admins only) opens a report of everything Kartei holds about the contact, including fields only admins see, the full history, proposals and reviews, and **where the data goes**: phones (CardDAV, relay), Outlook / Exchange, Active Directory, the exports that contain the contact, API tokens and webhooks, each with the fields or columns concerned. *Print / PDF* prints it or saves it as PDF for the person. Creating a report is recorded in the contact's history.

![Access report](../img/en/report.png)

**Erasure (Art. 17).** Deleting a contact first moves it to the recycle bin. *Delete permanently* (or the automatic emptying under *General*) removes it for good. With *Anonymise the history when deleting permanently* (on by default), its entries in the history and the audit log then keep only who did what and when: the name and all values are removed (shown as *(anonymised)*). Turn it off only if you need the values for a documented reason.

> Data that has already been passed on (export files, other systems via the API or webhooks) is not erased by Kartei: the next export run no longer contains the contact, phones and Outlook remove it at the next sync; other systems must delete it themselves (the webhook event `contact.deleted` tells them).
{: .tip}

## Security

- **`SECRET_KEY`:** the LDAP password, the AD writing password, the Outlook client secret and the SMTP password are stored encrypted with a key derived from `SECRET_KEY`. If the key changes, these values are lost (they read as empty) and must be entered again, and all users are signed out. Keep `SECRET_KEY` stable and in your backup.
- **Shown once:** the CardDAV password and API tokens are stored only as hashes. They are shown once when created; afterwards they can only be replaced.
- **Rate limits:** after 10 failed sign-ins for one username, after 20 failed CardDAV logins and after 20 failed API requests, the client address is blocked for 15 minutes. Behind the reverse proxy, the address is the last entry of `X-Forwarded-For`; make sure the proxy appends it and that port 8000 is not reachable directly (or set `PROXY_HEADERS=0` without a proxy).
- **HTTPS only:** cookies are marked *Secure*. Keep `SECURE_COOKIES=1` in production.
- **Least privilege:** the LDAP service account only needs read access. Give the AD writing account rights on the target OU only, limit the Outlook app to the group's mailboxes, and limit `Mail.Send` to the sending mailbox.
- **Field visibility:** CardDAV, Outlook sync and the API only see fields visible to *Everyone*. Exports and the AD sync contain whatever you configure; protect the export share accordingly.
- **Emergency access:** `/django-admin/` is a hidden fallback for superusers. Use it only in emergencies; changes made there bypass Kartei's checks and are not written to the audit log.

## Troubleshooting

| Problem | Cause and solution |
|---|---|
| *Bad Request (400)* when opening Kartei | The host name is missing in `ALLOWED_HOSTS`. Add it and run `docker compose up -d`. |
| *Forbidden (403)* / CSRF error when signing in or saving | `CSRF_TRUSTED_ORIGINS` does not match the address in the browser exactly (scheme, host, port), or the proxy does not send `X-Forwarded-Proto: https`. |
| Sign-in succeeds, but you are back on the sign-in page | Access over plain HTTP: the Secure cookie is not stored. Use HTTPS (or `SECURE_COOKIES=0` for local tests only). |
| *Too many attempts – please wait 15 minutes* | 10 failed sign-ins for this username. Wait, or restart `web` to clear the counters. |
| AD user cannot sign in | Not in any role group (check with *Save & test* and *Test user*), account disabled, or a local user with the same name exists. Check `docker compose logs web`. |
| LDAP test: *Can't contact LDAP server* | Server or port unreachable, or the certificate is not trusted: paste the root CA under *CA certificate*. |
| User import: *No users found in the groups* | The *User search base* does not contain the group members, or the group DNs are wrong. Nothing was changed. |
| Export status *error*: *Row count dropped …* / *Empty export …* | The guard stopped it. Check the data and the filter; if the drop is intended, use *Force*. |
| Export error *Permission denied* | The export directory is not writable for UID 1000, or a network share is not mounted (restart the containers after mounting). |
| Exports or syncs do not run | Is `exporter` running (`docker compose ps`)? Check `docker compose logs exporter`, the *Export interval* and *Export enabled* / *schedule*. |
| AD sync: *… contacts would be deleted (limit … %)* | The guard stopped it. Check with *Save & dry run*; raise *Max. deletions (%)* temporarily if the deletions are intended. |
| AD sync: *Insufficient access* in the failures | The writing account lacks rights on the target OU. |
| Outlook: `HTTP 401` / `invalid_client` | Wrong or expired client secret. Create a new secret and enter it. |
| Outlook: `HTTP 403` / *Access is denied* | Admin consent missing, or the mailbox is outside the application access policy. |
| Outlook: *The group has no members with a mailbox* | Wrong group ID, or the members have no Exchange Online mailbox. |
| iPhone cannot connect | CardDAV not enabled, wrong password (generate a new one), proxy blocks `PROPFIND`/`REPORT` or the `Authorization` header, or 20 failed logins (wait 15 minutes). |
| Review emails are not sent | Email transport not complete (check with *Save & send test*), the reviewer has no email address, or `exporter` is not running. Mail errors are logged by `exporter`. |
| Microsoft 365 mail: `HTTP 403` | The app lacks the application permission `Mail.Send` (with admin consent), or the sending mailbox is outside the application access policy. |
| Changed email text is not used | A broken stored text (e.g. after an update) falls back to the default text; the `exporter` log shows a warning. Open *Email texts* and save the text again. |
| Links in emails or the CardDAV address are wrong | Set the *Public URL* under *General*. |
| Saved passwords suddenly do not work | `SECRET_KEY` changed. Enter the LDAP, AD, Outlook and SMTP passwords again. |
| CSV import fails with *413* | The reverse proxy limits the upload size (`client_max_body_size`). |
| Admin password lost | `docker compose exec web python manage.py changepassword <username>` |
