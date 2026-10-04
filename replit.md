# ATHAR on Replit

ATHAR is an Arabic RTL Django application. Keep the existing Django apps,
templates, static assets, and included SQLite database; do not migrate or seed
over its imported content as part of environment setup.

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
- The preview explicitly uses the included `db.sqlite3`, even if Replit supplies
  a `DATABASE_URL`. Changing storage requires an intentional decision; the
  existing production configuration still uses its configured database URL.
- The default extractive AI mode needs no API key. External AI providers
  remain optional and must be configured through secrets or the app's provider UI.
- Useful routes: `/`, `/discover/`, `/timeline/`, `/login/`, `/dashboard/`,
  and `/healthz/`.

## Checks

```sh
DJANGO_SETTINGS_MODULE=config.replit python manage.py check
DJANGO_SETTINGS_MODULE=config.replit python manage.py test tests --noinput
```

## Before publishing

This is a development preview, not a production deployment. The imported README
documents a shared demo administrator password; replace it before exposing the
app to other users. Production setup is documented in `PRODUCTION.md` and
`config/production.py`, including PostgreSQL, explicit hosts, HTTPS origins,
and secure secret configuration. Do not publish with `config.replit`.