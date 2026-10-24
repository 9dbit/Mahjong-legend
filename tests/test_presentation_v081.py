"""UI-only update: preserve engine bytes and test aligned light assets."""
from pathlib import Path
import hashlib, json, unittest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
A=ROOT/'web/assets/locked-v08'
class Presentation081(unittest.TestCase):
    def test_math_source_unchanged(self):
        for p,expected in [('mahjong_legend/engine.py','a40246c005a4680c18951542d2b817ec6b03d203'),('mahjong_legend/math_config.json','664f9bcfe6cf8a224d4b78830ec42f07ff1472ef')]:
            b=(ROOT/p).read_bytes();self.assertEqual(hashlib.sha1(f'blob {len(b)}\0'.encode()+b).hexdigest(),expected)
    def test_transparent_masks_have_same_alpha(self):
        with Image.open(A/'effects/logo-emission.webp') as a, Image.open(A/'effects/logo-mask.webp') as b:
            self.assertEqual(a.size,(310,129));self.assertEqual(a.mode,'RGBA');self.assertEqual(a.getchannel('A').tobytes(),b.getchannel('A').tobytes());self.assertEqual(a.getchannel('A').getextrema(),(0,255))
    def test_mask_pixels_are_approved_logo_pixels(self):
        with Image.open(A/'frame.webp') as f,Image.open(A/'effects/logo-emission.webp') as e:
            ref=f.convert('RGB').crop((222,60,532,189));pixels=e.convert('RGBA')
            for y in range(0,129,3):
                for x in range(0,310,3):
                    r,g,b,a=pixels.getpixel((x,y))
                    if a:self.assertEqual((r,g,b),ref.getpixel((x,y)))
    def test_supplemental_manifest(self):
        manifest=json.loads((A/'presentation-manifest.json').read_text());self.assertEqual(manifest['version'],'0.8.1');self.assertEqual(len(manifest['files']),2)
        for p,m in manifest['files'].items():self.assertEqual(hashlib.sha256((A/p).read_bytes()).hexdigest(),m['sha256'])
    def test_ui_and_math_versions_are_distinct(self):
        r=json.loads((A/'release.json').read_text());self.assertEqual(r['release'],'0.8.1');self.assertEqual(r['math_version'],'0.8.0');self.assertTrue(r['virtual_credits_only'])
        h=(ROOT/'web/index.html').read_text();self.assertEqual(h.count('class="logo-fx"'),1);self.assertIn('v0.8.3',h);self.assertIn('polish.css',h)
if __name__=='__main__':unittest.main()
