"""Actor history uses bounded lookup while active-ticket guards remain intact."""
import json
import sqlite3
import time

import pytest
from fastapi import Request
import agency_runtime as native


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'native.sqlite'
    for key in ('RAILWAY_PROJECT_ID', 'RAILWAY_SERVICE_ID', 'RAILWAY_DEPLOYMENT_ID',
                'RAILWAY_VOLUME_MOUNT_PATH', 'ENGINE_RESTORE_OBJECT_KEY', 'ENGINE_RESTORE_OBJECT'):
        monkeypatch.delenv(key, raising=False)
    for key, value in {'AGENCY_WALLET_MODE': 'sandbox', 'AGENCY_ENVIRONMENT': 'preproduction',
                       'AGENCY_DEPLOYMENT_ID': 'mahjong-history-test',
                       'AGENCY_CORE_DEPLOYMENT_ID': 'core-history-test',
                       'MAHJONG_AGENCY_DB_PATH': str(path), 'AGENCY_STUDIO_SYNC': '0',
                       'ENGINE_BACKUP_ENABLED': 'false'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(native, 'wallet', lambda: object())
    def remote(action, payload):
        assert action == 'status', 'History reads must not mutate a wallet'
        return {'balance': '1000000', 'reserved': '0'}
    monkeypatch.setattr(native, 'remote', remote)
    native.init(); db = native.connect()
    session = {'tenant_id': 'history-test', 'player_id': 'returning', 'session_id': 'returning-session',
               'coin_scale': 0, 'game': 'mahjong-wild', 'provider': 'soft-tech',
               'environment': 'preproduction', 'deployment_id': 'core-history-test'}
    cookie = 'b' * 64
    db.execute('INSERT INTO launches VALUES(?,?,?,?,?)',
               ('synthetic-token', 'synthetic-redemption', native.hashtext(cookie), json.dumps(session), time.time()))
    request = Request({'type': 'http', 'method': 'GET', 'path': '/api/last-round',
                       'headers': [(b'cookie', (native.COOKIE + '=' + cookie).encode())]})
    config = json.dumps(native.studio.active_config())
    seed = '13' * 32
    outcome = json.dumps(native.play_round(seed, native.GameConfig(json.loads(config)['math'])))
    yield db, session, request, config, seed, outcome
    db.close()


def insert_ticket(db, rid, actor, config, seed, outcome, *, state='settled', created_at=1, request_id=None):
    db.execute('''INSERT INTO tickets
        (id,actor,seed,config_json,engine_hash,state,request_id,outcome_json,created_at,finished_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)''',
        (rid, actor, seed, config, native.ENGINE_HASH, state, request_id, outcome,
         created_at, created_at + 1 if state == 'settled' else None))


def explain(db, sql):
    return [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + sql)]


def test_returning_actor_history_and_active_plan_with_growing_unrelated_rows(database, monkeypatch):
    db, session, request, config, seed, outcome = database
    actor = 'history-test:returning'
    db.execute('BEGIN IMMEDIATE')
    for i in range(20):
        insert_ticket(db, 'owned-' + str(i), actor, config, seed, outcome, created_at=100 + i)
    insert_ticket(db, 'ready-owned', actor, config, seed, None, state='ready', created_at=time.time())
    insert_ticket(db, 'failed-owned', actor, config, seed, None, state='failed', created_at=time.time())
    db.commit()
    statements = []
    db.set_trace_callback(statements.append)
    original_connect = native.connect
    def observed_connect(**kwargs):
        connection = original_connect(**kwargs); connection.set_trace_callback(statements.append); return connection
    monkeypatch.setattr(native, 'connect', observed_connect)
    prior_state, prior_last, previous = None, None, 0
    for history in (1000, 10000):
        db.execute('BEGIN IMMEDIATE')
        for i in range(previous, history):
            # Unrelated rows never enter renderer/math code in this query fixture.
            insert_ticket(db, 'unrelated-' + str(i), 'other:' + str(i % 300), '{}', seed, '{}', created_at=i)
        db.commit(); previous = history; statements.clear()
        state = native.state(db, session, actor)
        last = native.dispatch(request, 'last-round', {})
        assert state['spin_count'] == 20 and state['ticket']['sequence'] == 21
        assert state['ticket']['id'] == 'ready-owned' and state['ticket']['status'] == 'ready'
        assert last['ticket_id'] == 'owned-19'
        if prior_state is not None:
            assert state == prior_state and last == prior_last
        prior_state, prior_last = state, last
        actual = {name: next(sql for sql in statements if 'FROM tickets WHERE actor=' in sql and token in sql)
                  for name, token in (('active', "state IN ('ready','pending','reserved')"),
                                      ('last', 'ORDER BY finished_at DESC LIMIT 1'),
                                      ('history', 'ORDER BY finished_at DESC LIMIT 100'), ('count', 'count(*)'))}
        for name, sql in actual.items():
            plan = explain(db, sql)
            expected_index = 'one_open' if name == 'active' else 'tickets_settled_history'
            assert any('SEARCH tickets' in step and expected_index in step for step in plan), plan
            assert not any('SCAN tickets' in step or 'TEMP B-TREE' in step for step in plan), plan
            if name == 'count':
                assert any('COVERING INDEX' in step for step in plan), plan
            reference = sql.replace('FROM tickets', 'FROM tickets NOT INDEXED')
            assert [tuple(row) for row in db.execute(sql)] == [tuple(row) for row in db.execute(reference)]
        assert [row['id'] for row in db.execute(actual['history'])] == ['owned-' + str(i) for i in range(19, -1, -1)]


@pytest.mark.parametrize('state,blocks_next', [('ready', True), ('pending', True), ('reserved', True),
                                              ('settled', False), ('failed', False), ('expired', False)])
def test_unique_active_ticket_guard_is_preserved(database, state, blocks_next):
    db, _, _, config, seed, outcome = database
    insert_ticket(db, 'prior', 'guard:actor', config, seed, outcome, state=state)
    if blocks_next:
        with pytest.raises(sqlite3.IntegrityError):
            insert_ticket(db, 'next', 'guard:actor', config, seed, None, state='ready')
    else:
        insert_ticket(db, 'next', 'guard:actor', config, seed, None, state='ready')


def test_request_once_guard_remains_actor_scoped(database):
    db, _, _, config, seed, outcome = database
    insert_ticket(db, 'one', 'guard:actor', config, seed, outcome, request_id='same-request')
    with pytest.raises(sqlite3.IntegrityError):
        insert_ticket(db, 'duplicate', 'guard:actor', config, seed, outcome, request_id='same-request')
    insert_ticket(db, 'other-actor', 'guard:other', config, seed, outcome, request_id='same-request')


def test_existing_database_adds_history_index_without_changing_data_or_identity(database):
    db, _, _, config, seed, outcome = database
    insert_ticket(db, 'saved-outcome', 'history-test:returning', config, seed, outcome, request_id='saved-request')
    db.execute('DROP INDEX tickets_settled_history')
    before = list(db.iterdump())
    identity = db.execute('SELECT * FROM native_deployment_identity').fetchall()
    guards = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()
    native.init()
    assert [line for line in db.iterdump() if not line.startswith('CREATE INDEX tickets_settled_history')] == before
    assert db.execute('SELECT * FROM native_deployment_identity').fetchall() == identity
    assert db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall() == guards
    assert db.execute('PRAGMA synchronous').fetchone()[0] == 2
    assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='tickets_settled_history'").fetchone()[0] == 1
    native.init()
    assert [line for line in db.iterdump() if not line.startswith('CREATE INDEX tickets_settled_history')] == before
