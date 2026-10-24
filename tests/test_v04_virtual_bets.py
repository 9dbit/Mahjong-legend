"""v0.4 virtual bet controls: proportional accounting, valid values, HTTP safety."""
import json
from decimal import Decimal
from pathlib import Path
import sys
import threading
import unittest
from urllib import request, error

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mahjong_legend.server import DemoSession, BET_OPTIONS, make_server
from mahjong_legend.engine import play_round, verify_round

class VirtualStakeTests(unittest.TestCase):
    def test_options_ordered_and_default_compatible(self):
        self.assertEqual(list(BET_OPTIONS),list(map(Decimal,['0.2','0.5','1','2','5','10'])))
        session=DemoSession();session.seed='12'*32
        result=session.spin()
        self.assertEqual(Decimal(result['stake_virtual_credits']),Decimal('1'))
        self.assertEqual(Decimal(result['state']['balance']),
                         Decimal('1000')-Decimal('1')+Decimal(result['round']['total_payout_x']))

    def test_virtual_credit_scaling_and_seed_replay(self):
        for bet in BET_OPTIONS:
            session=DemoSession();session.seed='32'*32
            precommit=session.state()['next_seed_commitment_sha256']
            data=session.spin(str(bet))
            amount=Decimal(data['round']['total_payout_x'])*bet
            self.assertEqual(Decimal(data['win_virtual_credits']),amount)
            self.assertEqual(Decimal(data['state']['balance']),Decimal('1000')-bet+amount)
            self.assertEqual(data['round']['seed_commitment_sha256'],precommit)
            self.assertEqual(data['round'],play_round('32'*32,session.cfg))
            self.assertTrue(verify_round(data['round'],session.cfg)['valid'])

    def test_invalid_bets_never_debit_or_consume_seed(self):
        invalid=[0.2,1,None if False else {},[],False,-1,'-1','0','0.3','11',
                 'NaN','Infinity','-Infinity','1e9999','hello','']
        session=DemoSession();before=session.state()
        for bad in invalid:
            with self.assertRaises(ValueError):session.spin(bad)
        after=session.state()
        self.assertEqual(before,after)

    def test_insufficient_balance_no_debit(self):
        session=DemoSession();session.credits=Decimal('0.1')
        before=session.state()
        with self.assertRaises(ValueError):session.spin('0.2')
        self.assertEqual(before,session.state())

class VirtualBetHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session=DemoSession();cls.server=make_server(port=0,session=cls.session)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start();cls.url=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.thread.join(timeout=3);cls.server.server_close()

    def post(self,payload):
        req=request.Request(self.url+'/api/spin',method='POST',
            data=json.dumps(payload).encode('utf8'),
            headers={'Content-Type':'application/json','X-ML-Request':'local-demo'})
        try:
            with request.urlopen(req,timeout=10) as resp:return resp.status,json.loads(resp.read())
        except error.HTTPError as exc:return exc.code,json.loads(exc.read())

    def test_real_http_spin_virtual_bet(self):
        status,body=self.post({'bet':'2'})
        self.assertEqual(status,200)
        self.assertEqual(Decimal(body['stake_virtual_credits']),Decimal('2'))
        self.assertTrue(verify_round(body['round'],self.session.cfg)['valid'])

    def test_rejects_invalid_http_values(self):
        previous=self.session.state()['spin_count']
        for val in ['999',10,{'value':'1'},'NaN']:
            code,body=self.post({'bet':val})
            self.assertEqual(code,400)
            self.assertIn('error',body)
        self.assertEqual(self.session.state()['spin_count'],previous)

    def test_home_route_shows_game_not_promo_page(self):
        with request.urlopen(self.url+'/',timeout=5) as resp:
            html=resp.read().decode('utf8')
        self.assertIn('class="game-stage"',html)
        self.assertNotIn('class="intro"',html)
        self.assertNotIn('class="info-area"',html)
        self.assertIn('id="spin-btn"',html)

if __name__=='__main__':unittest.main()
