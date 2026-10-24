"""Mahjong Legend virtual-credit HTTP game server.

Local or explicit public mode; isolated ephemeral sessions, no real money.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from http.cookies import SimpleCookie
import os
import time
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

from .engine import GameConfig, display_decimal, play_round, verify_round, sha256

WEB = Path(__file__).resolve().parent.parent / 'web'
ROUTES = {'/': 'index.html', '/index.html': 'index.html',
          '/app.js': 'app.js', '/style.css': 'style.css'}
BET_OPTIONS = (Decimal('0.2'), Decimal('0.5'), Decimal('1'),
               Decimal('2'), Decimal('5'), Decimal('10'))


class DemoSession:
    def __init__(self, cfg: GameConfig | None = None):
        self.cfg = cfg or GameConfig()
        self.lock = threading.RLock()
        self.credits = self.cfg.initial_balance
        self.seed = secrets.token_hex(32)
        self.spins = 0
        self.last_round = None

    def state(self) -> dict:
        with self.lock:
            return {
                'game': 'Mahjong Legend', 'version': self.cfg.raw['version'],
                'balance': display_decimal(self.credits),
                'spin_price': display_decimal(self.cfg.spin_price),
                'bet_options': [display_decimal(x) for x in BET_OPTIONS],
                'max_payout_x': str(self.cfg.cap),
                'spin_count': self.spins,
                'next_seed_commitment_sha256': sha256(bytes.fromhex(self.seed)),
                'config_sha256': self.cfg.digest,
                'rules': {'grid': self.cfg.heights, 'ways': 2000,
                          'base_multipliers': self.cfg.base_mult,
                          'bonus_multipliers': self.cfg.bonus_mult,
                          'scatter_per_reel': self.cfg.scatter_prob,
                          'free_spins_for_3_scatters': self.cfg.raw['free_spins_for_3_scatters'],
                          'extra_free_spins': self.cfg.raw['extra_free_spins_per_additional_scatter'],
                          'paytable': self.cfg.raw['paytable'],
                          'symbols': self.cfg.raw['symbols']},
                'last_round_id': None if self.last_round is None else self.last_round['round_id'],
            }

    def spin(self, bet=None) -> dict:
        with self.lock:
            # Stake only scales virtual credits; it never modifies the math RNG
            # outcome or the verifiable payout multiple of this round.
            if bet is None:
                stake = self.cfg.spin_price
            elif isinstance(bet, str):
                try:
                    stake = Decimal(bet)
                except Exception as exc:
                    raise ValueError('Invalid virtual stake') from exc
            else:
                raise ValueError('Virtual stake must be an offered string denomination')
            if not stake.is_finite() or stake not in BET_OPTIONS:
                raise ValueError('Unsupported virtual stake')
            if self.credits < stake:
                raise ValueError('Not enough virtual credits. Use Reset Demo to restore them.')
            # Run the entire outcome first. A runtime safety error never debits credits.
            completed = play_round(self.seed, self.cfg)
            self.credits -= stake
            credit_win = stake * Decimal(completed['total_payout_x'])
            self.credits += credit_win
            self.seed = secrets.token_hex(32)
            self.spins += 1
            self.last_round = completed
            return {'round': completed, 'stake_virtual_credits': display_decimal(stake),
                    'win_virtual_credits': display_decimal(credit_win),
                    'state': self.state()}

    def reset(self) -> dict:
        with self.lock:
            self.credits = self.cfg.initial_balance
            self.seed = secrets.token_hex(32)
            self.spins = 0
            self.last_round = None
            return self.state()


class SessionStore:
    """Bounded per-browser in-memory virtual-credit game sessions (non-persistent)."""
    def __init__(self, cfg=None, max_sessions=2000, ttl_seconds=86400):
        self.cfg = cfg or GameConfig()
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self.lock = threading.RLock()
        self.items = OrderedDict()

    def obtain(self, token):
        now = time.monotonic()
        with self.lock:
            if token in self.items:
                session, last = self.items.pop(token)
                if now - last <= self.ttl_seconds:
                    self.items[token] = (session, now)
                    return session, token, False
            # Expire idle sessions before any new allocation.
            expired = [key for key, (_, last) in self.items.items()
                       if now - last > self.ttl_seconds]
            for key in expired:
                del self.items[key]
            while len(self.items) >= self.max_sessions:
                self.items.popitem(last=False)
            new_token = secrets.token_urlsafe(32)
            while new_token in self.items:
                new_token = secrets.token_urlsafe(32)
            session = DemoSession(self.cfg)
            self.items[new_token] = (session, now)
            return session, new_token, True


class DemoHandler(BaseHTTPRequestHandler):
    session: DemoSession
    sessions: SessionStore | None = None
    public_mode = False
    server_version = 'MahjongLegendDemo/0.5'

    def _session(self):
        if self.sessions is None:
            return self.session
        try:
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            token = cookie['MLSESSION'].value if 'MLSESSION' in cookie else None
        except Exception:
            token = None
        session, token, fresh = self.sessions.obtain(token)
        if fresh:
            self._fresh_token = token
        return session


    def _send(self, code: int, body: bytes, content_type='application/json; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        if getattr(self, '_fresh_token', None):
            secure = self.public_mode or self.headers.get('X-Forwarded-Proto') == 'https'
            parts = [f'MLSESSION={self._fresh_token}', 'Path=/',
                     'HttpOnly', 'SameSite=Lax', 'Max-Age=86400']
            if secure:
                parts.append('Secure')
            self.send_header('Set-Cookie', '; '.join(parts))
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; img-src 'self' data:; connect-src 'self'; "
                         "style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            return self._json(200, {'ok': True, 'game': 'Mahjong Legend', 'version': '0.5.0'})
        session = self._session()
        if path == '/api/state':
            return self._json(200, session.state())
        if path == '/api/last-round':
            if session.last_round is None:
                return self._json(404, {'error': 'No rounds yet'})
            return self._json(200, {'round': session.last_round})
        if path in ROUTES:
            file = WEB / ROUTES[path]
            body = file.read_bytes()
            content_type = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            if content_type.startswith('text/') or content_type == 'application/javascript':
                content_type += '; charset=utf-8'
            return self._send(200, body, content_type)
        self._json(404, {'error': 'Not found'})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ('/api/spin', '/api/reset', '/api/verify'):
            return self._json(404, {'error': 'Not found'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self._json(415, {'error': 'JSON content type required'})
        if self.headers.get('X-ML-Request') != 'local-demo':
            return self._json(403, {'error': 'Required demo header missing'})
        origin = self.headers.get('Origin')
        allowed_origins = (f'http://127.0.0.1:{self.server.server_port}',
                           f'http://localhost:{self.server.server_port}')
        if self.public_mode:
            host = self.headers.get('Host', '')
            if not host or any(c in host for c in '/\\@ ') or len(host) > 253:
                return self._json(403, {'error': 'Invalid host'})
            allowed_origins = (f'https://{host}',)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self._json(403, {'error': 'Cross-site operation rejected'})
            if not origin:
                return self._json(403, {'error': 'Origin header required'})
        if origin and origin not in allowed_origins:
            return self._json(403, {'error': 'Origin not allowed'})
        session = self._session()
        try:
            content_len = int(self.headers.get('Content-Length', '0'))
            if content_len < 0 or content_len > 1_000_000:
                return self._json(413, {'error': 'Request too large'})
            data = json.loads(self.rfile.read(content_len) or '{}')
            if not isinstance(data, dict):
                return self._json(400, {'error': 'Expected JSON object'})
            if path == '/api/spin':
                return self._json(200, session.spin(data.get('bet')))
            if path == '/api/reset':
                return self._json(200, session.reset())
            if path == '/api/verify':
                if not isinstance(data.get('round'), dict):
                    return self._json(400, {'error': 'Missing round object'})
                return self._json(200, verify_round(data['round'], session.cfg))
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {'error': str(exc)})
        except Exception as exc:
            self._json(500, {'error': f'Demo engine failure: {type(exc).__name__}'})

    def log_message(self, fmt, *args):
        # local server, avoid raw request logging
        return


def make_server(host='127.0.0.1', port=8765, session=None, public=False) -> ThreadingHTTPServer:
    if not public and host not in ('127.0.0.1', 'localhost'):
        raise ValueError('Binding outside localhost requires explicit public=True')
    class BoundHandler(DemoHandler):
        pass
    BoundHandler.session = session or DemoSession()
    BoundHandler.sessions = SessionStore() if public else None
    BoundHandler.public_mode = public
    server = ThreadingHTTPServer((host, port), BoundHandler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description='Run local Mahjong Legend demo')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8765')))
    parser.add_argument('--public', action='store_true',
                        help='Enable public HTTP hosting with isolated browser sessions')
    args = parser.parse_args()
    host = '0.0.0.0' if args.public else '127.0.0.1'
    server = make_server(host=host, port=args.port, public=args.public)
    print(f'Mahjong Legend listening on {host}:{server.server_port}', flush=True)
    print('All credits are virtual and reset on server restart.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
