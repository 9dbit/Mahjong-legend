"""Immutable native deployment identity and environment-bound protocol helpers.

This is a binding, not evidence that infrastructure was physically isolated.
Production stays quarantined until a separately reviewed release control exists.
"""
import hashlib, hmac, json, os, re, sqlite3, time, secrets
from pathlib import Path

PROCESS_BOOT_ID = secrets.token_hex(16)
PROCESS_STARTED = time.monotonic()

def runtime_health():
    return {'process_boot_id': PROCESS_BOOT_ID, 'uptime_seconds': int(time.monotonic() - PROCESS_STARTED)}


def requested_identity(game, path):
    environment = os.getenv('AGENCY_ENVIRONMENT', 'sandbox')
    if environment not in ('sandbox', 'preproduction', 'production'):
        raise RuntimeError('AGENCY_ENVIRONMENT invalid')
    deployment = os.getenv('AGENCY_DEPLOYMENT_ID')
    core = os.getenv('AGENCY_CORE_DEPLOYMENT_ID')
    if environment != 'sandbox' and (not deployment or not core):
        raise RuntimeError('Explicit native and core deployment IDs required')
    deployment = deployment or 'legacy-' + game
    core = core or 'legacy-sandbox-core'
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{7,127}', x) for x in (deployment, core)):
        raise RuntimeError('Invalid deployment identity')
    return {'environment': environment, 'deployment_id': deployment,
            'core_deployment_id': core, 'game_id': game, 'identity_version': 1}


def canonical_path(path):
    p = Path(path)
    if not p.is_absolute(): raise RuntimeError('Absolute persistent database path required')
    resolved = p.resolve()
    mount = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
    if mount and not resolved.is_relative_to(Path(mount).resolve()):
        raise RuntimeError('Native database escapes persistent volume')
    return str(resolved)


def _compare(db, identity):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_deployment_identity'").fetchone()
    if not exists:
        if identity['environment'] != 'sandbox' and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone():
            raise RuntimeError('UNBOUND_DATABASE_CANNOT_CHANGE_ENVIRONMENT')
        return False
    row = db.execute('SELECT identity_json FROM native_deployment_identity WHERE singleton=1').fetchone()
    if not row or json.loads(row[0]) != identity:
        raise RuntimeError('NATIVE_DEPLOYMENT_IDENTITY_MISMATCH')
    return True


def open_bound_database(path, game):
    path = canonical_path(path)
    identity = requested_identity(game, path)
    # Wrong-environment restore must fail before WAL/schema writes.
    if Path(path).exists():
        ro = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)
        try: _compare(ro, identity)
        finally: ro.close()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    os.chmod(path, 0o600)
    try:
        db.execute('BEGIN IMMEDIATE')
        if not _compare(db, identity):
            db.execute('CREATE TABLE native_deployment_identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity_json TEXT NOT NULL)')
            db.execute('INSERT INTO native_deployment_identity VALUES(1,?)', (json.dumps(identity, sort_keys=True, separators=(',', ':')),))
        db.executescript("""
        CREATE TRIGGER IF NOT EXISTS native_identity_update BEFORE UPDATE ON native_deployment_identity BEGIN SELECT RAISE(ABORT,'immutable native identity'); END;
        CREATE TRIGGER IF NOT EXISTS native_identity_delete BEFORE DELETE ON native_deployment_identity BEGIN SELECT RAISE(ABORT,'immutable native identity'); END;
        CREATE TRIGGER IF NOT EXISTS native_identity_insert BEFORE INSERT ON native_deployment_identity BEGIN SELECT RAISE(ABORT,'immutable native identity'); END;
        """)
        db.commit()
        db.row_factory = sqlite3.Row
        return db
    except Exception:
        db.close()
        raise


def public_identity(game, path):
    return {**requested_identity(game, path), 'identity_bound': True,
            'physical_isolation_verified': False,
            'play_enabled': os.getenv('AGENCY_ENVIRONMENT', 'sandbox') != 'production'}


def require_play():
    from fastapi import HTTPException
    if os.getenv('AGENCY_ENVIRONMENT', 'sandbox') == 'production':
        raise HTTPException(423, 'PRODUCTION_RELEASE_GATES_PENDING')


def validate_redeemed(session, game, path):
    identity = requested_identity(game, path)
    strict = identity['environment'] != 'sandbox' or bool(os.getenv('AGENCY_CORE_DEPLOYMENT_ID'))
    if strict and (session.get('environment') != identity['environment'] or
                   session.get('core_deployment_id', session.get('deployment_id')) != identity['core_deployment_id']):
        from fastapi import HTTPException
        raise HTTPException(409, 'CORE_DEPLOYMENT_IDENTITY_MISMATCH')


def cookie_value(token, game, path):
    identity = requested_identity(game, path)
    namespace = '\n'.join(('native.cookie.v2', identity['environment'], identity['deployment_id'], identity['core_deployment_id'], game, token))
    return hmac.new(os.environ['AGENCY_WALLET_SECRET'].encode(), namespace.encode(), 'sha256').hexdigest()
