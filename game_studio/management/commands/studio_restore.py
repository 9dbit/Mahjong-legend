"""Restore a verified private archive into an empty, already migrated database."""
from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from game_studio.domain import ENGINE_HASH
from game_studio.storage import StorageError, _validate_key
from .studio_backup import (BackupError, FIXTURE_NAME, _read_checked, backup_models,
                            media_store, migrations, model_schema, open_archive,
                            summary, verify_open_archive)


def _empty(database):
    if any(model._base_manager.using(database).exists() for model in backup_models()):
        raise BackupError("Restore requires an empty game, user, group and session database; nothing was replaced")


def _lock_empty_database(database):
    connection = connections[database]
    if connection.vendor == "postgresql":
        tables = {model._meta.db_table for model in backup_models()}
        for model in backup_models():
            tables.update(field.remote_field.through._meta.db_table for field in model._meta.local_many_to_many)
        quoted = ", ".join(connection.ops.quote_name(name) for name in sorted(tables))
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute(f"LOCK TABLE {quoted} IN ACCESS EXCLUSIVE MODE")
    elif connection.vendor == "sqlite":
        # Also takes a write reservation if a custom SQLite setting uses deferred
        # transactions. No row is modified; concurrent bootstrap cannot race us.
        with connection.cursor() as cursor:
            cursor.execute('UPDATE "game_studio_activerelease" SET "id" = "id" WHERE 0')
    else:
        raise BackupError("Restore supports PostgreSQL and SQLite only")
    _empty(database)


def restore_backup(path, database="default"):
    with open_archive(path) as archive:
        manifest = verify_open_archive(archive)
        if manifest["schema_sha256"] != model_schema() or manifest["engine_sha256"] != ENGINE_HASH:
            raise BackupError("Restore requires the matching model schema and game engine build")
        if manifest["migrations"] != migrations(database):
            raise BackupError("Target migrations differ from the archive; use the matching migrated build")
        _empty(database)
        store = media_store()
        with tempfile.TemporaryDirectory(prefix="mahjong-restore-") as tmp:
            fixture_path = Path(tmp) / FIXTURE_NAME
            descriptor = os.open(fixture_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                entry = manifest["fixture"]
                _read_checked(archive, FIXTURE_NAME, entry["sha256"], entry["size"], output)
            try:
                with transaction.atomic(using=database):
                    _lock_empty_database(database)
                    for item in manifest["objects"]:
                        # Re-check bytes before each immutable write, guarding
                        # against an archive changed after initial verification.
                        output = io.BytesIO()
                        _read_checked(archive, item["key"], item["sha256"], item["size"], output)
                        _, extension = _validate_key(item["key"])
                        receipt = store.put(output.getvalue(), extension)
                        if receipt != {"key": item["key"], "sha256": item["sha256"], "size": item["size"]}:
                            raise BackupError("Restored object differs from its immutable manifest")
                    call_command("loaddata", str(fixture_path), database=database, verbosity=0,
                                 stdout=io.StringIO(), stderr=io.StringIO())
                    counts = {model._meta.label_lower: model._base_manager.using(database).count() for model in backup_models()}
                    if counts != manifest["counts"]:
                        raise BackupError("Restored model counts differ from the verified archive")
            except (BackupError, StorageError):
                raise
            except Exception:
                # A loaddata error can include a field's value. Keep all fixture
                # contents, credentials and future seeds out of CLI logs.
                raise BackupError("Database restore failed and its transaction was rolled back") from None
        return manifest


class Command(BaseCommand):
    help = "Restore a complete Studio backup into an empty, already migrated database."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("archive")
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        try:
            manifest = restore_backup(options["archive"], options["database"])
        except (BackupError, StorageError) as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError("Restore failed; no archive contents or credentials were logged") from None
        import json
        self.stdout.write(json.dumps({**summary(manifest), "restored": True}, sort_keys=True))
