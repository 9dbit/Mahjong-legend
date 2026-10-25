"""Media edits and storage integrity must hold without a Django installation."""
from array import array
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import wave

from PIL import Image

from game_studio.media import (AUDIO_RATE, MAX_IMAGE_BYTES, MediaError,
                               inspect_upload, process_audio, render_scene, render_tile)
from game_studio.storage import ContentStore, StorageError


def image_bytes(size=(120, 180), color=(210, 65, 20, 255), fmt="PNG"):
    target = BytesIO()
    Image.new("RGBA", size, color).save(target, format=fmt)
    return target.getvalue()


def audio_bytes(duration=0.25, channels=1, frequency=440, amplitude=0.25, rate=22050):
    output = BytesIO()
    samples = array("h")
    for frame in range(round(rate * duration)):
        value = round(amplitude * 32767 * math.sin(2 * math.pi * frequency * frame / rate))
        samples.extend([value] * channels)
    with wave.open(output, "wb") as source:
        source.setnchannels(channels)
        source.setsampwidth(2)
        source.setframerate(rate)
        source.writeframes(samples.tobytes())
    return output.getvalue()


class ImagePipelineTests(unittest.TestCase):
    def test_decode_decides_format_not_filename(self):
        source = image_bytes()
        metadata = inspect_upload(source, "not-really.jpg")
        self.assertEqual(metadata["mime"], "image/png")
        self.assertEqual(metadata["sha256"], sha256(source).hexdigest())
        self.assertEqual((metadata["width"], metadata["height"]), (120, 180))

    def test_rejects_damage_svg_animation_and_limits(self):
        for source in (b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"", b"PNG", image_bytes()[:30]):
            with self.subTest(source=source[:30]), self.assertRaises(MediaError):
                inspect_upload(source, "valid.png")
        with self.assertRaises(MediaError):
            inspect_upload(b"a" * (MAX_IMAGE_BYTES + 1), "huge.png")
        with self.assertRaises(MediaError):
            inspect_upload(image_bytes(size=(8193, 1)), "too-wide.png")
        output = BytesIO()
        Image.new("RGBA", (10, 10), "red").save(output, "PNG", save_all=True,
                                                    append_images=[Image.new("RGBA", (10, 10), "blue")])
        with self.assertRaises(MediaError):
            inspect_upload(output.getvalue(), "animated.png")

    def test_tile_contain_cover_anchor_and_transparency(self):
        source = image_bytes(size=(200, 50))
        contain = render_tile(source)
        cover = render_tile(source, {"fit": "cover"})
        with Image.open(BytesIO(contain)) as image:
            self.assertEqual(image.size, (218, 327))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((109, 0))[3], 0)
            self.assertEqual(image.getpixel((109, 163))[:3], (210, 65, 20))
        with Image.open(BytesIO(cover)) as image:
            self.assertEqual(image.getpixel((109, 0))[3], 255)
        self.assertEqual(contain, render_tile(source))
        self.assertEqual(source, image_bytes(size=(200, 50)))

    def test_glyph_body_and_recipe_validation(self):
        source = image_bytes(size=(20, 20), color=(220, 15, 15, 255))
        with Image.open(BytesIO(render_tile(source, {"mode": "glyph", "gold": True}))) as image:
            self.assertEqual(image.size, (218, 327))
            self.assertGreater(image.getpixel((109, 163))[0], 200)
            self.assertNotEqual(image.getpixel((109, 20)), image.getpixel((109, 163)))
        for edit in ({"zoom": float("nan")}, {"x": -1}, {"fit": "stretch"},
                     {"gold": "true"}, {"background": "url(secret)"}, {"unknown": 1}, {"zoom": True}):
            with self.subTest(edit=edit), self.assertRaises(MediaError):
                render_tile(source, edit)

    def test_extreme_aspect_cover_never_allocates_scaled_source(self):
        # A naive resize-to-cover would need an 11 GB intermediate here.
        source = image_bytes(size=(8192, 1))
        with Image.open(BytesIO(render_tile(source, {"fit": "cover", "zoom": 4}))) as image:
            self.assertEqual(image.size, (218, 327))
            self.assertEqual(image.getpixel((109, 163))[:3], (210, 65, 20))

    def test_scene_is_safe_reencoded_image(self):
        source = image_bytes()
        result = render_scene(source)
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (120, 180))
        self.assertEqual(inspect_upload(result, "scene.webp", "scene")["kind"], "scene")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioPipelineTests(unittest.TestCase):
    def test_actual_waveform_and_sample_analysis(self):
        source = audio_bytes()
        metadata = inspect_upload(source, "misnamed.mp3", "audio")
        self.assertEqual(metadata["mime"], "audio/wav")
        self.assertEqual(metadata["channels"], 1)
        self.assertEqual(metadata["sample_rate"], AUDIO_RATE)
        self.assertEqual(metadata["source_sample_rate"], 22050)
        self.assertAlmostEqual(metadata["duration"], 0.25, places=3)
        self.assertEqual(len(metadata["peaks"]), 384)
        self.assertAlmostEqual(metadata["peak"], 0.25, places=2)
        self.assertAlmostEqual(metadata["rms"], 0.25 / math.sqrt(2), places=2)
        self.assertEqual(metadata["loudness_status"], "not_applicable_short_clip")
        self.assertIsNone(metadata["lufs"])

    def test_trim_fade_gain_pan_loop_and_original_preserved(self):
        source = audio_bytes(duration=0.5)
        digest = sha256(source).hexdigest()
        recipe = {"trim_start": 0.1, "trim_end": 0.4, "gain_db": -6,
                  "pan": 1, "fade_in": 0.03, "fade_out": 0.03,
                  "loop_start": 0.04, "loop_end": 0.25,
                  "highpass_hz": 30, "lowpass_hz": 12000, "eq_mid_db": 1}
        result = process_audio(source, "tone.wav", recipe)
        self.assertEqual(result["extension"], "wav")
        self.assertEqual(result["mime"], "audio/wav")
        self.assertEqual(result["metadata"]["frames"], 13230)
        self.assertEqual(result["metadata"]["loop_start_frame"], 1764)
        self.assertAlmostEqual(result["metadata"]["duration"], 0.3)
        self.assertEqual(result["metadata"]["channels"], 2)
        self.assertLess(result["metadata"]["peak"], 0.15)
        self.assertEqual(result["data"], process_audio(source, "tone.wav", recipe)["data"])
        with wave.open(BytesIO(result["data"]), "rb") as clip:
            self.assertEqual(clip.getnframes(), 13230)
            samples = array("h", clip.readframes(clip.getnframes()))
            self.assertEqual(max(abs(value) for value in samples[::2]), 0)
            self.assertGreater(max(abs(value) for value in samples[1::2]), 1000)
            self.assertLess(max(abs(value) for value in samples[:8]), 10)
        self.assertEqual(sha256(source).hexdigest(), digest)

    def test_refuses_invalid_recipe_and_clipping(self):
        source = audio_bytes(duration=0.2, amplitude=0.9)
        edits = [{"gain_db": 12}, {"gain_db": float("inf")}, {"trim_start": 0.2, "trim_end": 0.1},
                 {"trim_end": 1}, {"fade_in": 0.15, "fade_out": 0.15},
                 {"loop_start": 0.1}, {"loop_start": 0.1, "loop_end": 0.3},
                 {"highpass_hz": 10000, "lowpass_hz": 5000}, {"pan": 2}, {"filters": "amovie=/etc/passwd"}]
        for recipe in edits:
            with self.subTest(recipe=recipe), self.assertRaises(MediaError):
                process_audio(source, "tone.wav", recipe)

    def test_rejects_playlists_corrupt_audio_and_surround(self):
        for source in (b"#EXTM3U\nhttps://example.com/secret.wav", b"RIFF\x00\x00\x00\x00WAVEjunk",
                       b"<svg/>", audio_bytes(duration=0.1, channels=6)):
            with self.subTest(source=source[:16]), self.assertRaises(MediaError):
                inspect_upload(source, "allowed.wav", "audio")

    def test_loudness_valid_for_longer_audio_and_silence_json_safe(self):
        source = audio_bytes(duration=3.1, channels=2)
        measured = process_audio(source, "long.wav")["metadata"]
        self.assertEqual(measured["loudness_status"], "measured")
        self.assertTrue(math.isfinite(measured["lufs"]))
        self.assertTrue(math.isfinite(measured["true_peak_db"]))
        silence = inspect_upload(audio_bytes(duration=0.1, amplitude=0), "quiet.wav", "audio")
        self.assertIsNone(silence["peak_db"])
        self.assertIsNone(silence["rms_db"])
        self.assertTrue(silence["silent"])


