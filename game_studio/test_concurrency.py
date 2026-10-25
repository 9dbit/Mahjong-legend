"""Independent release races and worker-lease recovery regressions.

PostgreSQL cases use separate real connections and database locks. SQLite runs
the deterministic takeover cases; it cannot establish PostgreSQL lock behavior.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import threading
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from . import game, jobs
from .domain import baseline_config, digest, ENGINE_HASH
from .models import (
    ActiveRelease, Asset, ConfigurationVersion, Job, LedgerEntry, PlayerSession,
    Release, Round, SpinTicket,
)
from .releases import bootstrap, make_release


class PostgreSQLIndependentRequestTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires PostgreSQL row locks; run in the PostgreSQL CI job')
        self.baseline = bootstrap()

    def test_unrelated_session_settles_while_other_ticket_and_shared_rows_are_locked(self):
        """An existing player's Spin must not wait on another player or publisher."""
        first, _, _ = game.obtain()
        second, _, _ = game.obtain()
        first_ticket = game.state(first)['ticket']['id']
        second_ticket = game.state(second)['ticket']['id']
        self.assertEqual(
            SpinTicket.objects.get(pk=first_ticket).release_id,
            SpinTicket.objects.get(pk=second_ticket).release_id,
        )
        completed = threading.Event()
        responses, errors = [], []

        def play_other_session():
            try:
                # A regressed shared-row lock fails promptly instead of leaving
                # a test connection blocked during teardown.
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '2s'")
                    cursor.execute("SET statement_timeout = '5s'")
                player = PlayerSession.objects.get(pk=second.pk)
                responses.append(game.spin(player, '1', second_ticket, uuid.uuid4()))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()
                completed.set()

        thread = threading.Thread(target=play_other_session, daemon=True)
        try:
            with transaction.atomic():
                SpinTicket.objects.select_for_update().get(pk=first_ticket)
                # NO KEY UPDATE permits FK references from a successful round,
                # but conflicts with an accidental FOR UPDATE on the Release
                # joined by the unrelated ticket's claim.
                Release.objects.select_for_update(no_key=True).get(pk=self.baseline.pk)
                ActiveRelease.objects.select_for_update().get(pk=1)
                thread.start()
                self.assertTrue(completed.wait(8), 'Unrelated Spin waited on shared rows')
                self.assertEqual(errors, [])
                self.assertEqual(len(responses), 1)
                # These assertions run while all three locks above remain held.
                self.assertEqual(Round.objects.filter(session=second).count(), 1)
                self.assertEqual(LedgerEntry.objects.filter(session=second, kind='round').count(), 1)
                self.assertFalse(Round.objects.filter(session=first).exists())
                self.assertEqual(SpinTicket.objects.get(pk=first_ticket).status, 'ready')
        finally:
            if thread.ident is not None:
                thread.join(8)
        self.assertFalse(thread.is_alive())
        second.refresh_from_db()
        self.assertEqual(second.spins, 1)
        self.assertEqual(responses[0]['round_release_id'], str(self.baseline.pk))

    def test_simultaneous_identical_preview_creation_returns_one_release(self):
        """Two editors arriving at the same content produce one immutable release."""
        config = baseline_config()
        expected = digest({'config': config, 'engine': ENGINE_HASH, 'preview': True})
        before_versions = ConfigurationVersion.objects.count()
        insert_gate = threading.Barrier(2)
        ids, errors = [], []

        def create_preview(name):
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '8s'")
                insert_prefix = 'INSERT INTO ' + connection.ops.quote_name(Release._meta.db_table)
                waited = False

                def synchronize_insert(execute, sql, params, many, context):
                    nonlocal waited
                    # Synchronize the observable DB race, not ORM method calls
                    # or mocked query results: both requests saw no such row and
                    # now attempt the same unique content hash concurrently.
                    if not waited and sql.lstrip().startswith(insert_prefix):
                        waited = True
                        insert_gate.wait(timeout=10)
                    return execute(sql, params, many, context)

                with connection.execute_wrapper(synchronize_insert):
                    release = make_release(deepcopy(config), name, preview=True)
                ids.append(release.pk)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=create_preview, args=(name,), daemon=True)
                   for name in ('Editor one preview', 'Editor two preview')]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(15)
        finally:
            insert_gate.abort()
            for thread in threads:
                if thread.is_alive():
                    thread.join(8)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Release.objects.filter(preview=True).count(), 1)
        saved = Release.objects.get(pk=ids[0])
        self.assertEqual(saved.digest, expected)
        self.assertEqual(saved.config, config)
        self.assertEqual(ConfigurationVersion.objects.count(), before_versions)
        self.assertEqual(ActiveRelease.objects.get(pk=1).release_id, self.baseline.pk)


class WorkerTakeoverTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('worker-recovery-fixture')
        original_hash = sha256(b'original fixture bytes').hexdigest()
        self.original = Asset.objects.create(
            name='original.png', kind='tile', status='pending',
            object_key=f'objects/{original_hash[:2]}/{original_hash}.bin',
            sha256=original_hash, byte_size=22, created_by=self.user,
        )
        self.job = Job.objects.create(
            kind='ingest', created_by=self.user,
            request={'asset_id': str(self.original.pk), 'recipe': {}},
        )

    def fields(self, label):
        content_hash = sha256(label.encode()).hexdigest()
        return {
            'name':label+'.png', 'kind':'tile', 'status':'ready',
            'object_key':f'objects/{content_hash[:2]}/{content_hash}.png',
            'sha256':content_hash, 'byte_size':len(label), 'mime':'image/png',
            'metadata':{'width':218, 'height':327, 'result':label},
            'original':self.original, 'is_derivative':True, 'created_by':self.user,
        }

    def take_over(self, old):
        Job.objects.filter(pk=old.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        current = jobs.claim()
        self.assertIsNotNone(current)
        self.assertEqual(current.pk, old.pk)
        self.assertEqual(current.fence, old.fence+1)
        return current

    def test_late_ingest_error_preserves_recovered_original_and_derivative(self):
        """An old decoder failure cannot turn a recovered, ready asset into Failed."""
        winner_ids = []

        def interrupted_media(old):
            current = self.take_over(old)
            result = {'recovered':True}
            jobs.finish(
                current, result, asset_fields=self.fields('recovered-output'),
                original_fields=(self.original.pk, {
                    'status':'ready', 'mime':'image/png', 'metadata':{'verified':'recovery'},
                }),
            )
            winner_ids.append(result['asset_id'])
            # This arrives after the replacement worker committed successfully.
            raise ValueError('Old decoder failed after recovery finished')

        with patch('game_studio.jobs._media', side_effect=interrupted_media):
            self.assertTrue(jobs.run_one())
        self.job.refresh_from_db()
        self.original.refresh_from_db()
        self.assertEqual(self.job.fence, 2)
        self.assertEqual(self.job.status, 'succeeded')
        self.assertEqual(self.job.error, '')
        self.assertIsNone(self.job.lease_until)
        self.assertEqual(self.original.status, 'ready')
        self.assertEqual(self.original.metadata, {'verified':'recovery'})
        self.assertEqual(self.original.mime, 'image/png')
        self.assertEqual(Asset.objects.filter(is_derivative=True).count(), 1)
        self.assertEqual(self.job.result['asset_id'], winner_ids[0])
        self.assertEqual(Asset.objects.get(pk=winner_ids[0]).metadata['result'], 'recovered-output')

    def test_stale_finish_cannot_create_assets_before_or_after_recovered_finish(self):
        """Lost ownership prohibits both a derivative insert and original mutation."""
        old = jobs.claim()
        current = self.take_over(old)
        stale_fields = self.fields('stale-output')
        stale_original = (self.original.pk, {'status':'ready', 'metadata':{'verified':'stale'}})

        jobs.finish(old, {'stale':True}, asset_fields=stale_fields, original_fields=stale_original)
        self.job.refresh_from_db()
        self.original.refresh_from_db()
        self.assertEqual(self.job.status, 'running')
        self.assertEqual(self.job.fence, current.fence)
        self.assertEqual(self.job.result, {})
        self.assertEqual(self.original.status, 'pending')
        self.assertEqual(self.original.metadata, {})
        self.assertEqual(Asset.objects.filter(is_derivative=True).count(), 0)

        winner = {'recovered':True}
        jobs.finish(
            current, winner, asset_fields=self.fields('current-output'),
            original_fields=(self.original.pk, {'status':'ready', 'metadata':{'verified':'current'}}),
        )
        jobs.finish(old, {'stale':True}, asset_fields=stale_fields, original_fields=stale_original)
        self.job.refresh_from_db()
        self.original.refresh_from_db()
        self.assertEqual(self.job.status, 'succeeded')
        self.assertEqual(self.job.result, winner)
        self.assertEqual(self.original.metadata, {'verified':'current'})
        self.assertEqual(Asset.objects.filter(is_derivative=True).count(), 1)
        self.assertFalse(Asset.objects.filter(sha256=stale_fields['sha256']).exists())
        self.assertFalse(Asset.objects.filter(published=True).exists())
