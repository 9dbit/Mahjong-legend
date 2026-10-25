"""Presentation-only change: exact face ratio, preserved art, immediate input."""
from pathlib import Path
import hashlib,json,unittest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/portrait-v085'
class PortraitUI(unittest.TestCase):
    def test_all_tiles_exact_two_to_three(self):
        for key in 'ABCDEFGHIJKLMNOWS':
            for state in ('normal','gold'):
                with Image.open(OUT/f'tiles/{key}-{state}.webp') as im:
                    self.assertEqual(im.size,(218,327));self.assertEqual(im.mode,'RGBA')
    def test_fixed_header_and_footer_artwork_preserved(self):
        source=Image.open(ROOT/'web/assets/approved-v082/frame.webp').convert('RGB')
        result=Image.open(OUT/'frame.webp').convert('RGB')
        self.assertEqual(result.size,(864,1859))
        self.assertEqual(result.crop((0,0,864,650)).tobytes(),source.crop((0,0,864,650)).tobytes())
        self.assertEqual(result.crop((0,1243,864,1859)).tobytes(),source.crop((0,920,864,1536)).tobytes())
    def test_manifest_checksums(self):
        m=json.loads((OUT/'manifest.json').read_text())
        self.assertEqual(m['tile_ratio'],[2,3]);self.assertEqual(m['math_version'],'0.8.0')
        for name,digest in m['files'].items():self.assertEqual(hashlib.sha256((OUT/name).read_bytes()).hexdigest(),digest)
    def test_input_does_not_draw_or_retry_outcomes(self):
        s=(OUT/'game.js').read_text()
        self.assertLess(s.index("window.MahjongReels.beginInput({root:$('board'),turbo"),s.index("accepted=await req('/api/spin'"))
        self.assertEqual(s.count("req('/api/spin'"),1)
        self.assertIn('await verifySeed(accepted.round,commitment)',s)
        self.assertIn('suppressSpinClickUntil',s)
    def test_runtime_and_splash_in_document(self):
        html=(ROOT/'web/index.html').read_text()
        for asset in ('game.js','reels.js','portrait.css'):
            self.assertIn('portrait-v085/'+asset,html)
        self.assertIn('soft-tech-continue',html)
        self.assertIn('data-release="0.8.5"',html)
if __name__=='__main__':unittest.main()
