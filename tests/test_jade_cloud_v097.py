"""Approved mobile jade cloud must remain transparent, symmetric and unwarped."""
from pathlib import Path
import unittest
import hashlib
import xml.etree.ElementTree as ET
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'web/assets/ornaments'
CSS=ROOT/'web/assets/fullframe-v086/layout.css'
JS=ROOT/'web/assets/fullframe-v086/layout.js'


class JadeCloudPresentation(unittest.TestCase):
    def test_independent_assets_are_vector_and_ratio_locked(self):
        source=ET.parse(ART/'approved-cloud-v097.svg').getroot()
        self.assertEqual((int(source.attrib['width']),int(source.attrib['height'])),(192,410))
        self.assertEqual(source.attrib['viewBox'],'0 0 192 410')
        closing=ET.parse(ART/'reel-endcap-v097.svg').getroot()
        self.assertEqual((int(closing.attrib['width']),int(closing.attrib['height'])),(120,180))
        self.assertEqual(closing.attrib['viewBox'],'0 0 120 180')
        css=CSS.read_text()
        geometry=JS.read_text()
        self.assertIn("approved-cloud-cutout-v097.webp",css)
        image=ART/'approved-cloud-cutout-v097.webp'
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),
                         '87f3099d9593d53ae62fffb710b060c745c3044df1a6c4d7b856245caa4dcd2b')
        with Image.open(image) as cutout:
            self.assertEqual(cutout.size,(128,274))
            self.assertEqual(cutout.mode,'RGBA')
            self.assertEqual(cutout.getchannel('A').getextrema(),(0,255))
        self.assertTrue((ART/'reel-endcap-v097.svg').exists())  # retained for history
        self.assertIn("background-size:contain",css)
        self.assertIn("transform:scaleX(-1)",css)
        self.assertIn("410*cloudScale",geometry)
        self.assertIn("192*cloudScale",geometry)
        self.assertIn("(shorterGutter+bleed)/192",geometry)

    def test_standard_visual_corner_tiles_scroll_below_jade_without_scoring(self):
        css=CSS.read_text()
        compiler=(ROOT/'tools/build_studio_runtime.py').read_text()
        reels=(ROOT/'web/assets/reel-v083/reels.js').read_text()
        self.assertIn(".game-stage .board .reel.short::after",css)
        self.assertIn("grid-template-rows:repeat(5,minmax(0,1fr))!important",css)
        self.assertIn(".corner-visual-image",css)
        self.assertIn("jade-cloud-foreground--right",css)
        self.assertIn("clip-path:polygon(0 0,100% 0,0 100%)",css)
        self.assertIn("visualFiller:cornerTile",compiler)
        self.assertIn("ghost.dataset.scoring='false'",compiler)
        self.assertIn("querySelectorAll(':scope > .tile')",compiler)
        self.assertIn('jade-cloud-foreground--left',compiler)
        self.assertIn("compiled.write_text(reel_text)",compiler)
        self.assertIn("'corner-visual'));",compiler)
        self.assertIn(".corner-visual-image');",compiler)
        self.assertIn('layout.css?v=101',compiler)
        self.assertIn('presentation-101',compiler)
        self.assertIn("visibleCount:visual.length",compiler)
        self.assertIn("seq.visibleCount",compiler)
        self.assertNotIn("e.style.setProperty('--corner-cap-image'",compiler)
        self.assertEqual(reels.count("signal('start', c.i + 1)"),1)


if __name__=='__main__':
    unittest.main()
