"""Server-only Soft Tech agency wallet transport for FastAPI/Django adapters.
Persist request IDs, round references and server outcomes before requests. A timeout
has unknown outcome: retry the identical business request or query status. Never
credit a local wallet as a fallback and never send this secret to the browser.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import secrets
import ssl
import threading
import time
import urllib.parse
import urllib3

REQUEST_TIMEOUT_SECONDS = 12.0
MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_IN_FLIGHT = 40
_TRANSPORT_LOCK = threading.Lock()
_TRANSPORT = None


class AgencyWalletError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


class _SharedTransport:
    """Per-process TLS pool; request auth remains entirely per call.

    The global semaphore includes background recovery callbacks and prevents
    more active transports than the native HTTP worker capacity. Pool wait uses
    the same twelve-second budget rather than adding another network deadline.
    """
    def __init__(self):
        self.pid = os.getpid()
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = True
        self.ssl_context.verify_mode = ssl.CERT_REQUIRED
        self.pool = urllib3.PoolManager(num_pools=4, maxsize=MAX_IN_FLIGHT, block=True,
                                        retries=False, ssl_context=self.ssl_context,
                                        cert_reqs=ssl.CERT_REQUIRED)
        self.slots = threading.BoundedSemaphore(MAX_IN_FLIGHT)
        self.lock = threading.Lock()
        self.stats = {'requests':0,'failures':0,'in_flight':0,'peak_in_flight':0,
                      'pool_wait_seconds_total':0.0,'http_seconds_total':0.0,
                      'max_pool_wait_seconds':0.0,'max_http_seconds':0.0}

    def post(self, url, body, headers):
        started = time.monotonic(); deadline = started + REQUEST_TIMEOUT_SECONDS
        with self.lock: self.stats['requests'] += 1
        acquired = self.slots.acquire(timeout=REQUEST_TIMEOUT_SECONDS)
        admitted = time.monotonic(); wait = admitted - started
        with self.lock:
            self.stats['pool_wait_seconds_total'] += wait
            self.stats['max_pool_wait_seconds'] = max(self.stats['max_pool_wait_seconds'], wait)
            if acquired:
                self.stats['in_flight'] += 1
                self.stats['peak_in_flight'] = max(self.stats['peak_in_flight'], self.stats['in_flight'])
            else: self.stats['failures'] += 1
        if not acquired: raise TimeoutError('Agency connection pool wait timed out')
        response = None; drained = False; failed = True
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError('Agency request timed out before connection')
            # A transport permit reserves capacity in every origin's 40-slot
            # pool. Never add a second wait or retry a signed financial POST.
            response = self.pool.urlopen('POST', url, body=body, headers=headers,
                retries=False, redirect=False, pool_timeout=0,
                timeout=urllib3.Timeout(total=remaining, connect=remaining, read=remaining),
                preload_content=False, decode_content=False, enforce_content_length=True)
            declared = response.headers.get('Content-Length')
            if declared is not None and (not declared.isdigit() or int(declared) > MAX_RESPONSE_BYTES):
                raise AgencyWalletError(502, 'AGENCY_RESPONSE_TOO_LARGE')
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise AgencyWalletError(502, 'AGENCY_RESPONSE_ENCODING_UNSUPPORTED')
            data = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError('Agency response deadline exceeded')
                connection = response.connection
                if connection is not None and connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read(min(65536, MAX_RESPONSE_BYTES + 1 - len(data)), decode_content=False)
                if not chunk:
                    drained = True; break
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES: raise AgencyWalletError(502, 'AGENCY_RESPONSE_TOO_LARGE')
            if not 200 <= response.status < 300:
                raise AgencyWalletError(response.status, 'AGENCY_REQUEST_REJECTED')
            value = json.loads(data)
            if not isinstance(value, dict): raise ValueError('Agency response must be a JSON object')
            failed = False
            return value
        finally:
            try:
                if response is not None:
                    # A partial/error stream is discarded; a drained stream can
                    # be reused without another caller inheriting response data.
                    try:
                        if not drained: response.close()
                    finally:
                        response.release_conn()
            finally:
                elapsed = time.monotonic() - admitted
                with self.lock:
                    self.stats['in_flight'] -= 1
                    self.stats['failures'] += int(failed)
                    self.stats['http_seconds_total'] += elapsed
                    self.stats['max_http_seconds'] = max(self.stats['max_http_seconds'], elapsed)
                self.slots.release()

    def metrics(self):
        with self.lock:
            return {'pool_limit':MAX_IN_FLIGHT,'origin_pool_limit':4,
                    **{key:round(value,6) if isinstance(value,float) else value for key,value in self.stats.items()}}


def shared_transport():
    global _TRANSPORT
    with _TRANSPORT_LOCK:
        if _TRANSPORT is None or _TRANSPORT.pid != os.getpid():
            if _TRANSPORT is not None: _TRANSPORT.pool.clear()
            _TRANSPORT = _SharedTransport()
        return _TRANSPORT


def close_transport():
    """Close idle sockets at process shutdown or between isolated fixtures."""
    global _TRANSPORT
    with _TRANSPORT_LOCK:
        if _TRANSPORT is not None: _TRANSPORT.pool.clear()
        _TRANSPORT = None


def transport_metrics():
    with _TRANSPORT_LOCK:
        return _TRANSPORT.metrics() if _TRANSPORT is not None else {'pool_limit':MAX_IN_FLIGHT,'origin_pool_limit':4,'requests':0,'in_flight':0}


class AgencyWallet:
    def __init__(self, origin: str, key_id: str, secret: str, *, allow_local=False, environment=None, audience=None):
        url = urllib.parse.urlsplit(origin)
        local = allow_local and url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1')
        if not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment or not (url.scheme == 'https' or local):
            raise ValueError('Agency wallet origin must be HTTPS')
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError('Invalid agency wallet port')
        if not key_id or len(secret) < 32:
            raise ValueError('Agency wallet credentials required')
        self.environment = environment or os.getenv('AGENCY_ENVIRONMENT', 'sandbox')
        self.audience = audience or os.getenv('AGENCY_CORE_DEPLOYMENT_ID', '')
        if self.environment not in ('sandbox', 'preproduction', 'production'):
            raise ValueError('Invalid agency environment')
        if self.environment != 'sandbox' and not self.audience:
            raise ValueError('Explicit agency audience required')
        if self.audience and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{7,127}', self.audience):
            raise ValueError('Invalid agency audience')
        self.origin, self.key_id, self.secret = origin.rstrip('/'), key_id, secret.encode()
        self.transport = shared_transport()

    def request(self, action: str, payload: dict) -> dict:
        if self.environment == 'production':
            raise AgencyWalletError(423, 'PRODUCTION_RELEASE_GATES_PENDING')
        if action not in ('redeem', 'status', 'reserve', 'settle', 'void'):
            raise ValueError('Unsupported agency action')
        if action == 'redeem' and not payload.get('request_id'):
            raise ValueError('Persisted redemption request ID required')
        path = '/api/v4/agency-game/' + action
        body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
        if len(body) > MAX_REQUEST_BYTES:
            raise AgencyWalletError(413, 'AGENCY_REQUEST_TOO_LARGE')
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        domain = ('agency.v2', self.environment, self.audience) if self.audience else ('agency.v1',)
        message = '\n'.join((*domain, 'POST', path, timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
        headers = {'Content-Type': 'application/json', 'Accept-Encoding':'identity', 'X-Agency-Key': self.key_id,
                   'X-Agency-Timestamp': timestamp, 'X-Agency-Nonce': nonce,
                   'X-Agency-Signature': hmac.new(self.secret, message, hashlib.sha256).hexdigest()}
        if self.audience:
            headers.update({'X-Agency-Version':'2', 'X-Agency-Environment':self.environment, 'X-Agency-Audience':self.audience})
        return self.transport.post(self.origin + path, body, headers)
