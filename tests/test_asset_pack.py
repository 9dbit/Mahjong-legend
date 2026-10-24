import json
import unittest
from pathlib import Path
from PIL import Image, ImageChops
ROOT=Path(__file__).resolve().parents[1]
M=json.loads((ROOT/'web/assets/asset_manifest.json').read_text())['assets']

class AssetTests(unittest.TestCase):
 def test_exact_symbols(self):
  for s in 'ABCDEFGHIJKLMNOWS':
   self.assertIn('tiles/tile_'+s,M)
   self.assertIn('symbols/symbol_'+s,M)
 def test_transparent_export(self):
  for key,v in M.items():
   f=ROOT/v['file'];self.assertTrue(f.is_file(),str(f))
   if f.suffix=='.webp' and v.get('transparent'):
    im=Image.open(f);self.assertIn(im.mode,('RGBA','LA'))
    a=im.getchannel('A');self.assertLess(a.getextrema()[0],255,key)
 def test_mirrored_dragons(self):
  a=Image.open(ROOT/M['ornaments/dragon_left']['file']).convert('RGBA')
  b=Image.open(ROOT/M['ornaments/dragon_right']['file']).convert('RGBA')
  self.assertFalse(ImageChops.difference(a.transpose(Image.Transpose.FLIP_LEFT_RIGHT),b).getbbox())
 def test_music_and_sfx(self):
  self.assertTrue((ROOT/'web/assets/audio/music/ambient_jade_loop.m4a').is_file())
  self.assertEqual(len(list((ROOT/'web/assets/audio/sfx').glob('*.wav'))),10)
if __name__=='__main__':unittest.main()