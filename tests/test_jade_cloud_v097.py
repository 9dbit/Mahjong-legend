"""Approved mobile jade cloud must remain transparent, symmetric and unwarped."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

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
        self.assertIn("approved-cloud-v097.svg",css)
        self.assertIn("reel-endcap-v097.svg",css)
        self.assertIn("background-size:contain",css)
        self.assertIn("transform:scaleX(-1)",css)
        self.assertIn("410*cloudScale",geometry)
        self.assertIn("192*cloudScale",geometry)
        self.assertIn("(shorterGutter+bleed)/192",geometry)

    def test_all_scored_reels_spin_starting_at_top_and_bottom_closes(self):
        css=CSS.read_text()
        compiler=(ROOT/'tools/build_studio_runtime.py').read_text()
        self.assertIn(".game-stage .board .reel.short::before",css)
        self.assertIn("content:none!important",css)
        self.assertIn(".game-stage .board .reel.short::after",css)
        self.assertIn("top:calc(100% + 2px)",css)
        self.assertNotIn("e.style.setProperty('--corner-cap-image'",compiler)
        self.assertIn('Unexpected reel builder; review first-row animation',compiler)
        self.assertEqual((ROOT/'web/assets/reel-v083/reels.js').read_text().count("signal('start', c.i + 1)"),1)


if __name__=='__main__':
    unittest.main()
