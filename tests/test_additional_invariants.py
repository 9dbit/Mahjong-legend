import copy
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest
from urllib import request,error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mahjong_legend.engine import GameConfig, play_round, verify_round, evaluate, cascade
from mahjong_legend.server import make_server,DemoSession
import random
import threading

class EngineInvariants(unittest.TestCase):
    def setUp(self):
        self.cfg=GameConfig()

    def test_config_clone_prevents_external_mutation(self):
        raw=copy.deepcopy(self.cfg.raw)
        cfg=GameConfig(raw)
        original=cfg.digest
        raw['max_round_payout_x']='0.01'
        self.assertEqual(cfg.digest,original)
        self.assertEqual(cfg.cap,Decimal('1000'))

    def test_config_rejects_invalid_probability(self):
        raw=copy.deepcopy(self.cfg.raw)
        raw['scatter_probability_per_reel']=1.5
        with self.assertRaises(ValueError):
            GameConfig(raw)

    def test_cap_equal_min_of_uncapped_same_seed(self):
        raw=copy.deepcopy(self.cfg.raw)
        raw['max_round_payout_x']='1000000000'
        uncapped=GameConfig(raw)
        caps=[Decimal('.01'),Decimal('1'),Decimal('30'),Decimal('1000')]
        variants=[]
        for cap in caps:
            config=copy.deepcopy(self.cfg.raw)
            config['max_round_payout_x']=str(cap)
            variants.append(GameConfig(config))
        for i in range(60):
            seed=f'{8800+i:064x}'
            expected=Decimal(play_round(seed,uncapped)['total_payout_x'])
            for cap,config in zip(caps,variants):
                result=play_round(seed,config)
                self.assertEqual(Decimal(result['total_payout_x']),min(expected,cap))
                self.assertTrue(verify_round(result,config)['valid'])

    def test_enhanced_winners_transform_to_wild(self):
        cfg=self.cfg
        board=[[{'symbol':'A','enhanced':False} for _ in range(h)] for h in cfg.heights]
        board[1][0]['enhanced']=True
        board[2][1]['enhanced']=True
        raw,marked,groups=evaluate(board,cfg)
        self.assertGreater(raw,0)
        out=cascade(random.Random(16),board,marked,False,cfg)
        self.assertIn('W',[tile['symbol'] for tile in out[1]])
        self.assertIn('W',[tile['symbol'] for tile in out[2]])

    def test_total_is_sum_of_awarded_events(self):
        for i in range(100):
            result=play_round(f'{68000+i:064x}',self.cfg)
            event_sum=sum((Decimal(e['awarded_x']) for e in result['events'] if e['type']=='cascade'),Decimal(0))
            self.assertEqual(event_sum,Decimal(result['total_payout_x']))
            self.assertLessEqual(event_sum,self.cfg.cap)
            self.assertEqual(result['capped'],event_sum==self.cfg.cap)

class APIHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(port=0,session=DemoSession())
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=3)
        cls.server.server_close()

    def call(self,path,data='{}',headers=None):
        req=request.Request(self.url+path,method='POST',data=data.encode('utf8'),
                            headers=headers or {})
        try:
            with request.urlopen(req,timeout=4) as resp:
                return resp.status,resp.read()
        except error.HTTPError as exc:
            return exc.code,exc.read()

    def test_origin_rejected(self):
        status,_=self.call('/api/reset',headers={'Content-Type':'application/json',
              'X-ML-Request':'local-demo','Origin':'https://evil.example'})
        self.assertEqual(status,403)

    def test_requires_json_and_custom_header(self):
        status,_=self.call('/api/reset',headers={'Content-Type':'text/plain'})
        self.assertEqual(status,415)
        status,_=self.call('/api/reset',headers={'Content-Type':'application/json'})
        self.assertEqual(status,403)

    def test_limit_payload_size(self):
        status,_=self.call('/api/verify',data='{}',headers={'Content-Length':'1000001',
              'Content-Type':'application/json','X-ML-Request':'local-demo'})
        self.assertEqual(status,413)

    def test_get_static_files(self):
        for path,kind in [('/','text/html'),('/app.js','javascript'),('/style.css','text/css')]:
            with request.urlopen(self.url+path,timeout=4) as resp:
                self.assertIn(kind,resp.headers['Content-Type'])
                self.assertGreater(len(resp.read()),100)

if __name__=='__main__':unittest.main()
