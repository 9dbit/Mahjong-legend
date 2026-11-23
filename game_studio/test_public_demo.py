"""Public demo embedding without widening Studio or game API access."""
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import urljoin, urlsplit
import uuid

from django.test import Client, SimpleTestCase, TestCase, override_settings

from .releases import bootstrap


RUNTIME_ORIGIN = 'https://mahjong.xd-play.com'


def content(response):
    try:
        return b''.join(response.streaming_content) if response.streaming else response.content
    finally:
        response.close()


def policy(response):
    return dict(directive.strip().split(' ', 1)
                for directive in response['Content-Security-Policy'].split(';')
                if directive.strip())


class DocumentAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        url = attrs.get('src') if tag in ('script', 'img') else attrs.get('href') if tag == 'link' else None
        if url:
            self.urls.append(url)


@override_settings(ALLOWED_HOSTS=['mahjong.xd-play.com', 'testserver'])
class PublicDemoDocumentTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='mahjong.xd-play.com')

    def test_demo_reuses_approved_root_document_and_only_changes_ancestor_policy(self):
        root = self.client.get('/', secure=True)
        demo = self.client.get('/play/?gamelang=en&cur=USD', secure=True)
        self.assertEqual(root.status_code, 200)
        self.assertEqual(demo.status_code, 200)
        self.assertEqual(content(demo), content(root))
        self.assertEqual(demo['Content-Type'], 'text/html')
        self.assertNotIn('X-Frame-Options', demo)
        self.assertEqual(root['X-Frame-Options'], 'DENY')
        demo_policy, root_policy = policy(demo), policy(root)
        self.assertEqual(demo_policy.pop('frame-ancestors'), 'https://xd-play.com')
        self.assertEqual(root_policy.pop('frame-ancestors'), "'none'")
        self.assertEqual(demo_policy, root_policy)
        self.assertFalse(demo.cookies)
        self.assertNotIn('Access-Control-Allow-Origin', demo)

    def test_demo_asset_urls_resolve_at_runtime_root_and_are_served(self):
        parser = DocumentAssets()
        parser.feed(content(self.client.get('/play/', secure=True)).decode())
        self.assertTrue(parser.urls)
        for url in parser.urls:
            with self.subTest(url=url):
                self.assertTrue(url.startswith('/') and not url.startswith('//'))
                resolved = urlsplit(urljoin(RUNTIME_ORIGIN + '/play/', url))
                self.assertEqual(resolved.scheme + '://' + resolved.netloc, RUNTIME_ORIGIN)
                response = self.client.get(url, secure=True)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(content(response))
        worker = self.client.get('/sw.js', secure=True)
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker['Service-Worker-Allowed'], '/')
        content(worker)

    def test_embedding_exception_does_not_cover_root_admin_api_or_lookalike_paths(self):
        for path in ('/', '/index.html', '/admin/', '/api/studio/assets',
                     '/play', '/play//', '/play/admin/', '/play/index.html',
                     '/PLAY/', '/assets/approved-v082/pwa.js'):
            with self.subTest(path=path):
                response = self.client.get(path, secure=True)
                self.assertEqual(response['X-Frame-Options'], 'DENY')
                self.assertEqual(policy(response)['frame-ancestors'], "'none'")
                content(response)
        self.assertEqual(self.client.get('/api/studio/assets', secure=True).status_code, 401)

    def test_successful_studio_page_and_signed_preview_keep_existing_policies(self):
        # A built Studio shell must remain protected even when its route is 200.
        with tempfile.TemporaryDirectory() as directory:
            web = Path(directory)
            (web / 'studio').mkdir()
            (web / 'studio/index.html').write_text('<!doctype html><title>Studio fixture</title>')
            with patch('game_studio.views.WEB', web):
                response = self.client.get('/studio/', secure=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['X-Frame-Options'], 'DENY')
                self.assertEqual(policy(response)['frame-ancestors'], "'none'")
                content(response)
        preview = self.client.get('/studio/preview/invalid-token', secure=True)
        self.assertEqual(preview.status_code, 403)
        self.assertEqual(preview['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(policy(preview)['frame-ancestors'], "'self'")

    def test_demo_error_response_is_not_embeddable(self):
        response = self.client.post('/play/', {}, secure=True)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(policy(response)['frame-ancestors'], "'none'")
        with tempfile.TemporaryDirectory() as directory, patch('game_studio.views.WEB', Path(directory)):
            missing = self.client.get('/play/', secure=True)
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing['X-Frame-Options'], 'DENY')
            self.assertEqual(policy(missing)['frame-ancestors'], "'none'")


@override_settings(ALLOWED_HOSTS=['mahjong.xd-play.com', 'testserver'], PRODUCTION=True)
class PublicDemoApiTests(TestCase):
    def setUp(self):
        bootstrap()
        self.client = Client(HTTP_HOST='mahjong.xd-play.com')

    def test_embedded_game_keeps_same_origin_api_and_existing_session_contract(self):
        content(self.client.get('/play/', secure=True))
        state = self.client.get('/api/state', secure=True)
        self.assertEqual(state.status_code, 200)
        cookie = state.cookies['MLGAME']
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(cookie['domain'], '')
        self.assertEqual(cookie['path'], '/')
        data = {'bet': '1', 'ticket_id': state.json()['ticket']['id'],
                'idempotency_key': str(uuid.uuid4())}
        headers = {'HTTP_X_ML_REQUEST': 'local-demo',
                   'HTTP_REFERER': RUNTIME_ORIGIN + '/play/'}
        # The parent may embed the document, but cannot become its API origin.
        denied = self.client.post('/api/spin', json.dumps(data), content_type='application/json',
                                  secure=True, HTTP_ORIGIN='https://xd-play.com',
                                  HTTP_SEC_FETCH_SITE='same-site', **headers)
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn('Access-Control-Allow-Origin', denied)
        accepted = self.client.post('/api/spin', json.dumps(data), content_type='application/json',
                                    secure=True, HTTP_ORIGIN=RUNTIME_ORIGIN,
                                    HTTP_SEC_FETCH_SITE='same-origin', **headers)
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertEqual(accepted.json()['state']['spin_count'], 1)
        self.assertEqual(accepted['X-Frame-Options'], 'DENY')
        content(self.client.get('/', secure=True))
        root_state = self.client.get('/api/state', secure=True)
        self.assertEqual(root_state.json()['spin_count'], 1)
        self.assertFalse(root_state.cookies)
