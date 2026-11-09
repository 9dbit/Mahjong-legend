"""Real local TLS transport regressions; synthetic certificates/receipts only."""
import hashlib
import hmac
import json
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import urllib3
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

import agency_wallet as wallet_module
from agency_wallet import AgencyWallet, AgencyWalletError, close_transport, transport_metrics

SECRET = 'synthetic-wallet-test-secret-' + 'q' * 32
KEY_ID = 'synthetic-engine-key'
AUDIENCE = 'core-tls-fixture'
TOKEN = 'synthetic-token-must-not-appear-in-transport-metrics'


def certificates(directory, name):
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Disposable ' + name)])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
              key_encipherment=False, data_encipherment=False, key_agreement=False,
              key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')]))
            .issuer_name(ca_name).public_key(server_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    ca_path, cert_path, key_path = [directory / (name + suffix) for suffix in ('.ca.pem', '.cert.pem', '.key.pem')]
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(server_key.private_bytes(serialization.Encoding.PEM,
                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    return ca_path, cert_path, key_path


class LocalTLS(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def __init__(self, cert, key):
        self.state = SimpleNamespace(lock=threading.Lock(), records=[], receipts={}, debits=0,
            active=0, peak_active=0, redirects=0, slow_entered=threading.Event(), slow_release=threading.Event())
        super().__init__(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.socket = context.wrap_socket(self.socket, server_side=True)
        self.origin = 'https://localhost:' + str(self.server_port)
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def handle_error(self, request, client_address):
        # Deliberate peer disconnects are test cases, not server log output.
        pass

    def stop(self):
        self.state.slow_release.set()
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=2)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def log_message(self, *args):
        pass

    def respond(self, code, value, **headers):
        body = value if isinstance(value, bytes) else json.dumps(value, separators=(',', ':')).encode()
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        for name, value in headers.items():
            self.send_header(name.replace('_', '-'), value)
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self):
        with self.server.state.lock:
            self.server.state.redirects += 1
        self.respond(200, {'redirected': True})

    def do_POST(self):
        state = self.server.state
        body = self.rfile.read(int(self.headers['Content-Length']))
        headers = {name.lower(): value for name, value in self.headers.items()}
        domain = ('agency.v2', headers['x-agency-environment'], headers['x-agency-audience']) if headers.get('x-agency-version') == '2' else ('agency.v1',)
        message = '\n'.join((*domain, 'POST', self.path, headers['x-agency-timestamp'], headers['x-agency-nonce'], hashlib.sha256(body).hexdigest())).encode()
        valid = headers['x-agency-key'] == KEY_ID and hmac.compare_digest(headers['x-agency-signature'], hmac.new(SECRET.encode(), message, 'sha256').hexdigest())
        payload = json.loads(body)
        with state.lock:
            state.records.append({'body': body, 'headers': headers, 'valid': valid, 'connection': self.client_address})
            state.active += 1
            state.peak_active = max(state.peak_active, state.active)
        try:
            if not valid:
                self.respond(401, {'error': 'bad fixture signature'})
                return
            mode = payload.get('fixture_mode')
            if mode == 'slow':
                state.slow_entered.set()
                state.slow_release.wait(timeout=5)
            if mode == 'parallel':
                time.sleep(0.15)
            if mode == 'disconnect':
                with state.lock:
                    fresh = payload['round_ref'] not in state.receipts
                    if fresh:
                        state.debits += 1
                        state.receipts[payload['round_ref']] = {'round_id': payload['round_ref'], 'applied': True, 'debit_count': state.debits}
                    receipt = state.receipts[payload['round_ref']]
                if fresh:
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.respond(200, receipt)
                return
            if mode == 'status':
                self.respond(payload['status'], {'error': 'fixture rejection'}, Location=self.server.origin + '/redirect-target')
                return
            if mode == 'invalid-json':
                self.respond(200, b'{invalid json')
                return
            if mode in ('drip-length', 'drip-chunked'):
                # Each byte arrives before the inactivity timeout; the complete
                # body deliberately takes much longer than the request budget.
                response_body = b'{"ok":true,"padding":"' + b'x' * 16 + b'"}'
                self.send_response(200)
                if mode == 'drip-length':
                    self.send_header('Content-Length', str(len(response_body)))
                else:
                    self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                for byte in response_body:
                    chunk = bytes([byte])
                    self.wfile.write(chunk if mode == 'drip-length' else b'1\r\n' + chunk + b'\r\n')
                    self.wfile.flush()
                    time.sleep(0.04)
                if mode == 'drip-chunked': self.wfile.write(b'0\r\n\r\n')
                return
            if mode == 'oversized':
                self.respond(200, b'x' * (1024 * 1024 + 1))
                return
            if mode == 'oversized-chunked':
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                for _ in range(17):
                    chunk = b'x' * 65536
                    self.wfile.write(b'10000\r\n' + chunk + b'\r\n')
                    self.wfile.flush()
                self.wfile.write(b'0\r\n\r\n')
                return
            self.respond(200, {'ok': True, 'player_id': payload.get('player_id')})
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True
        finally:
            with state.lock:
                state.active -= 1


@pytest.fixture
def tls(tmp_path, monkeypatch):
    close_transport()
    ca, cert, key = certificates(tmp_path, 'trusted')
    monkeypatch.setenv('SSL_CERT_FILE', str(ca))
    monkeypatch.delenv('AGENCY_CORE_DEPLOYMENT_ID', raising=False)
    servers = [LocalTLS(cert, key)]
    def make_server(name):
        _, other_cert, other_key = certificates(tmp_path, name)
        server = LocalTLS(other_cert, other_key)
        servers.append(server)
        return server
    def client(origin=None, **options):
        return AgencyWallet(origin or servers[0].origin, KEY_ID, SECRET,
                            environment=options.pop('environment', 'preproduction'),
                            audience=options.pop('audience', AUDIENCE), **options)
    try:
        yield SimpleNamespace(server=servers[0], client=client, untrusted_server=make_server)
    finally:
        close_transport()
        for server in servers:
            server.stop()


def test_fresh_clients_share_verified_tls_connection_but_fresh_v1_v2_auth(tls):
    with patch.object(wallet_module.ssl, 'create_default_context', wraps=ssl.create_default_context) as created:
        clients = [tls.client() for _ in range(6)]
        for client in clients:
            assert client.request('status', {'player_id': 'same-player', 'token': TOKEN})['ok']
        assert created.call_count == 1
    v1 = tls.client(environment='sandbox', audience='')
    assert v1.request('status', {'player_id': 'same-player'})['ok']
    assert all(client.transport is clients[0].transport for client in clients)
    assert clients[0].transport.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert clients[0].transport.ssl_context.check_hostname is True
    records = tls.server.state.records
    assert len(records) == 7 and all(record['valid'] for record in records)
    assert len({record['connection'] for record in records}) == 1
    assert len({record['headers']['x-agency-nonce'] for record in records}) == 7
    assert len({record['headers']['x-agency-signature'] for record in records}) == 7
    assert records[0]['headers']['x-agency-environment'] == 'preproduction'
    assert records[0]['headers']['x-agency-audience'] == AUDIENCE
    assert 'x-agency-version' not in records[-1]['headers']
    assert wallet_module.REQUEST_TIMEOUT_SECONDS == 12.0
    metrics = transport_metrics()
    assert metrics['pool_limit'] == 40 and metrics['origin_pool_limit'] == 4
    assert metrics['requests'] == 7 and metrics['in_flight'] == 0
    encoded = json.dumps(metrics)
    for private in (SECRET, KEY_ID, TOKEN, AUDIENCE, 'same-player', 'x-agency', tls.server.origin):
        assert private not in encoded


def test_wrong_hostname_and_untrusted_ca_are_rejected_before_http(tls):
    wrong_host = tls.server.origin.replace('localhost', '127.0.0.1')
    with pytest.raises(urllib3.exceptions.SSLError):
        tls.client(wrong_host).request('status', {})
    untrusted = tls.untrusted_server('untrusted')
    with pytest.raises(urllib3.exceptions.SSLError):
        tls.client(untrusted.origin).request('status', {})
    assert tls.server.state.records == [] and untrusted.state.records == []
    assert tls.client().request('status', {})['ok']
    assert transport_metrics()['in_flight'] == 0


@pytest.mark.parametrize('status', [302, 429, 500])
def test_http_failures_are_not_redirected_or_retried_and_next_call_is_clean(tls, status):
    client = tls.client()
    with pytest.raises(AgencyWalletError) as error:
        client.request('status', {'fixture_mode': 'status', 'status': status})
    assert error.value.status == status
    assert len(tls.server.state.records) == 1 and tls.server.state.redirects == 0
    assert client.request('status', {})['ok']
    assert len(tls.server.state.records) == 2 and transport_metrics()['in_flight'] == 0


def test_commit_disconnect_is_not_retried_and_caller_same_payload_converges_once(tls):
    payload = {'fixture_mode': 'disconnect', 'round_ref': 'durable-round-fixture', 'stake': '100'}
    client = tls.client()
    with pytest.raises(urllib3.exceptions.HTTPError):
        client.request('reserve', payload)
    assert len(tls.server.state.records) == 1 and tls.server.state.debits == 1
    receipt = tls.client().request('reserve', payload)
    assert receipt == {'round_id': payload['round_ref'], 'applied': True, 'debit_count': 1}
    assert tls.server.state.debits == 1
    a, b = tls.server.state.records
    assert a['body'] == b['body'] and a['headers']['x-agency-nonce'] != b['headers']['x-agency-nonce']
    assert a['headers']['x-agency-signature'] != b['headers']['x-agency-signature']


def test_slow_player_does_not_block_an_unrelated_player(tls):
    with ThreadPoolExecutor(max_workers=2) as executor:
        slow = executor.submit(tls.client().request, 'status', {'fixture_mode': 'slow', 'player_id': 'slow-player'})
        try:
            assert tls.server.state.slow_entered.wait(timeout=2)
            fast = executor.submit(tls.client().request, 'status', {'player_id': 'fast-player'})
            assert fast.result(timeout=2)['player_id'] == 'fast-player'
            assert not slow.done()
        finally:
            tls.server.state.slow_release.set()
        assert slow.result(timeout=2)['player_id'] == 'slow-player'


def test_sixty_concurrent_requests_are_bounded_to_forty_and_release_capacity(tls):
    barrier = threading.Barrier(61)
    def call(index):
        client = tls.client()
        barrier.wait(timeout=5)
        return client.request('status', {'fixture_mode': 'parallel', 'player_id': str(index)})
    with ThreadPoolExecutor(max_workers=60) as executor:
        futures = [executor.submit(call, index) for index in range(60)]
        barrier.wait(timeout=5)
        values = [future.result(timeout=12) for future in futures]
    assert {value['player_id'] for value in values} == {str(index) for index in range(60)}
    assert len(tls.server.state.records) == 60
    assert 2 <= tls.server.state.peak_active <= 40
    metrics = transport_metrics()
    assert metrics['requests'] == 60 and metrics['failures'] == 0
    assert metrics['in_flight'] == 0 and 2 <= metrics['peak_in_flight'] <= 40
    assert tls.client().request('status', {})['ok']


@pytest.mark.parametrize('mode', ['oversized', 'oversized-chunked', 'invalid-json'])
def test_oversized_and_invalid_responses_cannot_poison_reused_pool(tls, mode):
    with pytest.raises((AgencyWalletError, ValueError)):
        tls.client().request('status', {'fixture_mode': mode})
    assert tls.client().request('status', {'player_id': 'after-bad-response'})['ok']
    assert transport_metrics()['in_flight'] == 0


def test_request_byte_cap_and_production_lock_reject_before_any_http(tls):
    assert wallet_module.MAX_REQUEST_BYTES == 65536 and wallet_module.MAX_RESPONSE_BYTES == 1024 * 1024
    client = tls.client()
    overhead = len(json.dumps({'padding': ''}, separators=(',', ':')).encode())
    with pytest.raises(AgencyWalletError) as oversized:
        client.request('status', {'padding': 'x' * (65536 - overhead + 1)})
    assert oversized.value.status == 413 and tls.server.state.records == []
    with pytest.raises(AgencyWalletError) as locked:
        tls.client(environment='production').request('status', {'token': TOKEN})
    assert locked.value.status == 423 and tls.server.state.records == []
    assert transport_metrics()['requests'] == 0
    assert client.request('status', {'padding': 'x' * (65536 - overhead)})['ok']
    assert len(tls.server.state.records[0]['body']) == 65536


@pytest.mark.parametrize('mode', ['drip-length', 'drip-chunked'])
def test_slow_drip_body_respects_total_budget_without_retry_or_pool_leak(tls, monkeypatch, mode):
    assert wallet_module.REQUEST_TIMEOUT_SECONDS == 12.0
    # Scale only this isolated fixture budget; production remains twelve seconds.
    monkeypatch.setattr(wallet_module, 'REQUEST_TIMEOUT_SECONDS', 0.15)
    client = tls.client()
    started = time.monotonic()
    with pytest.raises((TimeoutError, urllib3.exceptions.HTTPError)):
        client.request('status', {'fixture_mode': mode})
    elapsed = time.monotonic() - started
    assert 0.10 <= elapsed < 0.60, {'mode': mode, 'elapsed_seconds': elapsed}
    assert len(tls.server.state.records) == 1
    assert transport_metrics()['in_flight'] == 0
    assert transport_metrics()['failures'] == 1
    # A partial TLS body must not contaminate the next explicit request.
    assert client.request('status', {})['ok']
    assert len(tls.server.state.records) == 2
    assert transport_metrics()['in_flight'] == 0
    print(json.dumps({'scenario': mode, 'fixture_budget_seconds': 0.15, 'elapsed_seconds': round(elapsed, 6), 'production_timeout_seconds': 12.0, 'automatic_retries': 0}))
