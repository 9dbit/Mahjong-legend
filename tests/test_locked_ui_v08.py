"""Current x5 ladder tests plus locked-art build checks. No production seed override."""
from pathlib import Path
import copy, hashlib, json, unittest
from decimal import Decimal
from PIL import Image
from mahjong_legend.engine import GameConfig, play_round, verify_round

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'web/assets/locked-v08'

class LockedMath(unittest.TestCase):
    def setUp(self):self.cfg=GameConfig()
    def test_user_approved_ladder(self):
        self.assertEqual(self.cfg.base_mult,(1,2,3,5))
        self.assertEqual(self.cfg.bonus_mult,(2,3,5,8))
        self.assertEqual(self.cfg.raw['version'],'0.8.0')
    def test_fourth_base_cascade_is_five(self):
        r=play_round(f'{148:064x}',self.cfg)
        steps=[e for e in r['events'] if e['type']=='cascade' and e['phase']=='base']
        self.assertGreaterEqual(len(steps),4)
        self.assertEqual([e['multiplier'] for e in steps[:4]],[1,2,3,5])
        self.assertTrue(all(e['multiplier']==5 for e in steps[3:]))
    def test_delta_vs_legacy_ladder_is_exact(self):
        old=GameConfig({**self.cfg.raw,'base_multipliers':[1,2,3,4]})
        now=play_round(f'{148:064x}',self.cfg);before=play_round(f'{148:064x}',old)
        self.assertFalse(now['capped']);self.assertFalse(before['capped'])
        extra=sum((Decimal(e['raw_payout_x'])*self.cfg.base_scale for e in now['events'] if e['type']=='cascade' and e['phase']=='base' and e['step']>=4),Decimal(0))
        self.assertEqual(Decimal(now['total_payout_x'])-Decimal(before['total_payout_x']),extra)
    def test_new_rules_have_new_hash_and_reject_old_replay(self):
        old=GameConfig({**self.cfg.raw,'base_multipliers':[1,2,3,4]})
        self.assertNotEqual(old.digest,self.cfg.digest)
        self.assertFalse(verify_round(play_round(f'{148:064x}',old),self.cfg)['valid'])
    def test_replays_and_caps_across_bonus_and_base(self):
        for i in [2,4,148,311,357]+list(range(800,850)):
            r=play_round(f'{i:064x}',self.cfg)
            self.assertTrue(verify_round(r,self.cfg)['valid'])
            paid=sum((Decimal(e['awarded_x']) for e in r['events'] if e['type']=='cascade'),Decimal(0))
            self.assertEqual(paid,Decimal(r['total_payout_x']))
            self.assertLessEqual(paid,self.cfg.cap)
    def test_bonus_ladder_unchanged(self):
        r=play_round(f'{357:064x}',self.cfg)
        self.assertGreater(r['free_spins_played'],0)
        for e in r['events']:
            if e['type']=='cascade' and e['phase']=='bonus':self.assertEqual(e['multiplier'],[2,3,5,8][min(e['step']-1,3)])

class LockedArtwork(unittest.TestCase):
    def test_all_distinct_regular_symbols_have_both_states(self):
        hashes=[]
        for s in 'ABCDEFGHIJKLMNO':
            for state in ['normal','gold']:
                with Image.open(ASSETS/f'tiles/{s}-{state}.webp') as im:
                    self.assertEqual(im.size,(218,232));self.assertEqual(im.mode,'RGBA')
            hashes.append(hashlib.sha256((ASSETS/f'tiles/{s}-normal.webp').read_bytes()).hexdigest())
        self.assertEqual(len(set(hashes)),15)
    def test_manifest_checksums(self):
        manifest=json.loads((ASSETS/'manifest.json').read_text())
        self.assertEqual(len(manifest['files']),62)
        for path,entry in manifest['files'].items():
            self.assertEqual(hashlib.sha256((ASSETS/path).read_bytes()).hexdigest(),entry['sha256'])
    def test_break_layers_transparent(self):
        for p in (ASSETS/'effects').glob('*.webp'):
            with Image.open(p) as im:
                self.assertEqual(im.convert('RGBA').getchannel('A').getextrema()[0],0)
    def test_index_uses_actual_runtime_and_no_legacy_skin(self):
        html=(ROOT/'web/index.html').read_text()
        self.assertIn('locked-v08/game.js',html);self.assertIn('locked-v08/game.css',html)
        self.assertNotIn('mahjong-wild.css?v=06',html)
        self.assertIn('id="effects-layer"',html)
        self.assertRegex(html,r'x1\s*[·/]\s*x2\s*[·/]\s*x3\s*[·/]\s*x5')
    def test_release_does_not_claim_old_rtp(self):
        release=json.loads((ASSETS/'release.json').read_text())
        self.assertEqual(release['rtp_status'],'not_revalidated_after_base_multiplier_change')
        self.assertTrue(release['virtual_credits_only'])

if __name__=='__main__':unittest.main()
