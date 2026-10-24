"""The rotating disk must cover the baked arrow at its original coordinates."""
from pathlib import Path
import unittest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'web/assets/locked-v08'

class SpinDiscAlignment(unittest.TestCase):
    def test_approved_disk_pixels_and_complete_crop(self):
        with Image.open(ASSETS/'frame.webp') as f,Image.open(ASSETS/'spin-disc.webp') as d:
            self.assertEqual(d.size,(150,150));self.assertEqual(d.mode,'RGBA')
            reference=f.convert('RGB').crop((301,1106,451,1256))
            self.assertEqual(d.getchannel('A').getextrema(),(0,255))
            for y in range(0,150,5):
                for x in range(0,150,5):
                    r,g,b,a=d.getpixel((x,y))
                    if a:self.assertEqual((r,g,b),reference.getpixel((x,y)))
    def test_css_matches_native_source_location(self):
        css=(ASSETS/'polish.css').read_text()
        self.assertIn('left:18.83312%;top:8.543889%;width:62.33378%',css)
        # Compare CSS percentages to the native reference's 752x1338 geometry.
        x=.34*752+.1883312*.32*752
        y=.815*1338+.08543889*.95*.143*1338
        width=.6233378*.32*752
        self.assertAlmostEqual(x,301,places=3);self.assertAlmostEqual(y,1106,places=3);self.assertAlmostEqual(width,150,places=3)

if __name__=='__main__':unittest.main()
