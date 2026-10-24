"""Public-hosting regression tests: session isolation and origin protections."""
import json
import threading
import unittest
from http import HTTPStatus
from http.client import HTTPConnection

from mahjong_legend.server import make_server


class PublicHostingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server('127.0.0.1', 0, public=True)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def get(self, path, cookie=None):
        conn=HTTPConnection('127.0.0.1', self.port, timeout=5)
        hdr={'Cookie':cookie} if cookie else {}
        conn.request('GET',path,headers=hdr)
        res=conn.getresponse()
        body=json.loads(res.read())
        status=res.status
        new_cookie=res.getheader('Set-Cookie')
        conn.close()
        return status, body, new_cookie

    def post(self, path, cookie, origin=None):
        conn=HTTPConnection('127.0.0.1', self.port, timeout=5)
        hdr={'Content-Type':'application/json','X-ML-Request':'local-demo','Cookie':cookie}
        if origin is not None:
            hdr['Origin']=origin
        conn.request('POST',path,body=json.dumps({'bet':'1'}),headers=hdr)
        res=conn.getresponse()
        status=res.status
        body=json.loads(res.read())
        conn.close()
        return status, body

    def test_1_health(self):
        status, data, cookie = self.get('/health')
        self.assertEqual(status, 200)
        self.assertTrue(data['ok'])
        self.assertIsNone(cookie)

    def test_2_independent_browser_balances(self):
        _, a, header_a=self.get('/api/state')
        _, b, header_b=self.get('/api/state')
        ca=header_a.split(';')[0]
        cb=header_b.split(';')[0]
        self.assertNotEqual(ca,cb)
        self.assertIn('HttpOnly',header_a)
        self.assertIn('Secure',header_a)
        origin=f'https://127.0.0.1:{self.port}'
        result, body=self.post('/api/spin',ca,origin)
        self.assertEqual(result,200)
        self.assertEqual(body['state']['spin_count'],1)
        _, a_after, _=self.get('/api/state',ca)
        _, b_after, _=self.get('/api/state',cb)
        self.assertEqual(a_after['spin_count'],1)
        self.assertEqual(b_after['spin_count'],0)
        self.assertEqual(b_after['balance'],b['balance'])
        self.assertNotEqual(a_after['next_seed_commitment_sha256'],b_after['next_seed_commitment_sha256'])

    def test_3_origin_required(self):
        _,state,cookie=self.get('/api/state')
        origin=f'https://127.0.0.1:{self.port}'
        status,_=self.post('/api/spin',cookie.split(';')[0])
        self.assertEqual(status,403)
        status,_=self.post('/api/spin',cookie.split(';')[0],'https://evil.example')
        self.assertEqual(status,403)
        status,_=self.post('/api/spin',cookie.split(';')[0],origin)
        self.assertEqual(status,200)

if __name__=='__main__':
    unittest.main()
