"""Approved artwork presentation must never modify outcome math or session security."""
from pathlib import Path
import hashlib,json,unittest
from PIL import Image
from mahjong_legend.engine import GameConfig
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'web/assets/approved-v082'
class ApprovedUI(unittest.TestCase):
    def test_source_dimensions_and_digest(self):
        m=json.loads((OUT/'manifest.json').read_text());p=ROOT/m['source']
        with Image.open(p) as im:self.assertEqual(im.size,(864,1536))
        self.assertEqual(m['source_sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
    def test_all_runtime_checksums(self):
        m=json.loads((OUT/'manifest.json').read_text());self.assertGreaterEqual(len(m['files']),70)
        for path,item in m['files'].items():self.assertEqual(hashlib.sha256((OUT/path).read_bytes()).hexdigest(),item['sha256'],path)
    def test_all_symbols_remain_distinct_in_both_states(self):
        for state in ['normal','gold']:
            hashes=[]
            for symbol in 'ABCDEFGHIJKLMNO':
                p=OUT/f'tiles/{symbol}-{state}.webp'
                with Image.open(p) as im:self.assertEqual(im.size,(218,232));self.assertEqual(im.mode,'RGBA')
                hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(len(set(hashes)),15)
    def test_approved_logo_and_dragon_pixels_preserved(self):
        source=Image.open(ROOT/'web/assets/reference/approved_pwa_20261024.jpg').convert('RGB');frame=Image.open(OUT/'frame.webp').convert('RGB')
        for box in [(250,90,620,255),(30,180,115,290),(749,180,830,290),(20,700,108,810),(230,1420,630,1480)]:
            self.assertEqual(source.crop(box).tobytes(),frame.crop(box).tobytes(),box)
    def test_new_ui_is_loaded_not_a_static_screenshot(self):
        h=(ROOT/'web/index.html').read_text();self.assertIn('approved-v082/approved.css',h);self.assertIn('data-release="0.8.3"',h)
        s=(ROOT/'web/assets/locked-v08/game.js').read_text();self.assertIn("req('/api/spin'",s);self.assertIn("'/assets/approved-v082/'",s)
        self.assertIn('fragment-side',s);self.assertIn('await Promise.all(promises)',s)
    def test_pwa_is_standalone_and_no_outcome_cache(self):
        m=json.loads((ROOT/'web/manifest.webmanifest').read_text());self.assertEqual(m['display'],'standalone');self.assertEqual(m['scope'],'/')
        sw=(ROOT/'web/sw.js').read_text();self.assertIn("url.pathname.startsWith('/api/')",sw);self.assertIn("req.method!=='GET'",sw)
        html=(ROOT/'web/index.html').read_text();self.assertIn('viewport-fit=cover',html);self.assertIn('black-translucent',html)
        for icon in m['icons']:self.assertTrue((ROOT/'web'/icon['src'].lstrip('/')).exists())
    def test_music_is_original_local_and_gesture_unlocked(self):
        m=json.loads((OUT/'audio/music.json').read_text());self.assertGreater(m['seconds'],45);self.assertEqual(m['bpm'],76)
        s=(ROOT/'web/assets/locked-v08/audio.js').read_text();self.assertIn('jade_serenity.',s);self.assertIn("'pointerdown'",s);self.assertIn('unlockPending',s);self.assertIn('pauseMusic()',s)
    def test_math_version_and_ladders_are_unchanged(self):
        cfg=GameConfig();self.assertEqual(cfg.raw['version'],'0.8.0');self.assertEqual(cfg.base_mult,(1,2,3,5));self.assertEqual(cfg.bonus_mult,(2,3,5,8))
    def test_custom_reset_confirmation_and_all_menu_tabs(self):
        h=(ROOT/'web/index.html').read_text();self.assertIn('id="reset-dialog"',h)
        for name in ['rules','paytable','history','fairness','settings']:self.assertIn(f'data-panel="{name}"',h)
        self.assertIn('id="test-audio-btn"',h)
if __name__=='__main__':unittest.main()
