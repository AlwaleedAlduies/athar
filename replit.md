# ATHAR on Replit

ATHAR is an Arabic RTL Django application. Keep the existing Django apps,
templates, static assets, and included SQLite backup. The user approved using
PostgreSQL for publishing while preserving imported historical content.

## Running

Use the **Run** button / **Start application** workflow. It runs:

```sh
DJANGO_SETTINGS_MODULE=config.replit python manage.py migrate --noinput && DJANGO_SETTINGS_MODULE=config.replit python manage.py runserver 0.0.0.0:5000
```

Python 3.12 and the packages in `requirements.lock` are installed into Replit's
managed Python environment. No virtual environment or Docker is needed.
`requirements.txt` retains the repository's dependency declarations.
The test-only `reportlab` dependency from `requirements-dev.txt` is also installed.

## Preview configuration

- `config.replit` is development-only. It supports Replit's HTTPS proxy, preview
  hosts, and CSRF origins without altering the existing production settings.
- The existing `SESSION_SECRET` Replit secret supplies Django's signing key
  when `SECRET_KEY` is not set. Do not print or commit either secret.
- The preview now uses Replit's development PostgreSQL through `DATABASE_URL`.
  Historical content was initially copied using `import_sqlite_content`.
  `restore_sqlite_database` restores the full bundled snapshot into development
  PostgreSQL, including accounts, activity, AI logs, and author/analysis links.
  The SQLite source stays read-only and unchanged. Saved sessions are excluded,
  and provider configurations are preserved inactive until tested here.
- The default extractive AI mode needs no API key. External AI providers
  remain optional and must be configured through secrets or the app's provider UI.
- Useful routes: `/`, `/discover/`, `/timeline/`, `/login/`, `/dashboard/`,
  and `/healthz/`.

## Checks

```sh
DJANGO_SETTINGS_MODULE=config.replit python manage.py check
DJANGO_SETTINGS_MODULE=config.replit python manage.py test tests --noinput
```

## Publishing

The Autoscale publish command is `env PORT=5000 python deploy/replit_serve.py`,
using Waitress and `config.replit_production`. The build command only runs
`collectstatic`. Neither command runs migrations: Replit's Publish flow applies
the development schema to production. Keep `deploy/serve.py` unchanged for the
existing external Railway/Caddy deployment workflow.

Production environment variables are configured with `DEBUG=false`,
`DEMO_MODE=false`, explicit domain/HTTPS origin, and extractive AI mode.
`config.replit_production` uses `SESSION_SECRET` if `SECRET_KEY` is absent.
Keep the signing secret unchanged. The root page is exempted from Django's
HTTP redirect for Replit's internal startup probe; other routes enforce HTTPS.
Do not publish with the development `config.replit` settings.

The first production database must be initialized from the populated development
database through Publishing. If production already exists but is empty, use the
Publishing option to copy development data after confirming it is still empty.
Do not run schema mutations against Replit's managed production database.

The full restore keeps the source administrator account but replaces its shared
README password with the private `ATHAR_ADMIN_PASSWORD` Replit secret before
importing it. This secret is only used by management commands, not runtime
authentication. Remove it from Secrets after the import if it is no longer
needed. Production file uploads still use local media storage; configure durable
object storage before relying on uploaded files across Autoscale restarts.

The content import is development-only, read-only against the SQLite source,
transactional, and refuses to overwrite existing content:

```sh
DJANGO_SETTINGS_MODULE=config.settings python manage.py import_sqlite_content
# Add --apply only when the development content database is empty.
```

The full restore is also development-only and transactional. It refuses to
overwrite development rows whose IDs are absent from the source snapshot:

```sh
DJANGO_SETTINGS_MODULE=config.replit python manage.py restore_sqlite_database
# Requires ATHAR_ADMIN_PASSWORD in Replit Secrets:
DJANGO_SETTINGS_MODULE=config.replit python manage.py restore_sqlite_database --apply
```