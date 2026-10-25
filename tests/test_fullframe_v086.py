"""Full frame is a presentation change. Source tile art/outcome math stay intact."""
from pathlib import Path
import hashlib,json,unittest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/fullframe-v086'
class FullFrameUI(unittest.TestCase):
    def test_runtime_is_loaded(self):
        html=(ROOT/'web/index.html').read_text()
        for value in ['data-release="0.8.6"','fullframe-v086/layout.css','fullframe-v086/layout.js','soft-tech-continue']:
            self.assertIn(value,html)
        self.assertEqual(html.count('class="fullframe-art"'),1)
    def test_manifest_and_source_center_pixels(self):
        manifest=json.loads((OUT/'manifest.json').read_text())
        source=Image.open(ROOT/manifest['source']).convert('RGB')
        for name,digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((OUT/name).read_bytes()).hexdigest(),digest)
        for name in ['rail','hud','crown-center','controls-center','board-center']:
            with Image.open(OUT/f'{name}.webp') as im:
                self.assertEqual(im.convert('RGB').tobytes(),source.crop(tuple(manifest['slices'][name])).tobytes())
    def test_layout_cannot_issue_rounds(self):
        js=(OUT/'layout.js').read_text()
        for token in ['/api/spin','Math.random','balance=','fetch(']:self.assertNotIn(token,js)
        self.assertIn('visualViewport',js)
        self.assertIn('view.scale',js)
    def test_fullframe_css_does_not_restore_height_based_width_clamp(self):
        css=(OUT/'layout.css').read_text()
        self.assertIn('width:var(--ff-width,100vw)',css)
        self.assertIn('aspect-ratio:auto',css)
        self.assertIn('max-width:none',css)
        self.assertIn('aspect-ratio:1',css)
    def test_fullframe_release_and_cache(self):
        r=json.loads((OUT/'release.json').read_text())
        self.assertEqual((r['release'],r['math_version'],r['tile_ratio']),('0.8.6','0.8.0','2:3'))
        self.assertIn('presentation-086',(ROOT/'web/sw.js').read_text())
if __name__=='__main__':unittest.main()