class ContentStoreTests(unittest.TestCase):
    def test_content_addressing_idempotence_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContentStore(tmp)
            one = store.put(b"original byte content", "png")
            two = store.put(b"original byte content", "png")
            self.assertEqual(one, two)
            self.assertEqual(store.get(one["key"]), b"original byte content")
            self.assertTrue(store.exists(one["key"]))
            (Path(tmp) / one["key"]).write_bytes(b"modified content")
            with self.assertRaises(StorageError):
                store.get(one["key"])
            with self.assertRaises(StorageError):
                store.put(b"original byte content", "png")

    def test_concurrent_same_upload_creates_one_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContentStore(tmp)
            with ThreadPoolExecutor(max_workers=6) as pool:
                receipts = list(pool.map(lambda _: store.put(b"concurrent upload", "wav"), range(12)))
            self.assertEqual(len({result["key"] for result in receipts}), 1)
            self.assertEqual(len(list(Path(tmp).rglob("*.wav"))), 1)
            self.assertEqual(store.get(receipts[0]["key"]), b"concurrent upload")

    def test_invalid_keys_extensions_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            store = ContentStore(tmp)
            for key in ("../secret", "/etc/passwd", "objects/aa/" + "b" * 64 + ".wav",
                        "https://bucket.example/file", "objects/aa/" + "a" * 64 + ".svg"):
                with self.subTest(key=key), self.assertRaises(StorageError):
                    store.get(key)
            with self.assertRaises(StorageError):
                store.put(b"data", "../svg")
            source = b"symlink test"
            prefix = sha256(source).hexdigest()[:2]
            (Path(tmp) / "objects").mkdir()
            (Path(tmp) / "objects" / prefix).symlink_to(outside, target_is_directory=True)
            with self.assertRaises(StorageError):
                store.put(source, "png")
            self.assertFalse(list(Path(outside).iterdir()))

    def test_incomplete_s3_does_not_fall_back_to_ephemeral_local(self):
        with patch.dict(os.environ, {"STUDIO_S3_ENDPOINT": "https://s3.example.test"}, clear=True):
            with self.assertRaises(StorageError):
                ContentStore()
        with patch.dict(os.environ, {"STUDIO_S3_BUCKET": "private", "STUDIO_S3_ENDPOINT": "http://s3.example.test",
                                     "STUDIO_S3_ACCESS_KEY": "test", "STUDIO_S3_SECRET_KEY": "test"}, clear=True):
            with self.assertRaises(StorageError):
                ContentStore()


if __name__ == "__main__":
    unittest.main()
