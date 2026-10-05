"""Restore the bundled SQLite snapshot into development PostgreSQL."""
import io
import json
import os
from pathlib import Path
import tempfile

from django.apps import apps
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction


EXCLUDED_MODELS = {"sessions.session"}


class Command(BaseCommand):
    help = (
        "Restore the bundled SQLite snapshot into development PostgreSQL. "
        "Does not import saved login sessions."
    )

    def add_arguments(self, parser):
        parser.add_argument("--source", default=str(settings.BASE_DIR / "db.sqlite3"))
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        settings_module = (
            os.environ.get("DJANGO_SETTINGS_MODULE", "")
            or getattr(settings, "SETTINGS_MODULE", "")
        )
        target = connections["default"]
        if not settings.DEBUG or "production" in settings_module:
            raise CommandError("Development only. Production is initialized through Publishing.")
        if target.vendor != "postgresql":
            raise CommandError("Target must be development PostgreSQL; SQLite is never modified.")

        source = Path(options["source"]).resolve()
        if not source.is_file():
            raise CommandError("Source SQLite file does not exist.")

        source_alias = "sqlite_restore_source"
        source_config = dict(target.settings_dict)
        source_config.update(
            ENGINE="django.db.backends.sqlite3",
            NAME=f"{source.as_uri()}?mode=ro",
            USER="",
            PASSWORD="",
            HOST="",
            PORT="",
            OPTIONS={"uri": True},
            CONN_MAX_AGE=0,
        )
        connections.databases[source_alias] = source_config

        models = [
            model
            for model in apps.get_models()
            if model._meta.label_lower not in EXCLUDED_MODELS
        ]
        try:
            source_counts = {
                model: model._base_manager.using(source_alias).count()
                for model in models
            }
            excluded_sessions = (
                apps.get_model("sessions.Session")
                ._base_manager.using(source_alias)
                .count()
            )
            source_primary_keys = {
                model: set(
                    model._base_manager.using(source_alias).values_list("pk", flat=True)
                )
                for model in models
            }
            total_records = sum(source_counts.values())
            self.stdout.write(
                f"{total_records} database records found; "
                f"{excluded_sessions} saved session(s) will not be restored."
            )
            if not options["apply"]:
                self.stdout.write("Dry run only. Add --apply to restore into development PostgreSQL.")
                return

            password = os.environ.get("ATHAR_ADMIN_PASSWORD")
            if not password:
                raise CommandError(
                    "Set ATHAR_ADMIN_PASSWORD in Replit Secrets before applying the restore."
                )
            user_model = apps.get_model(settings.AUTH_USER_MODEL)
            source_admins = list(
                user_model._base_manager.using(source_alias)
                .filter(username="admin", role="ADMIN")
            )
            if len(source_admins) != 1:
                raise CommandError(
                    "Expected exactly one source account with the administrator role."
                )
            new_admin = user_model(username="admin", role="ADMIN")
            try:
                validate_password(password, new_admin)
            except Exception as exc:
                # Validation feedback can include characteristics of the secret;
                # do not echo it in terminal output or logs.
                raise CommandError(
                    "ATHAR_ADMIN_PASSWORD does not meet the configured password policy."
                ) from exc
            new_admin.set_password(password)
            replacement_hash = new_admin.password

            with tempfile.TemporaryDirectory(prefix="athar-full-restore-") as directory:
                fixture = Path(directory) / "database.json"
                call_command(
                    "dumpdata",
                    database=source_alias,
                    all=True,
                    exclude=["sessions"],
                    output=str(fixture),
                    verbosity=0,
                )
                records = json.loads(fixture.read_text(encoding="utf-8"))
                admin_records = [
                    record
                    for record in records
                    if record.get("model") == user_model._meta.label_lower
                    and record.get("fields", {}).get("username") == "admin"
                    and record.get("fields", {}).get("role") == "ADMIN"
                ]
                if len(admin_records) != 1:
                    raise CommandError("Could not safely identify the administrator in the fixture.")
                admin_records[0]["fields"]["password"] = replacement_hash
                fixture.write_text(
                    json.dumps(records, ensure_ascii=False),
                    encoding="utf-8",
                )

                with transaction.atomic(using="default"):
                    with target.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_xact_lock(604102026)")

                    # Refuse to overwrite any development row that is not part
                    # of this source snapshot.
                    unexpected_models = []
                    for model in models:
                        target_primary_keys = set(
                            model._base_manager.using("default").values_list("pk", flat=True)
                        )
                        if target_primary_keys - source_primary_keys[model]:
                            unexpected_models.append(model._meta.label_lower)
                    if unexpected_models:
                        raise CommandError(
                            "Development contains rows absent from the source snapshot; "
                            "refusing to overwrite: " + ", ".join(unexpected_models)
                        )

                    call_command(
                        "loaddata",
                        str(fixture),
                        database="default",
                        stdout=io.StringIO(),
                        verbosity=0,
                    )
                    # Also discard any development sessions so none can be
                    # copied to production by the Publish database-copy flow.
                    apps.get_model("sessions.Session")._base_manager.using("default").all().delete()
                    target.check_constraints()
        finally:
            connections[source_alias].close()
            del connections.databases[source_alias]

        self.stdout.write(
            self.style.SUCCESS(
                "Database restored to development PostgreSQL; the shared demo "
                "administrator password was replaced, and saved sessions were excluded."
            )
        )
