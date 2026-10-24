"""Verify shipping audio is decodable, non-silent, bounded and loopable."""
from array import array
from pathlib import Path
import hashlib
import json
import math
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'web/assets/audio/oriental-v082'


class OrientalAudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ASSETS / 'manifest.json').read_text())

    def test_required_events_have_valid_non_silent_audio(self):
        names = {'button', 'spin', 'reel_roll', 'reel_stop', 'crack', 'tile_break',
                 'cascade', 'wild', 'multiplier', 'scatter', 'win', 'bonus', 'bigwin',
                 'jade_garden_loop'}
        self.assertEqual(set(self.manifest['assets']), names)
        for name, entry in self.manifest['assets'].items():
            with self.subTest(name=name):
                path = ASSETS / (name + '.wav')
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry['sha256'])
                with wave.open(str(path), 'rb') as wav:
                    self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 22050))
                    samples = array('h', wav.readframes(wav.getnframes()))
                rms = math.sqrt(sum(v*v for v in samples) / len(samples)) / 32768
                self.assertGreater(rms, .005)
                self.assertLess(max(abs(v) for v in samples), 32000)
                if name not in ('jade_garden_loop', 'reel_roll'):
                    self.assertEqual(samples[-1], 0, 'Transient tail must fade to zero')

    def test_music_is_soft_original_seamless_and_mobile_sized(self):
        entry = self.manifest['assets']['jade_garden_loop']
        self.assertTrue(self.manifest['original'])
        self.assertEqual(self.manifest['music']['bpm'], 68)
        self.assertGreater(entry['duration'], 28)
        self.assertLess(entry['duration'], 29)
        self.assertLess(entry['bytes'], 1_300_000)
        self.assertGreater(entry['rms'], .04)
        self.assertLess(entry['rms'], .12)
        with wave.open(str(ASSETS / 'jade_garden_loop.wav'), 'rb') as wav:
            samples = array('h', wav.readframes(wav.getnframes()))
        self.assertLess(abs(samples[-1]-samples[0])/32768, .01)


if __name__ == '__main__':
    unittest.main()
