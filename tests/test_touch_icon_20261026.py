"""The new touch icon must match the user's supplied logo, not a stale seal.

This is an independent upgrade test. Never modify the locked v082 test source.
"""
from pathlib import Path
import hashlib
import json
import os
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/approved-v082'
EXPECTED='4a61e71616780fa891b4f37461bc1d171fdfcd453de124f9ee41494709a6ceac'


class ApprovedTouchIcon(unittest.TestCase):
    def test_user_icon_sha_dimensions_and_exact_generated_pixels(self):
        manifest=json.loads((OUT/'manifest.json').read_text())
        self.assertEqual(manifest['touch_icon_source'],
                         'web/assets/branding/mahjong-wild-touch-source.webp')
        source=ROOT/manifest['touch_icon_source']
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),EXPECTED)
        self.assertEqual(manifest['touch_icon_sha256'],EXPECTED)
        with Image.open(source) as original:
            self.assertEqual(original.size,(160,160))
            for n in (180,192,512):
                with self.subTest(n=n),Image.open(OUT/f'icon-{n}.png') as icon:
                    self.assertEqual(icon.size,(n,n))
                    self.assertEqual(icon.convert('RGB').tobytes(),
                        original.convert('RGB').resize((n,n),Image.Resampling.LANCZOS).tobytes())

    def test_final_runtime_and_studio_apple_touch_links(self):
        html=(ROOT/'web/index.html').read_text()
        studio=(ROOT/'studio_ui/index.html').read_text()
        self.assertIn('mahjong-gold-20261026',studio)
        self.assertIn('rel="icon" type="image/png"',studio)
        # The tests job runs BEFORE build_studio_runtime.py, while the Studio
        # job runs AFTER it. Validate the template/compile contract in the
        # former, then strictly validate the emitted HTML in the latter.
        compiled='apple-touch-icon" sizes="180x180"' in html
        if not compiled:
            self.assertNotEqual(os.getenv('MW_EXPECT_FINAL_ICON'), '1',
                'Final Studio build did not inject the approved iPhone icon')
            self.assertIn('<link rel="apple-touch-icon" href="/assets/approved-v082/icon-180.png">',html)
            compiler=(ROOT/'tools/build_studio_runtime.py').read_text()
            self.assertIn("source_touch=",compiler)
            self.assertIn('mahjong-gold-20261026',compiler)
            self.assertIn('html=html.replace(source_touch',compiler)
            self.assertIn('mahjong-wild-presentation-105',compiler)
        else:
            self.assertIn('mahjong-gold-20261026',html)
            self.assertIn('rel="icon" type="image/png"',html)
            self.assertIn("const CACHE='mahjong-wild-presentation-105'",
                          (ROOT/'web/sw.js').read_text())
        manifest=json.loads((ROOT/'web/manifest.webmanifest').read_text())
        self.assertEqual([entry['sizes'] for entry in manifest['icons']],['192x192','512x512'])


if __name__=='__main__':
    unittest.main()
