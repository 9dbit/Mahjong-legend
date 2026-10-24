import copy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import threading
import unittest
from urllib import request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mahjong_legend.engine import (
    GameConfig, initial_board, evaluate, cascade, play_round, verify_round,
    analytic_bonus_trigger_probability, sha256, free_spins_for_scatters,
)
from mahjong_legend.server import make_server, DemoSession

OLD = Path(__file__).resolve().parents[1] / 'research' / 'tile_cascade_math.py'

class MathEngineV03Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = GameConfig()

    def test_identity_configuration(self):
        self.assertEqual(self.cfg.raw['project'], 'Mahjong Legend')
        self.assertEqual(self.cfg.raw['version'], '0.3.0')
        self.assertEqual(math.prod(self.cfg.heights), 2000)
        self.assertEqual(self.cfg.cap, Decimal('1000'))

    def test_probabilities_and_symbol_pool(self):
        self.assertEqual(len(self.cfg.pool), 100)
        self.assertAlmostEqual(analytic_bonus_trigger_probability(self.cfg), .0045252608, places=10)
        self.assertEqual(free_spins_for_scatters(2,self.cfg),0)
        self.assertEqual(free_spins_for_scatters(3,self.cfg),8)
        self.assertEqual(free_spins_for_scatters(4,self.cfg),10)
        self.assertEqual(free_spins_for_scatters(5,self.cfg),12)

    def test_seed_commitment_and_deterministic_replay(self):
        seed='b4'*32
        a=play_round(seed,self.cfg)
        b=play_round(seed,self.cfg)
        self.assertEqual(a,b)
        self.assertEqual(a['seed_commitment_sha256'],sha256(bytes.fromhex(seed)))
        self.assertEqual(a['events_sha256'],sha256(json.dumps(a['events'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf8')))
        self.assertTrue(verify_round(a,self.cfg)['valid'])

    def test_independent_round_seeds(self):
        a=play_round('01'*32,self.cfg)
        b=play_round('02'*32,self.cfg)
        self.assertNotEqual(a['events_sha256'],b['events_sha256'])

    def test_invalid_seed(self):
        for seed in ('not hex', '', 'A'*64, 'f'*62):
            with self.assertRaises(ValueError):
                play_round(seed,self.cfg)

    def test_verify_rejects_payout_modification(self):
        round=play_round('cd'*32,self.cfg)
        forged=copy.deepcopy(round)
        forged['total_payout_x']='999'
        self.assertFalse(verify_round(forged,self.cfg)['valid'])

    def test_verify_rejects_transcript_modification(self):
        round=play_round('aa'*32,self.cfg)
        forged=copy.deepcopy(round)
        forged['events'][0]['board'][0][0]['symbol']='O'
        self.assertFalse(verify_round(forged,self.cfg)['valid'])
        forged['events_sha256']=sha256(json.dumps(forged['events'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf8'))
        self.assertFalse(verify_round(forged,self.cfg)['valid'])

    def test_verify_rejects_rule_changes(self):
        record=play_round('ae'*32,self.cfg)
        modified=copy.deepcopy(self.cfg.raw)
        modified['max_round_payout_x']='500'
        self.assertFalse(verify_round(record,GameConfig(modified))['valid'])

    def test_payout_cap_forced(self):
        modified=copy.deepcopy(self.cfg.raw)
        modified['max_round_payout_x']='0.01'
        cfg=GameConfig(modified)
        # At least one tested seed must produce winning paths.
        capped=next(play_round(f'{i:064x}',cfg) for i in range(1,100)
                    if play_round(f'{i:064x}',cfg)['capped'])
        self.assertEqual(Decimal(capped['total_payout_x']),Decimal('0.01'))
        self.assertTrue(capped['capped'])
        self.assertEqual(sum(e['type']=='cap_reached' for e in capped['events']),1)
        self.assertTrue(verify_round(capped,cfg)['valid'])

    def test_cap_zero_payout_remains_zero(self):
        cfg=GameConfig({**self.cfg.raw, 'max_round_payout_x':'0.01'})
        self.assertTrue(all(Decimal(play_round(f'{i:064x}',cfg)['total_payout_x']) <= cfg.cap
                            for i in range(1,70)))

    def test_evaluation_example_left_anchored(self):
        board=[
            [{'symbol':'A','enhanced':False} for _ in range(2)] + [{'symbol':'B','enhanced':False} for _ in range(2)],
            [{'symbol':'A','enhanced':False} for _ in range(3)] + [{'symbol':'B','enhanced':False} for _ in range(2)],
            [{'symbol':'A','enhanced':False}] + [{'symbol':'C','enhanced':False} for _ in range(4)],
            [{'symbol':'C','enhanced':False} for _ in range(5)],
            [{'symbol':'E','enhanced':False} for _ in range(4)],
        ]
        payout,marks,groups=evaluate(board,self.cfg)
        self.assertEqual(payout,Decimal('0.27'))
        self.assertEqual(groups[0]['ways'],6)
        self.assertEqual(marks[0],{0,1})

    def test_reference_parity_200_seeded_rounds(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('tile_cascade_math',OLD)
        mod=importlib.util.module_from_spec(spec)
        sys.modules['tile_cascade_math']=mod
        spec.loader.exec_module(mod)
        # The original implementation and v0.3 must agree on both RNG sequence
        # and total payouts for ordinary uncapped rounds.
        for i in range(200):
            seed=100000+i
            rng=random.Random(seed)
            initial=mod.run_spin(rng,False,float(self.cfg.base_scale))
            total=initial.win
            pending=mod.scatter_bonus_spins(initial.scatters)
            bonus_count=0
            while pending:
                pending-=1
                bonus_count+=1
                free=mod.run_spin(rng,True,float(self.cfg.bonus_scale))
                total+=free.win
                pending+=mod.scatter_bonus_spins(free.scatters)
            current=play_round(f'{seed:064x}',self.cfg)
            self.assertAlmostEqual(float(current['total_payout_x']),total,places=8)
            self.assertEqual(current['free_spins_played'],bonus_count)

    def test_round_events_consistent(self):
        for i in range(20):
            round=play_round(f'{i+888:064x}',self.cfg)
            screens=[e for e in round['events'] if e['type']=='screen_start']
            self.assertEqual(len(screens),1+round['free_spins_played'])
            self.assertEqual(screens[0]['scatters'],round['base_scatters'])
            self.assertEqual(Decimal(round['base_payout_x'])+Decimal(round['bonus_payout_x']),Decimal(round['total_payout_x']))
            self.assertLessEqual(Decimal(round['total_payout_x']),self.cfg.cap)
            self.assertEqual(round['events'][-1]['type'],'round_end')
            self.assertTrue(all(len(e['board'][r])==self.cfg.heights[r] for e in screens for r in range(5)))


class WebAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session=DemoSession()
        cls.server=make_server(port=0, session=cls.session)
        cls.thread=threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    @classmethod
    def post(cls, path, data=None, headers=None):
        hdr={'Content-Type':'application/json','X-ML-Request':'local-demo'}
        if headers: hdr.update(headers)
        req=request.Request(cls.url+path, data=json.dumps(data or {}).encode('utf-8'),
                            method='POST', headers=hdr)
        with request.urlopen(req, timeout=5) as r:
            return r.status, json.load(r)

    def test_1_initial_commitment_and_spin(self):
        with request.urlopen(self.url+'/api/state') as r:
            state=json.load(r)
        self.assertEqual(state['game'],'Mahjong Wild')
        commit=state['next_seed_commitment_sha256']
        status,response=self.post('/api/spin')
        self.assertEqual(status,200)
        record=response['round']
        self.assertEqual(record['seed_commitment_sha256'],commit)
        self.assertTrue(verify_round(record)['valid'])
        self.assertNotEqual(response['state']['next_seed_commitment_sha256'],commit)

    def test_2_server_verify_endpoint(self):
        record=self.session.last_round
        _,response=self.post('/api/verify',{'round':record})
        self.assertTrue(response['valid'])

    def test_3_static_app_and_reset(self):
        with request.urlopen(self.url+'/') as r:
            self.assertEqual(r.status,200)
            self.assertIn(b'Mahjong Wild',r.read())
        _,state=self.post('/api/reset')
        self.assertEqual(Decimal(state['balance']),Decimal(1000))
        self.assertEqual(state['spin_count'],0)

if __name__ == '__main__':
    unittest.main()
