# Studio backup and restore

These operator commands back up the **database and actual uploaded media bytes together**. They are not web endpoints and have no destructive restore or force option.

## Create and verify

Use a private directory on the operator's persistent storage. The output filename must not already exist.

```bash
python manage.py studio_backup /private-backups/mahjong-2026-10-25.zip
python manage.py studio_backup --verify /private-backups/mahjong-2026-10-25.zip
```

To retain machine-readable verification evidence, choose a fresh private receipt filename:

```bash
python manage.py studio_backup --verify /private-backups/mahjong-2026-10-25.zip --receipt /private-backups/mahjong-2026-10-25.verified.json
```

The optional receipt records the SHA-256 and byte length of the complete verified archive,
verification/backup timestamps, record/object counts, and archived engine/schema/fixture hashes.
Verification and hashing use the same open file and reject changes detected during the check.
The JSON receipt is written atomically with mode `0600`, never overwrites an existing file or
symlink, and is produced only after verification succeeds. Verification does not query or modify
the live database. Existing command output remains unchanged unless `--receipt` is supplied.

A receipt proves archive integrity at verification time. It does not prove an offsite copy,
retention schedule, a successful restore, physical-device acceptance, or the exact source commit
that created the backup. Keep the matching deployment image/commit and private storage/restore
receipts separately. Neither the archive nor its receipt is an authenticated signature.

The final ZIP and temporary fixtures have mode `0600`; temporary directories have mode `0700`. The command creates the final file atomically without replacing an existing file. A missing or corrupt stored object causes the backup to fail rather than produce a partial successful archive. Output contains only verification status, record/object counts and the engine hash.

The archive contains:

- A native Django JSONL fixture of every `game_studio` model, users, groups and database-backed admin sessions. This includes release/configuration snapshots, drafts, assets, durable jobs/audit records, players, tickets, round transcripts/responses, ledgers and idempotency records.
- The actual immutable bytes for every `Asset.object_key`, including uploaded originals and all recorded derivatives. Shared content hashes are stored once. Unreferenced storage orphans are not needed to restore the database and are omitted.
- A manifest with model counts, fixture/object SHA-256 hashes, byte lengths, engine hash, model-schema fingerprint and applied migrations.

Content types and permission rows are excluded because migrations create them. Group and user permission references use natural keys, so destination permission IDs may differ. User and game object IDs are retained.

PostgreSQL uses one repeatable-read, read-only database snapshot during serialization. SQLite uses its transactional snapshot and is intended for development/testing. Once database serialization finishes, immutable object bytes are collected without holding that snapshot open. No garbage collector may remove referenced objects during backup; the current engine retains them.

**Keep this archive private.** It contains password hashes, signed session data and unrevealed ticket seeds. ZIP checksums and SHA-256 detect corruption; they do not authenticate an attacker who can rewrite the entire archive and its manifest. Restore only archives from trusted operator storage. Transport/encrypt archives using the operator's established secret-storage process; these commands do not invent or print encryption passwords.

Application source, the matching container/Git release, environment credentials, the Django secret key and static artwork shipped by that build are not copied into the archive. Retain that exact deployment image/source separately. Preserve `DJANGO_SECRET_KEY` out of band when existing admin sessions need to remain valid; otherwise users must sign in again. Media uploads themselves are included as bytes, not as expiring signed URLs.

## Restore into a new empty environment

Prepare a **separate empty PostgreSQL database and a private media destination**. Stop web/bootstrap/worker processes for that target while restoring. Use the application build matching the archived engine and model schema.

```bash
python manage.py migrate --noinput
python manage.py studio_backup --verify /private-backups/mahjong-2026-10-25.zip
python manage.py studio_restore /private-backups/mahjong-2026-10-25.zip
```

Do not run `bootstrap_studio` before restore: it intentionally creates baseline data and roles, and restore will then refuse the nonempty database. Migrations alone are expected to create only schema, content types and permissions. A different database alias can be selected with `--database ALIAS`.

Restore verifies every member, checksum, schema and Asset-to-object relationship before modifying storage or the database. It rejects duplicate ZIP names, traversal/absolute/unknown paths, symlinks, encrypted or unsupported members, oversized expansions, unsupported models and duplicate fixture identities. It does not call ZIP extraction on untrusted paths.

The target must contain **zero** game records, users, groups or sessions. PostgreSQL table locks (with a five-second acquisition timeout) and a second empty check prevent a concurrent bootstrap or writer from being overwritten. SQLite takes an equivalent write reservation for development. Objects are restored through the immutable content store, then Django loads the fixture within a database transaction. Restored model counts must exactly match the archive.

If database import fails, all imported database rows roll back. Immutable object copies that were already written may remain unreferenced; they never replace differing bytes and are safe to reuse on a corrected retry. The command does not delete target data or attempt to repair a populated database. Original records in a nonempty target are never changed.

After successful restore, verify a known completed round and its ledger balance, confirm the active release/assets and owner login, then resume the target's web/worker services and route traffic to it. Already claimed jobs or pending tickets retain their saved leases and fencing values; recovery uses the existing lease rules. Keep the old environment isolated during cutover.

## Bounded archive format

This version supports up to 512 MiB archive/uncompressed contents, 128 MiB JSONL fixture, 16 MiB per JSONL record, 250,000 records and 10,000 unique media objects. Media members are stored without ZIP compression; fixture/manifest compression has an expansion-ratio bound. ZIP64 and split archives are unsupported. The central directory is bounded before allocating all member objects, and JSONL records are parsed incrementally.

An archive beyond these limits fails with a nonzero exit code. It is not silently truncated. Larger installations require a separately designed database snapshot and streamed object-backup workflow before increasing these limits.

## Verification evidence

Run:

```bash
python manage.py test game_studio.test_backup
```

The tests operate exclusively in Django's isolated test database and temporary media directories. The round-trip case includes a completed real engine round, its ledger/idempotency response, a future committed ticket, owner password/group permissions, an admin session, an original tile and its rendered derivative. Destination permission IDs are deliberately changed to prove natural-key restoration. Replay and retry settlement remain identical after restore. Additional cases cover corruption before any restore writes, path/symlink/duplicate/compression rejection, nonempty-target refusal, failed import rollback, private file permissions, no-overwrite behavior, missing object failure and secret-free command output.
