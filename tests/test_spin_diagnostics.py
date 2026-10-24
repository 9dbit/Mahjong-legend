"""Anonymous, opt-in spin metrics must never become a gameplay write channel."""
import io
import json
import threading
import unittest
from contextlib import redirect_stdout
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from mahjong_legend.server import make_server


class SpinDiagnostics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def send(self, data, origin=None, header=True):
        headers = {'Content-Type': 'application/json', 'Origin': origin or self.base}
        if header: headers['X-ML-Request'] = 'local-demo'
        req = Request(self.base + '/api/diagnostics/spin', data=json.dumps(data).encode(), headers=headers, method='POST')
        with urlopen(req, timeout=5) as res:
            return res.status, json.load(res)

    def test_anonymous_metrics_accepted_without_creating_session(self):
        report = {'version': '0.8.4', 'starts': [1,2,3,4,5], 'stops': [1,2,3,4,5],
                  'durationMs': 2300, 'atlasPixels': 650000, 'completed': True,
                  'device': {'width': 390, 'height': 844, 'dpr': 1.5},
                  'seed_hex': 'DO_NOT_COLLECT', 'balance': 1000}
        output=io.StringIO()
        with redirect_stdout(output):
            status, data = self.send(report)
        self.assertEqual(status, 202)
        self.assertTrue(data['accepted'])
        line=output.getvalue()
        self.assertIn('MW_SPIN_DIAG ', line)
        self.assertNotIn('DO_NOT_COLLECT',line)
        self.assertNotIn('balance',line)
        self.assertNotIn('seed',line)
        self.assertEqual(json.loads(line.split('MW_SPIN_DIAG ',1)[1])['starts'],[1,2,3,4,5])

    def test_cross_origin_blocked(self):
        with self.assertRaises(HTTPError) as err:
            self.send({'starts':[1]}, origin='https://evil.invalid')
        self.assertEqual(err.exception.code, 403)

    def test_missing_demo_header_blocked(self):
        with self.assertRaises(HTTPError) as err:
            self.send({'starts':[1]}, header=False)
        self.assertEqual(err.exception.code, 403)

    def test_giant_payload_rejected(self):
        with self.assertRaises(HTTPError) as err:
            self.send({'errors':['X'*4500]})
        self.assertEqual(err.exception.code, 413)

if __name__=='__main__': unittest.main()
