"""Round-trip only inside Django's isolated test database and temporary storage."""
from hashlib import sha256
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid
import warnings
import zipfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import F
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image

from . import game
from .domain import baseline_config
from .management.commands.studio_backup import (BackupError, FIXTURE_NAME, backup_models,
                                                 create_backup, verification_receipt, verify_backup)
from .management.commands.studio_restore import restore_backup
from .media import render_tile
from .models import (Asset, AuditEvent, AuthThrottle, Draft, Job, LedgerEntry,
                     PlayerSession, Release, Round, SpinRequest, SpinTicket)
from .releases import active_release
from .storage import ContentStore


class StudioBackupTests(TransactionTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="studio-backup-test-")
        self.root = Path(self.temporary.name)
        self.source_root = self.root / "source-objects"
        self.settings_override = override_settings(STUDIO_MEDIA_ROOT=str(self.source_root))
        self.settings_override.enable()
        self.env_override = patch.dict(os.environ, {"STUDIO_S3_BUCKET": ""})
        self.env_override.start()
        self.archive = self.root / "snapshot.zip"

    def tearDown(self):
        self.env_override.stop()
        self.settings_override.disable()
        self.temporary.cleanup()

    def fixture(self):
        call_command("bootstrap_studio", stdout=StringIO())
        self.user = get_user_model().objects.create_user("backup-owner", password="a-private-test-only-passphrase")
        self.user.groups.add(Group.objects.get(name="Owner"))
        self.user.user_permissions.add(Permission.objects.get(codename="publish_release", content_type__app_label="game_studio"))
        source = BytesIO()
        Image.new("RGBA", (32, 48), (120, 30, 220, 255)).save(source, format="PNG")
        original_data = source.getvalue()
        derivative_data = render_tile(original_data)
        store = ContentStore(self.source_root)
        self.assets = []
        for derivative, data in [(False, original_data), (True, derivative_data)]:
            receipt = store.put(data, "png")
            self.assets.append(Asset.objects.create(name="Private tile", kind="tile", status="ready",
                object_key=receipt["key"], sha256=receipt["sha256"], byte_size=receipt["size"], mime="image/png",
                metadata={"width":218 if derivative else 32,"height":327 if derivative else 48},
                created_by=self.user, original=self.assets[0] if derivative else None, is_derivative=derivative))
        draft = Draft.objects.create(name="Stored candidate", config=baseline_config(),
                                      base_release=active_release(), created_by=self.user)
        Job.objects.create(kind="render", request={"asset_id":str(self.assets[0].id)}, created_by=self.user)
        AuditEvent.objects.create(actor=self.user, action="backup_test", target=str(draft.id))
        AuthThrottle.objects.create(key="a" * 64, count=1, window_started=timezone.now())
        session = SessionStore()
        session["_auth_user_id"] = str(self.user.pk)
        session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        session["_auth_user_hash"] = self.user.get_session_auth_hash()
        session.save()
        self.admin_session_key = session.session_key
        self.player, _, _ = game.obtain()
        state = game.state(self.player)
        self.ticket_id = state["ticket"]["id"]
        self.request_key = uuid.uuid4()
        self.spin = game.spin(self.player, "1", self.ticket_id, self.request_key)
        self.next_seed = SpinTicket.objects.get(session=self.player, status="ready").secret_seed
        self.player_id = self.player.pk
        self.user_id = self.user.pk
        self.expected_objects = {asset.object_key:store.get(asset.object_key) for asset in self.assets}
        return create_backup(self.archive)

    def empty_test_database(self):
        # TransactionTestCase owns this database. This operation is never used by
        # either production command; restore has no flush/delete/force option.
        call_command("flush", interactive=False, verbosity=0, stdout=StringIO())

    def rewrite(self, change=None, additions=(), modify_info=None):
        target = self.root / f"changed-{uuid.uuid4().hex}.zip"
        with zipfile.ZipFile(self.archive) as source:
            members = {item.filename:(item, source.read(item.filename)) for item in source.infolist()}
        if change:
            change(members)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(target, "w") as output:
                for name, (info, data) in members.items():
                    if modify_info:
                        modify_info(info)
                    output.writestr(info, data)
                for name, data in additions:
                    output.writestr(name, data)
        return target

    def alter_fixture(self, transform):
        def change(members):
            info, data = members[FIXTURE_NAME]
            records = [json.loads(line) for line in data.splitlines() if line]
            transform(records)
            altered = b"".join(json.dumps(record, separators=(",", ":")).encode()+b"\n" for record in records)
            members[FIXTURE_NAME] = info, altered
            manifest_info, content = members["manifest.json"]
            manifest = json.loads(content)
            manifest["fixture"].update(sha256=sha256(altered).hexdigest(), size=len(altered))
            members["manifest.json"] = manifest_info, json.dumps(manifest).encode()
        return self.rewrite(change=change)

    def test_complete_roundtrip_preserves_replay_permissions_sessions_and_object_bytes(self):
        manifest = self.fixture()
        self.assertEqual(stat.S_IMODE(self.archive.stat().st_mode), 0o600)
        self.assertEqual(verify_backup(self.archive), manifest)
        self.assertEqual(len(manifest["objects"]), 2)
        self.assertNotIn("auth.permission", manifest["counts"])
        self.assertNotIn("contenttypes.contenttype", manifest["counts"])
        original_counts = manifest["counts"]
        self.empty_test_database()
        # IDs deliberately differ from the source. Permission natural keys must
        # resolve against the migrated destination, not the source integer IDs.
        Permission.objects.update(id=F("id") + 10000)
        restored_root = self.root / "restored-objects"
        with override_settings(STUDIO_MEDIA_ROOT=str(restored_root)):
            restored = restore_backup(self.archive)
            self.assertEqual(restored["counts"], original_counts)
            for key, data in self.expected_objects.items():
                self.assertEqual(ContentStore(restored_root).get(key), data)
        for model in backup_models():
            self.assertEqual(model._base_manager.count(), original_counts[model._meta.label_lower])
        user = get_user_model().objects.get(pk=self.user_id)
        self.assertTrue(user.check_password("a-private-test-only-passphrase"))
        self.assertTrue(user.has_perm("game_studio.publish_release"))
        self.assertTrue(user.groups.filter(name="Owner").exists())
        self.assertEqual(Session.objects.get(session_key=self.admin_session_key).get_decoded()["_auth_user_id"], str(user.pk))
        player = PlayerSession.objects.get(pk=self.player_id)
        self.assertEqual(SpinTicket.objects.get(session=player, status="ready").secret_seed, self.next_seed)
        self.assertEqual(game.spin(player, "1", self.ticket_id, self.request_key), self.spin)
        self.assertTrue(game.verify(player, self.spin["round"])["valid"])
        self.assertEqual(Round.objects.count(), 1)
        self.assertEqual(LedgerEntry.objects.filter(kind="round").count(), 1)
        self.assertEqual(SpinRequest.objects.count(), 1)

    def test_restore_refuses_nonempty_data_without_object_writes(self):
        self.fixture()
        with patch("game_studio.management.commands.studio_restore.media_store") as store:
            with self.assertRaisesRegex(BackupError, "empty"):
                restore_backup(self.archive)
            store.assert_not_called()
        self.empty_test_database()
        get_user_model().objects.create_user("existing-owner")
        with patch("game_studio.management.commands.studio_restore.media_store") as store:
            with self.assertRaisesRegex(BackupError, "empty"):
                restore_backup(self.archive)
            store.assert_not_called()
        self.assertEqual(get_user_model().objects.get().username, "existing-owner")

    def test_corrupt_object_fails_all_preflight_before_any_restore(self):
        self.fixture()
        key = self.assets[0].object_key
        def change(members):
            info, data = members[key]
            members[key] = info, bytes([data[0] ^ 1]) + data[1:]
        corrupt = self.rewrite(change=change)
        self.empty_test_database()
        with patch("game_studio.management.commands.studio_restore.media_store") as store:
            with self.assertRaisesRegex(BackupError, "SHA-256"):
                restore_backup(corrupt)
            store.assert_not_called()
        self.assertFalse(Release.objects.exists())
        self.assertFalse(get_user_model().objects.exists())

    def test_paths_duplicates_symlinks_and_unsupported_compression_rejected(self):
        self.fixture()
        for additions in ([('../outside.txt', b'x')], [('manifest.json', b'{}')], [('/absolute', b'x')]):
            with self.subTest(additions=additions), self.assertRaises(BackupError):
                verify_backup(self.rewrite(additions=additions))
        key = self.assets[0].object_key
        def symlink(info):
            if info.filename == key:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(BackupError, "member type"):
            verify_backup(self.rewrite(modify_info=symlink))
        def compressed_object(info):
            if info.filename == key:
                info.compress_type = zipfile.ZIP_DEFLATED
        with self.assertRaisesRegex(BackupError, "uncompressed"):
            verify_backup(self.rewrite(modify_info=compressed_object))

    def test_fixture_model_allowlist_and_size_limits(self):
        self.fixture()
        invalid = self.alter_fixture(lambda rows:rows.append({"model":"auth.permission","pk":99999,"fields":{}}))
        with self.assertRaisesRegex(BackupError, "unsupported model"):
            verify_backup(invalid)
        with patch("game_studio.management.commands.studio_backup.MAX_TOTAL_BYTES", 100):
            with self.assertRaisesRegex(BackupError, "512 MiB"):
                verify_backup(self.archive)

    def test_failed_database_import_rolls_back_every_database_record(self):
        self.fixture()
        def missing_owner(rows):
            for row in rows:
                if row["model"] == "game_studio.asset":
                    row["fields"]["created_by"] = ["not-an-archived-user"]
        inconsistent = self.alter_fixture(missing_owner)
        verify_backup(inconsistent)  # Hash-valid archive; invalid natural relationship.
        self.empty_test_database()
        with override_settings(STUDIO_MEDIA_ROOT=str(self.root / "failed-restore-objects")):
            with self.assertRaisesRegex(BackupError, "rolled back"):
                restore_backup(inconsistent)
        for model in backup_models():
            self.assertEqual(model._base_manager.count(), 0)

    def test_existing_archive_is_never_overwritten_and_missing_objects_leave_no_archive(self):
        self.fixture()
        before = self.archive.read_bytes()
        with self.assertRaisesRegex(BackupError, "already exists"):
            create_backup(self.archive)
        self.assertEqual(self.archive.read_bytes(), before)
        (self.source_root / self.assets[0].object_key).unlink()
        missing = self.root / "incomplete.zip"
        with self.assertRaises(Exception):
            create_backup(missing)
        self.assertFalse(missing.exists())
        self.assertFalse(list(self.root.glob('.studio-backup-*')))

    def test_cli_verification_does_not_log_fixture_secrets(self):
        self.fixture()
        output = StringIO()
        call_command("studio_backup", verify=str(self.archive), stdout=output)
        result = json.loads(output.getvalue())
        self.assertTrue(result["verified"])
        self.assertNotIn(self.next_seed, output.getvalue())
        self.assertNotIn(self.user.password, output.getvalue())
        self.assertNotIn(self.admin_session_key, output.getvalue())
        with self.assertRaises(CommandError):
            call_command("studio_restore", str(self.archive), stdout=StringIO())

    def test_private_receipt_identifies_exact_archive_without_database_queries_or_secrets(self):
        manifest = self.fixture()
        receipt_path = self.root / "verified.json"
        output = StringIO()
        with self.assertNumQueries(0):
            call_command("studio_backup", verify=str(self.archive), receipt=str(receipt_path), stdout=output)
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt, json.loads(output.getvalue()))
        self.assertEqual(receipt["format"], "mahjong-studio-backup-receipt/1")
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["archive_sha256"], sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(receipt["archive_bytes"], self.archive.stat().st_size)
        self.assertEqual(receipt["records"], sum(manifest["counts"].values()))
        self.assertEqual(receipt["objects"], len(manifest["objects"]))
        for key in ("engine_sha256", "schema_sha256"):
            self.assertEqual(receipt[key], manifest[key])
        self.assertEqual(receipt["fixture_sha256"], manifest["fixture"]["sha256"])
        self.assertEqual(receipt["backup_created_at"], manifest["created_at"])
        self.assertLessEqual(timezone.datetime.fromisoformat(receipt["verified_at"]), timezone.now())
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
        for secret in (self.next_seed, self.user.password, self.admin_session_key, self.user.username,
                       str(self.archive), self.assets[0].object_key):
            self.assertNotIn(secret, output.getvalue())

    def test_receipt_refuses_existing_files_and_symlinks_without_overwriting(self):
        self.fixture()
        original_archive = self.archive.read_bytes()
        existing = self.root / "existing.json"
        existing.write_text("keep original")
        link = self.root / "linked.json"
        link.symlink_to(existing)
        dangling = self.root / "dangling.json"
        dangling.symlink_to(self.root / "missing.json")
        for target in (existing, link, dangling, self.archive):
            with self.subTest(target=target.name), self.assertRaisesRegex(CommandError, "already exists"):
                call_command("studio_backup", verify=str(self.archive), receipt=str(target), stdout=StringIO())
        self.assertEqual(existing.read_text(), "keep original")
        self.assertEqual(self.archive.read_bytes(), original_archive)
        self.assertTrue(link.is_symlink())
        self.assertTrue(dangling.is_symlink())
        self.assertFalse(list(self.root.glob(".studio-receipt-*")))

    def test_failed_verification_never_creates_receipt(self):
        self.fixture()
        key = self.assets[0].object_key
        def corrupt(members):
            info, data = members[key]
            members[key] = info, bytes([data[0] ^ 1]) + data[1:]
        archive = self.rewrite(change=corrupt)
        receipt = self.root / "failed.json"
        with self.assertRaisesRegex(CommandError, "SHA-256"):
            call_command("studio_backup", verify=str(archive), receipt=str(receipt), stdout=StringIO())
        self.assertFalse(receipt.exists())

    def test_receipt_requires_explicit_verification(self):
        output, receipt = self.root / "new.zip", self.root / "invalid.json"
        with self.assertRaisesRegex(CommandError, "requires --verify"):
            call_command("studio_backup", str(output), receipt=str(receipt), stdout=StringIO())
        self.assertFalse(output.exists())
        self.assertFalse(receipt.exists())

    def test_archive_changed_during_verification_never_gets_a_receipt(self):
        self.fixture()
        from .management.commands.studio_backup import verify_open_archive
        def changed(archive):
            manifest = verify_open_archive(archive)
            with self.archive.open("ab") as output:
                output.write(b"changed during verification")
            return manifest
        with patch("game_studio.management.commands.studio_backup.verify_open_archive", side_effect=changed):
            with self.assertRaisesRegex(BackupError, "changed during verification"):
                verification_receipt(self.archive)
