"""Server-only Soft Tech agency wallet transport for FastAPI/Django adapters.
Persist request IDs, round references and server outcomes before requests. A timeout
has unknown outcome: retry the identical business request or query status. Never
credit a local wallet as a fallback and never send this secret to the browser.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request


class AgencyWalletError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AgencyWallet:
    def __init__(self, origin: str, key_id: str, secret: str, *, allow_local=False):
        url = urllib.parse.urlsplit(origin)
        local = allow_local and url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1')
        if url.username or url.password or url.path not in ('', '/') or url.query or url.fragment or not (url.scheme == 'https' or local):
            raise ValueError('Agency wallet origin must be HTTPS')
        if not key_id or len(secret) < 32:
            raise ValueError('Agency wallet credentials required')
        self.origin, self.key_id, self.secret = origin.rstrip('/'), key_id, secret.encode()
        self.opener = urllib.request.build_opener(_NoRedirect())

    def request(self, action: str, payload: dict) -> dict:
        if action not in ('redeem', 'status', 'reserve', 'settle', 'void', 'studio-sync'):
            raise ValueError('Unsupported agency action')
        if action == 'redeem' and not payload.get('request_id'):
            raise ValueError('Persisted redemption request ID required')
        path = '/api/v4/agency-game/' + action
        body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        message = '\n'.join(('agency.v1', 'POST', path, timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
        headers = {'Content-Type': 'application/json', 'X-Agency-Key': self.key_id,
                   'X-Agency-Timestamp': timestamp, 'X-Agency-Nonce': nonce,
                   'X-Agency-Signature': hmac.new(self.secret, message, hashlib.sha256).hexdigest()}
        try:
            with self.opener.open(urllib.request.Request(self.origin + path, data=body, headers=headers, method='POST'), timeout=12) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise AgencyWalletError(exc.code, 'AGENCY_REQUEST_REJECTED') from None
