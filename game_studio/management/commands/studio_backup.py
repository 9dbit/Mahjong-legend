"""Private, bounded database-and-object archives; never used by a web endpoint."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import stat
import struct
import tempfile
import zipfile

import django
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from game_studio.domain import ENGINE_HASH
from game_studio.models import Asset
from game_studio.storage import ContentStore, MAX_OBJECT_BYTES, StorageError, _validate_key


FORMAT = "mahjong-studio-backup/1"
FIXTURE_NAME = "database.jsonl"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_FIXTURE_BYTES = 128 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_OBJECTS = 10_000
MAX_RECORDS = 250_000
MAX_COMPRESSION_RATIO = 256
CHUNK = 128 * 1024


class BackupError(ValueError):
    """The archive is incomplete, incompatible or unsafe to restore."""


def backup_models():
    """Permissions/contenttypes are migrated; references to them use natural keys."""
    models = [Group, get_user_model(), Session, *apps.get_app_config("game_studio").get_models()]
    return list(dict.fromkeys(models))


def model_schema():
    shape = {}
    for model in backup_models():
        fields = []
        for field in [*model._meta.local_fields, *model._meta.local_many_to_many]:
            fields.append({"name": field.name, "type": field.get_internal_type(),
                           "pk": field.primary_key, "null": field.null,
                           "max_length": field.max_length,
                           "max_digits": getattr(field, "max_digits", None),
                           "decimal_places": getattr(field, "decimal_places", None),
                           "related": field.related_model._meta.label_lower if field.is_relation else None})
        shape[model._meta.label_lower] = fields
    return sha256(json.dumps(shape, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def migrations(database):
    included = {model._meta.app_label for model in backup_models()} | {"contenttypes", "auth"}
    rows = MigrationRecorder(connections[database]).applied_migrations()
    return sorted(f"{app}.{name}" for app, name in rows if app in included)


def media_store():
    return ContentStore(root=None if os.environ.get("STUDIO_S3_BUCKET") else settings.STUDIO_MEDIA_ROOT)


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BackupError("Archive JSON contains duplicate keys")
            result[key] = value
        return result

    def invalid_constant(value):
        raise BackupError("Archive JSON contains a non-finite number")

    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            raise BackupError("Archive JSON contains a non-finite number")
        return number

    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=invalid_constant, parse_float=floating)
    except BackupError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise BackupError("Archive JSON is invalid") from exc


def _hash_file(path: Path, maximum: int) -> tuple[str, int]:
    digest, size = sha256(), 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK):
            size += len(chunk)
            if size > maximum:
                raise BackupError("Backup exceeds the configured size limit")
            digest.update(chunk)
    return digest.hexdigest(), size


def _check_zip_envelope(source):
    """Bound the central directory before ZipFile allocates all ZipInfo objects."""
    source.seek(0, os.SEEK_END)
    size = source.tell()
    if not 22 <= size <= MAX_ARCHIVE_BYTES:
        raise BackupError("Archive is empty or exceeds 512 MiB")
    source.seek(max(0, size - 65557))
    tail = source.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0 or len(tail) - offset < 22:
        raise BackupError("Archive has no valid ZIP directory")
    _, disk, directory_disk, on_disk, entries, directory_size, directory_offset, comment_size = struct.unpack(
        "<4s4H2LH", tail[offset:offset + 22])
    if (disk or directory_disk or on_disk != entries or entries > MAX_OBJECTS + 2
            or directory_size > 4 * 1024 * 1024 or directory_offset + directory_size > size - 22
            or offset + 22 + comment_size != len(tail)):
        raise BackupError("Archive directory exceeds supported ZIP limits")
    if entries == 65535 or directory_offset == 0xFFFFFFFF or directory_size == 0xFFFFFFFF:
        raise BackupError("ZIP64 and multi-disk archives are unsupported")
    source.seek(0)


@contextmanager
def open_archive(path):
    try:
        with Path(path).open("rb") as source:
            _check_zip_envelope(source)
            with zipfile.ZipFile(source) as archive:
                yield archive
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError) as exc:
        raise BackupError("Archive could not be read or failed its ZIP integrity check") from exc


def _read_checked(archive, name, expected_hash, expected_size, sink=None):
    digest, size = sha256(), 0
    with archive.open(name) as source:
        while chunk := source.read(CHUNK):
            size += len(chunk)
            if size > expected_size:
                raise BackupError("Archive member exceeds its declared size")
            digest.update(chunk)
            if sink is not None:
                sink.write(chunk)
    if size != expected_size or digest.hexdigest() != expected_hash:
        raise BackupError("Archive member failed SHA-256 verification")


def _fixture_review(archive):
    allowed = {model._meta.label_lower: model for model in backup_models()}
    counts = Counter({name: 0 for name in allowed})
    identities, objects = set(), {}
    with archive.open(FIXTURE_NAME) as source:
        while line := source.readline(MAX_RECORD_BYTES + 1):
            if len(line) > MAX_RECORD_BYTES:
                raise BackupError("A database record exceeds 16 MiB")
            if not line.strip():
                continue
            record = _json(line)
            if (not isinstance(record, dict) or set(record) != {"model", "pk", "fields"}
                    or not isinstance(record["model"], str) or record["model"] not in allowed or not isinstance(record["fields"], dict)
                    or isinstance(record["pk"], bool) or not isinstance(record["pk"], (str, int))):
                raise BackupError("Database fixture contains an unsupported model or record")
            model = allowed[record["model"]]
            expected_fields = {field.name for field in [*model._meta.local_fields, *model._meta.local_many_to_many]
                               if field.serialize}
            if set(record["fields"]) != expected_fields:
                raise BackupError("Database fixture does not match the complete model schema")
            try:
                identity = (record["model"], str(model._meta.pk.to_python(record["pk"])))
            except Exception as exc:
                raise BackupError("Database fixture contains an invalid primary key") from exc
            if identity in identities:
                raise BackupError("Database fixture contains duplicate identities")
            identities.add(identity)
            if len(identities) > MAX_RECORDS:
                raise BackupError("Database fixture exceeds the record limit")
            counts[record["model"]] += 1
            if record["model"] == "game_studio.asset":
                fields = record["fields"]
                try:
                    digest, _ = _validate_key(fields["object_key"])
                except (StorageError, KeyError, TypeError) as exc:
                    raise BackupError("An asset references an invalid object key") from exc
                byte_size = fields.get("byte_size")
                if (digest != fields.get("sha256") or type(byte_size) is not int
                        or not 1 <= byte_size <= MAX_OBJECT_BYTES):
                    raise BackupError("Asset size or hash does not match its immutable object key")
                value = {"key": fields["object_key"], "sha256": digest, "size": byte_size}
                previous = objects.setdefault(fields["object_key"], value)
                if previous != value:
                    raise BackupError("Assets disagree about the same immutable object")
    return dict(counts), objects


def verify_open_archive(archive):
    """Verify all archive bytes and references without writing DB or media storage."""
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(entries) > MAX_OBJECTS + 2 or len(set(names)) != len(names):
        raise BackupError("Archive contains too many or duplicate members")
    total = 0
    for entry in entries:
        mode = (entry.external_attr >> 16) & 0o170000
        if (entry.is_dir() or mode not in (0, stat.S_IFREG) or entry.flag_bits & 1
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise BackupError("Archive contains an unsupported member type")
        if entry.filename == "manifest.json":
            maximum = MAX_MANIFEST_BYTES
        elif entry.filename == FIXTURE_NAME:
            maximum = MAX_FIXTURE_BYTES
        else:
            try:
                _validate_key(entry.filename)
            except StorageError as exc:
                raise BackupError("Archive contains an unsafe or unknown path") from exc
            maximum = MAX_OBJECT_BYTES
            if entry.compress_type != zipfile.ZIP_STORED:
                raise BackupError("Object bytes must use uncompressed ZIP members")
        if (entry.file_size > maximum or entry.file_size > max(1, entry.compress_size) * MAX_COMPRESSION_RATIO
                or entry.file_size < 0 or entry.compress_size < 0):
            raise BackupError("Archive member exceeds size or compression limits")
        total += entry.file_size
        if total > MAX_TOTAL_BYTES:
            raise BackupError("Archive expands beyond the 512 MiB limit")
    if "manifest.json" not in names or FIXTURE_NAME not in names:
        raise BackupError("Archive lacks its manifest or database fixture")
    manifest = _json(archive.read("manifest.json"))
    required = {"format", "created_at", "django_version", "schema_sha256", "engine_sha256", "migrations",
                "counts", "fixture", "objects"}
    if not isinstance(manifest, dict) or set(manifest) != required or manifest.get("format") != FORMAT:
        raise BackupError("Unsupported backup manifest")
    valid_digest = lambda value: isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    labels = {model._meta.label_lower for model in backup_models()}
    if (not valid_digest(manifest["schema_sha256"]) or not valid_digest(manifest["engine_sha256"])
            or not isinstance(manifest["created_at"], str) or len(manifest["created_at"]) > 40
            or not isinstance(manifest["django_version"], str) or len(manifest["django_version"]) > 40
            or not isinstance(manifest["counts"], dict) or set(manifest["counts"]) != labels
            or any(type(value) is not int or not 0 <= value <= MAX_RECORDS for value in manifest["counts"].values())
            or not isinstance(manifest["migrations"], list) or len(manifest["migrations"]) > 1000
            or any(not isinstance(value, str) or len(value) > 200 for value in manifest["migrations"])):
        raise BackupError("Invalid backup metadata")
    if not isinstance(manifest["objects"], list) or len(manifest["objects"]) > MAX_OBJECTS:
        raise BackupError("Invalid object manifest")
    fixture = manifest["fixture"]
    if (not isinstance(fixture, dict) or set(fixture) != {"name", "sha256", "size"}
            or fixture["name"] != FIXTURE_NAME or type(fixture["size"]) is not int
            or not 0 <= fixture["size"] <= MAX_FIXTURE_BYTES
            or not valid_digest(fixture["sha256"])
            or archive.getinfo(FIXTURE_NAME).file_size != fixture["size"]):
        raise BackupError("Invalid database fixture manifest")
    expected = {}
    for item in manifest["objects"]:
        if not isinstance(item, dict) or set(item) != {"key", "sha256", "size"}:
            raise BackupError("Invalid object manifest entry")
        try:
            key_hash, _ = _validate_key(item["key"])
        except (StorageError, TypeError) as exc:
            raise BackupError("Invalid object manifest key") from exc
        if (item["key"] in expected or item["sha256"] != key_hash or type(item["size"]) is not int
                or not 1 <= item["size"] <= MAX_OBJECT_BYTES):
            raise BackupError("Object manifest contains duplicate or inconsistent entries")
        expected[item["key"]] = item
    if set(names) != {"manifest.json", FIXTURE_NAME, *expected}:
        raise BackupError("Archive contains missing or unlisted files")
    _read_checked(archive, FIXTURE_NAME, fixture["sha256"], fixture["size"])
    counts, references = _fixture_review(archive)
    if counts != manifest["counts"] or references != expected:
        raise BackupError("Database references and archive manifest disagree")
    for item in expected.values():
        if archive.getinfo(item["key"]).file_size != item["size"]:
            raise BackupError("Object byte size differs from its manifest")
        _read_checked(archive, item["key"], item["sha256"], item["size"])
    return manifest


def verify_backup(path):
    with open_archive(path) as archive:
        return verify_open_archive(archive)


class _BoundedWriter:
    def __init__(self, output):
        self.output, self.size = output, 0

    def write(self, value):
        self.size += len(value.encode("utf-8"))
        if self.size > MAX_FIXTURE_BYTES:
            raise BackupError("Database fixture exceeds 128 MiB")
        return self.output.write(value)


def create_backup(path, database="default"):
    target = Path(path).absolute()
    if target.exists() or target.is_symlink():
        raise BackupError("Backup destination already exists; choose a new filename")
    if not target.parent.is_dir():
        raise BackupError("Backup destination directory must already exist")
    temporary_archive = None
    try:
        with tempfile.TemporaryDirectory(prefix="mahjong-backup-") as tmp:
            fixture_path = Path(tmp) / FIXTURE_NAME
            # mkstemp/TemporaryDirectory keep both temporary secrets and final ZIP private.
            connection = connections[database]
            with transaction.atomic(using=database):
                if connection.vendor == "postgresql":
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                elif connection.vendor != "sqlite":
                    raise BackupError("Backup snapshot supports PostgreSQL and SQLite only")
                counts = {model._meta.label_lower: model._base_manager.using(database).count() for model in backup_models()}
                if sum(counts.values()) > MAX_RECORDS:
                    raise BackupError("Database exceeds the bounded archive record limit")

                def records():
                    for model in backup_models():
                        yield from model._base_manager.using(database).order_by(model._meta.pk.name).iterator(chunk_size=200)

                descriptor = os.open(fixture_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    serializers.serialize("jsonl", records(), stream=_BoundedWriter(output),
                                          use_natural_foreign_keys=True, ensure_ascii=False)
                objects = {}
                for key, digest, size in Asset.objects.using(database).values_list("object_key", "sha256", "byte_size"):
                    candidate = {"key": key, "sha256": digest, "size": size}
                    if objects.setdefault(key, candidate) != candidate:
                        raise BackupError("Asset metadata is inconsistent")
                migration_state = migrations(database)
            if len(objects) > MAX_OBJECTS:
                raise BackupError("Object count exceeds the bounded archive limit")
            fixture_hash, fixture_size = _hash_file(fixture_path, MAX_FIXTURE_BYTES)
            manifest = {"format": FORMAT, "created_at": timezone.now().isoformat(),
                        "django_version": django.get_version(), "schema_sha256": model_schema(),
                        "engine_sha256": ENGINE_HASH, "migrations": migration_state, "counts": counts,
                        "fixture": {"name": FIXTURE_NAME, "sha256": fixture_hash, "size": fixture_size},
                        "objects": sorted(objects.values(), key=lambda item: item["key"])}
            manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            total = fixture_size + len(manifest_bytes) + sum(item["size"] for item in objects.values())
            if total > MAX_TOTAL_BYTES or len(manifest_bytes) > MAX_MANIFEST_BYTES:
                raise BackupError("Backup exceeds the 512 MiB bounded archive limit")
            descriptor, filename = tempfile.mkstemp(prefix=".studio-backup-", dir=target.parent)
            temporary_archive = Path(filename)
            os.close(descriptor)
            store = media_store()
            with zipfile.ZipFile(temporary_archive, "w", allowZip64=False) as archive:
                archive.writestr("manifest.json", manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)
                archive.write(fixture_path, FIXTURE_NAME, compress_type=zipfile.ZIP_DEFLATED)
                for item in manifest["objects"]:
                    data = store.get(item["key"])
                    if len(data) != item["size"] or sha256(data).hexdigest() != item["sha256"]:
                        raise BackupError("Stored object does not match database metadata")
                    archive.writestr(item["key"], data, compress_type=zipfile.ZIP_STORED)
            verify_backup(temporary_archive)
            with temporary_archive.open("rb") as output:
                os.fsync(output.fileno())
            try:
                os.link(temporary_archive, target)
            except FileExistsError as exc:
                raise BackupError("Backup destination already exists; nothing was overwritten") from exc
            if hasattr(os, "O_DIRECTORY"):
                directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return manifest
    finally:
        if temporary_archive is not None:
            temporary_archive.unlink(missing_ok=True)


def summary(manifest):
    return {"verified": True, "records": sum(manifest["counts"].values()),
            "objects": len(manifest["objects"]), "engine_sha256": manifest["engine_sha256"]}


def verification_receipt(path):
    """Hash and verify the same open archive, without reading the live database."""
    with open_archive(path) as archive:
        source = archive.fp
        before = os.fstat(source.fileno())
        manifest = verify_open_archive(archive)
        source.seek(0)
        digest, size = sha256(), 0
        while chunk := source.read(CHUNK):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise BackupError("Archive exceeds the bounded archive limit")
            digest.update(chunk)
        after = os.fstat(source.fileno())
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                  info.st_mtime_ns, info.st_ctime_ns)
        if identity(before) != identity(after) or size != before.st_size:
            raise BackupError("Archive changed during verification; no receipt was written")
        return {**summary(manifest), "format": "mahjong-studio-backup-receipt/1",
                "verified_at": timezone.now().isoformat(),
                "backup_created_at": manifest["created_at"],
                "archive_sha256": digest.hexdigest(), "archive_bytes": size,
                "schema_sha256": manifest["schema_sha256"],
                "fixture_sha256": manifest["fixture"]["sha256"]}


def write_verification_receipt(path, receipt):
    """Publish a private JSON receipt atomically, never replacing another file."""
    target = Path(path).absolute()
    if target.exists() or target.is_symlink():
        raise BackupError("Receipt destination already exists; choose a new filename")
    if not target.parent.is_dir():
        raise BackupError("Receipt destination directory must already exist")
    descriptor, filename = tempfile.mkstemp(prefix=".studio-receipt-", dir=target.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(receipt, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise BackupError("Receipt destination already exists; nothing was overwritten") from exc
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


class Command(BaseCommand):
    help = "Create a private database-and-object ZIP, or verify one without restoring it."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("output", nargs="?")
        parser.add_argument("--verify", metavar="FILE")
        parser.add_argument("--receipt", metavar="FILE",
                            help="With --verify, save private JSON evidence including the archive SHA-256.")
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        if bool(options["output"]) == bool(options["verify"]):
            raise CommandError("Supply a new output filename or --verify FILE, exclusively")
        if options["receipt"] and not options["verify"]:
            raise CommandError("--receipt requires --verify FILE; create the archive first")
        try:
            if options["receipt"]:
                receipt = verification_receipt(options["verify"])
                write_verification_receipt(options["receipt"], receipt)
                self.stdout.write(json.dumps(receipt, sort_keys=True))
                return
            manifest = (verify_backup(options["verify"]) if options["verify"]
                        else create_backup(options["output"], options["database"]))
        except (BackupError, StorageError) as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError("Backup failed; no archive contents or credentials were logged") from None
        self.stdout.write(json.dumps(summary(manifest), sort_keys=True))
