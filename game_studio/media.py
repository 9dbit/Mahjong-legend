"""Bounded, non-destructive media ingestion for Game Studio workers.

Original bytes never change. These functions return decoded metadata or a new
derivative; storage and publication are separate operations. Filenames are only
display metadata: a decoder, never an extension, decides the actual type.
"""
from __future__ import annotations

from array import array
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import warnings
import wave

from PIL import Image, ImageOps, UnidentifiedImageError


RENDERER_VERSION = "studio-media/1"
TILE_SIZE = (218, 327)
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
MAX_IMAGE_SIDE = 8192
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_AUDIO_SECONDS = 120
AUDIO_RATE = 44100
MAX_PCM_BYTES = (MAX_AUDIO_SECONDS * AUDIO_RATE * 2 * 4) + AUDIO_RATE
WAVEFORM_BINS = 384
_BODY_DIR = Path(__file__).resolve().parents[1] / "web/assets/approved-v082/tiles"


class MediaError(ValueError):
    """An upload or recipe cannot safely produce a supported derivative."""


def _bytes(data: bytes, maximum: int) -> bytes:
    if not isinstance(data, bytes) or not data:
        raise MediaError("Upload must contain non-empty file bytes")
    if len(data) > maximum:
        raise MediaError(f"Upload exceeds the {maximum // (1024 * 1024)} MiB limit")
    return data


def _number(value, key: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise MediaError(f"{key} must be a number")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise MediaError(f"{key} must be between {low:g} and {high:g}")
    return value


def _recipe(value: dict | None, allowed: set[str]) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - allowed:
        raise MediaError("Recipe contains unsupported fields")
    return dict(value)


def _image(data: bytes) -> tuple[Image.Image, str]:
    _bytes(data, MAX_IMAGE_BYTES)
    try:
        # Do not change Pillow's process-wide limits while other jobs run.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise MediaError("Use a PNG, JPEG or WebP image")
                fmt = source.format
                width, height = source.size
                if (width < 1 or height < 1 or max(width, height) > MAX_IMAGE_SIDE
                        or width * height > MAX_IMAGE_PIXELS):
                    raise MediaError("Image exceeds 8192 px per side or 24 megapixels")
                if getattr(source, "n_frames", 1) != 1:
                    raise MediaError("Animated images are not supported for game artwork")
                source.load()  # A successful header probe alone is insufficient.
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.info.clear()
                return image, fmt
    except MediaError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise MediaError("The image is damaged or cannot be decoded safely") from exc


def _audio_format(data: bytes) -> tuple[str, str]:
    """Select a demuxer from binary magic; never auto-open playlists or URLs."""
    _bytes(data, MAX_AUDIO_BYTES)
    if data[:4] in {b"RIFF", b"RF64"} and data[8:12] == b"WAVE":
        return "wav", "audio/wav"
    if data[:4] == b"OggS":
        return "ogg", "audio/ogg"
    if data[:4] == b"fLaC":
        return "flac", "audio/flac"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "mov", "audio/mp4"
    if data[:3] == b"ID3" or (len(data) > 2 and data[0] == 255 and data[1] & 224 == 224):
        return "mp3", "audio/mpeg"
    raise MediaError("Use a decodable WAV, MP3, M4A, OGG or FLAC audio file")


def _run(args: list[str], directory: Path, *, timeout: int = 35,
         capture_json: bool = False) -> tuple[bytes, str]:
    """No shell, no network protocols, bounded logs and a wall-clock deadline."""
    stdout_path, stderr_path = directory / "command-out", directory / "command-error"
    try:
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=err, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("Media processing exceeded its time limit") from exc
    except FileNotFoundError as exc:
        raise MediaError("The media worker requires FFmpeg and ffprobe") from exc
    with stderr_path.open("rb") as error_file:
        stderr = error_file.read(16384).decode("utf-8", errors="replace")
    if result.returncode:
        # Do not expose filesystem paths, uploaded metadata or raw decoder logs.
        raise MediaError("The audio decoder rejected this file or edit recipe")
    if capture_json and stdout_path.stat().st_size > 64 * 1024:
        raise MediaError("Audio metadata exceeds the supported limit")
    return (stdout_path.read_bytes() if capture_json else b""), stderr


def _input_args(path: Path, fmt: str) -> list[str]:
    args = ["-protocol_whitelist", "file,pipe", "-f", fmt]
    if fmt == "mov":
        args += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    return args + ["-i", str(path)]


def _probe(path: Path, fmt: str, directory: Path) -> dict:
    raw, _ = _run(["ffprobe", "-v", "error", "-threads", "1",
                   *_input_args(path, fmt), "-show_entries",
                   "stream=codec_type,codec_name,sample_rate,channels,duration:format=duration",
                   "-of", "json"], directory, capture_json=True)
    try:
        info = json.loads(raw)
        streams = info["streams"]
        audio = [x for x in streams if x.get("codec_type") == "audio"]
        if len(audio) != 1 or any(x.get("codec_type") == "video" for x in streams):
            raise MediaError("Upload audio with exactly one audio stream and no video")
        sample_rate, channels = int(audio[0]["sample_rate"]), int(audio[0]["channels"])
        if channels not in (1, 2) or not 8000 <= sample_rate <= 96000:
            raise MediaError("Use mono or stereo audio between 8 kHz and 96 kHz")
        reported = audio[0].get("duration", info.get("format", {}).get("duration"))
        if reported not in (None, "N/A"):
            duration = float(reported)
            if not math.isfinite(duration) or duration <= 0 or duration > MAX_AUDIO_SECONDS + 0.02:
                raise MediaError(f"Audio must be longer than zero and at most {MAX_AUDIO_SECONDS} seconds")
        return {"source_sample_rate": sample_rate, "channels": channels,
                "codec": audio[0].get("codec_name", "unknown")}
    except MediaError:
        raise
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise MediaError("Audio metadata is invalid") from exc


def _decode(data: bytes, directory: Path) -> tuple[Path, dict]:
    fmt, mime = _audio_format(data)
    source = directory / "source.bin"
    source.write_bytes(data)
    metadata = _probe(source, fmt, directory)
    pcm_path = directory / "decoded.f32"
    # Decode slightly beyond the allowed duration so an unknown or forged header
    # cannot silently turn an oversize track into an accepted truncated file.
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
          "-xerror", "-threads", "1", *_input_args(source, fmt),
          "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1",
          "-t", str(MAX_AUDIO_SECONDS + 0.05), "-ar", str(AUDIO_RATE),
          "-ac", str(metadata["channels"]), "-f", "f32le", str(pcm_path)], directory)
    byte_size = pcm_path.stat().st_size
    channels = metadata["channels"]
    if not byte_size or byte_size > MAX_PCM_BYTES or byte_size % (channels * 4):
        raise MediaError("Decoded audio is empty or exceeds its memory limit")
    frames = byte_size // (channels * 4)
    if frames / AUDIO_RATE > MAX_AUDIO_SECONDS + 1 / AUDIO_RATE:
        raise MediaError(f"Decoded audio exceeds {MAX_AUDIO_SECONDS} seconds")
    metadata.update({"mime": mime, "duration": frames / AUDIO_RATE,
                     "frames": frames, "sample_rate": AUDIO_RATE})
    return pcm_path, metadata


def _samples(path: Path) -> array:
    if path.stat().st_size > MAX_PCM_BYTES:
        raise MediaError("Audio exceeds the decoded memory limit")
    values = array("f")
    with path.open("rb") as source:
        values.fromfile(source, path.stat().st_size // 4)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def _db(value: float) -> float | None:
    return round(20 * math.log10(value), 3) if value > 0 else None


def _analyse(values: array, channels: int) -> dict:
    frames = len(values) // channels
    if not frames:
        raise MediaError("Audio must contain at least one frame")
    bins = min(WAVEFORM_BINS, frames)
    channel_peaks = [[] for _ in range(channels)]
    aggregate = []
    global_peak = sum_squares = 0.0
    clipped = 0
    for index in range(bins):
        start, end = index * frames // bins, (index + 1) * frames // bins
        lower, upper = [math.inf] * channels, [-math.inf] * channels
        combined = 0.0
        for frame in range(start, end):
            for channel in range(channels):
                sample = values[frame * channels + channel]
                if not math.isfinite(sample):
                    raise MediaError("Audio contains non-finite samples")
                lower[channel] = min(lower[channel], sample)
                upper[channel] = max(upper[channel], sample)
                magnitude = abs(sample)
                combined = max(combined, magnitude)
                global_peak = max(global_peak, magnitude)
                sum_squares += sample * sample
                clipped += magnitude > 1
        aggregate.append(round(combined, 5))
        for channel in range(channels):
            channel_peaks[channel].append([round(lower[channel], 5), round(upper[channel], 5)])
    rms = math.sqrt(sum_squares / len(values))
    return {"peaks": aggregate, "channel_peaks": channel_peaks,
            "waveform_bins": bins, "peak": round(global_peak, 8),
            "peak_db": _db(global_peak), "rms": round(rms, 8), "rms_db": _db(rms),
            "clipped_samples": clipped, "silent": global_peak == 0}


def _loudness(pcm_path: Path, metadata: dict, directory: Path) -> dict:
    # Integrated loudness is not a useful editing target for a 150 ms UI tap.
    if metadata["duration"] < 3:
        return {"lufs": None, "true_peak_db": None,
                "loudness_status": "not_applicable_short_clip"}
    _, stderr = _run(["ffmpeg", "-hide_banner", "-loglevel", "info", "-nostdin",
                      "-f", "f32le", "-ar", str(AUDIO_RATE), "-ac", str(metadata["channels"]),
                      "-i", str(pcm_path), "-filter_threads", "1", "-af",
                      "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], directory)
    try:
        match = re.search(r'\{\s*"input_i".*?\}', stderr, re.S)
        measured = json.loads(match.group()) if match else {}
        integrated, peak = float(measured["input_i"]), float(measured["input_tp"])
        return {"lufs": integrated if math.isfinite(integrated) else None,
                "true_peak_db": peak if math.isfinite(peak) else None,
                "loudness_status": "measured" if math.isfinite(integrated) else "below_gate"}
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise MediaError("Loudness analysis did not produce a valid report") from exc


def inspect_upload(data: bytes, filename: str, kind: str = "tile") -> dict:
    """Validate and decode original bytes, returning a JSON-safe analysis."""
    if kind not in {"tile", "scene", "audio"}:
        raise MediaError("Unsupported media kind")
    common = {"sha256": sha256(data).hexdigest() if isinstance(data, bytes) else "",
              "byte_size": len(data) if isinstance(data, bytes) else 0,
              "kind": kind, "renderer_version": RENDERER_VERSION}
    if kind in {"tile", "scene"}:
        image, fmt = _image(data)
        extrema = image.getchannel("A").getextrema()
        return {**common, "mime": {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt],
                "width": image.width, "height": image.height,
                "has_alpha": extrema[0] < 255, "format": fmt.lower()}
    with tempfile.TemporaryDirectory(prefix="mahjong-media-") as tmp:
        directory = Path(tmp)
        pcm_path, metadata = _decode(data, directory)
        return {**common, **metadata, **_analyse(_samples(pcm_path), metadata["channels"]),
                **_loudness(pcm_path, metadata, directory)}


def render_tile(data: bytes, recipe: dict | None = None) -> bytes:
    """Render one portrait tile. Glyph mode reuses the approved ceramic body."""
    edit = _recipe(recipe, {"mode", "fit", "zoom", "x", "y", "gold", "background"})
    mode, fit = edit.get("mode", "whole_tile"), edit.get("fit", "contain")
    if mode not in {"whole_tile", "glyph"} or fit not in {"contain", "cover"}:
        raise MediaError("Choose whole_tile or glyph mode and contain or cover fit")
    zoom = _number(edit.get("zoom", 1), "zoom", 0.25, 4)
    x = _number(edit.get("x", 0.5), "x", 0, 1)
    y = _number(edit.get("y", 0.5), "y", 0, 1)
    gold = edit.get("gold", False)
    if not isinstance(gold, bool):
        raise MediaError("gold must be true or false")
    background = edit.get("background", "#00000000")
    if not isinstance(background, str) or not re.fullmatch(r"#[a-fA-F0-9]{6}(?:[a-fA-F0-9]{2})?", background):
        raise MediaError("background must be a hexadecimal RGB or RGBA color")
    image, _ = _image(data)
    canvas = Image.new("RGBA", TILE_SIZE, background)
    if mode == "glyph":
        source = _BODY_DIR / ("base-gold.webp" if gold else "base-ivory.webp")
        if not source.is_file():
            raise MediaError("Approved tile bodies are unavailable; build the artwork first")
        with Image.open(source) as body:
            canvas = body.convert("RGBA").resize(TILE_SIZE, Image.Resampling.LANCZOS)
        box = (24, 45, 170, 237)
    else:
        box = (0, 0, *TILE_SIZE)
    left, top, width, height = box
    ratio = (min if fit == "contain" else max)(width / image.width, height / image.height) * zoom
    # Inverse-map straight into the small output. Resizing an 8192×1 source
    # to "cover" a portrait first would allocate hundreds of millions of pixels.
    offset_x = round((width - image.width * ratio) * x)
    offset_y = round((height - image.height * ratio) * y)
    layer = image.transform((width, height), Image.Transform.AFFINE,
                            (1 / ratio, 0, -offset_x / ratio, 0, 1 / ratio, -offset_y / ratio),
                            resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
    canvas.alpha_composite(layer, (left, top))
    output = BytesIO()
    canvas.save(output, format="PNG", optimize=False, compress_level=6)
    return output.getvalue()


def render_scene(data: bytes) -> bytes:
    """Strip metadata and re-encode a decoded, bounded still image for runtime."""
    image, _ = _image(data)
    output = BytesIO()
    image.save(output, format="WEBP", lossless=True, method=1)
    if output.tell() > MAX_IMAGE_BYTES:
        raise MediaError("Rendered scene exceeds 16 MiB; use a smaller source image")
    return output.getvalue()


def _audio_recipe(recipe: dict | None, metadata: dict) -> dict:
    edit = _recipe(recipe, {"trim_start", "trim_end", "loop_start", "loop_end", "fade_in", "fade_out",
                            "gain_db", "pan", "highpass_hz", "lowpass_hz",
                            "eq_low_db", "eq_mid_db", "eq_high_db"})
    duration = metadata["duration"]
    start = _number(edit.get("trim_start", 0), "trim_start", 0, duration)
    end = _number(edit.get("trim_end", duration), "trim_end", 0, duration)
    start_frame, end_frame = round(start * AUDIO_RATE), round(end * AUDIO_RATE)
    if end_frame <= start_frame:
        raise MediaError("Trim end must be after trim start")
    length = (end_frame - start_frame) / AUDIO_RATE
    normalized = {"trim_start": start_frame / AUDIO_RATE, "trim_end": end_frame / AUDIO_RATE,
                  "gain_db": _number(edit.get("gain_db", 0), "gain_db", -60, 12),
                  "pan": _number(edit.get("pan", 0), "pan", -1, 1),
                  "fade_in": _number(edit.get("fade_in", 0), "fade_in", 0, length),
                  "fade_out": _number(edit.get("fade_out", 0), "fade_out", 0, length)}
    for key in ("fade_in", "fade_out"):
        normalized[key] = round(normalized[key] * AUDIO_RATE) / AUDIO_RATE
    if normalized["fade_in"] + normalized["fade_out"] > length + 1 / AUDIO_RATE:
        raise MediaError("Combined fades cannot exceed the trimmed clip")
    for key in ("eq_low_db", "eq_mid_db", "eq_high_db"):
        normalized[key] = _number(edit.get(key, 0), key, -12, 12)
    for key in ("highpass_hz", "lowpass_hz"):
        normalized[key] = _number(edit.get(key, 0), key, 0, 20000)
        if normalized[key] and normalized[key] < 20:
            raise MediaError(f"{key} must be zero (disabled) or at least 20 Hz")
    if (normalized["highpass_hz"] and normalized["lowpass_hz"]
            and normalized["highpass_hz"] >= normalized["lowpass_hz"]):
        raise MediaError("High-pass frequency must be below low-pass frequency")
    if (edit.get("loop_start") is None) != (edit.get("loop_end") is None):
        raise MediaError("Set both loop_start and loop_end, or neither")
    if edit.get("loop_start") is not None:
        loop_start = _number(edit["loop_start"], "loop_start", 0, length)
        loop_end = _number(edit["loop_end"], "loop_end", 0, length)
        if round(loop_end * AUDIO_RATE) <= round(loop_start * AUDIO_RATE):
            raise MediaError("Loop end must be after loop start within the rendered clip")
        normalized.update({"loop_start": round(loop_start * AUDIO_RATE) / AUDIO_RATE,
                           "loop_end": round(loop_end * AUDIO_RATE) / AUDIO_RATE})
    else:
        normalized.update({"loop_start": None, "loop_end": None})
    return normalized


def process_audio(data: bytes, filename: str, recipe: dict | None = None) -> dict:
    """Render exact playable PCM WAV and analysis from a validated edit recipe.

    The file is lossless and supported by the existing Web Audio runtime. A
    lossy delivery codec can be added later as another immutable derivative;
    recipes always start from the retained original, never an earlier export.
    """
    with tempfile.TemporaryDirectory(prefix="mahjong-audio-") as tmp:
        directory = Path(tmp)
        decoded, source_metadata = _decode(data, directory)
        edit = _audio_recipe(recipe, source_metadata)
        channels = source_metadata["channels"]
        output_channels = 2 if edit["pan"] else channels
        start_frame = round(edit["trim_start"] * AUDIO_RATE)
        end_frame = round(edit["trim_end"] * AUDIO_RATE)
        duration = (end_frame - start_frame) / AUDIO_RATE
        filters = [f"atrim=start_sample={start_frame}:end_sample={end_frame}", "asetpts=PTS-STARTPTS"]
        if edit["highpass_hz"]:
            filters.append(f"highpass=f={edit['highpass_hz']:.6f}")
        if edit["lowpass_hz"]:
            filters.append(f"lowpass=f={edit['lowpass_hz']:.6f}")
        for name, frequency in (("eq_low_db", 120), ("eq_mid_db", 1000), ("eq_high_db", 8000)):
            if edit[name]:
                filters.append(f"equalizer=f={frequency}:t=q:w=0.707:g={edit[name]:.6f}")
        if edit["gain_db"]:
            filters.append(f"volume={edit['gain_db']:.6f}dB")
        if edit["pan"]:
            pan = edit["pan"]
            # Mono uses a constant-power pan; stereo uses balance attenuation.
            left = math.cos((pan + 1) * math.pi / 4) if channels == 1 else (1 - max(0, pan))
            right = math.sin((pan + 1) * math.pi / 4) if channels == 1 else (1 + min(0, pan))
            filters.append(f"pan=stereo|c0={left:.9f}*c0|c1={right:.9f}*c{0 if channels == 1 else 1}")
        if edit["fade_in"]:
            filters.append(f"afade=t=in:ss=0:ns={round(edit['fade_in'] * AUDIO_RATE)}")
        if edit["fade_out"]:
            fade_frames = round(edit["fade_out"] * AUDIO_RATE)
            filters.append(f"afade=t=out:ss={end_frame - start_frame - fade_frames}:ns={fade_frames}")
        rendered = directory / "rendered.f32"
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
              "-f", "f32le", "-ar", str(AUDIO_RATE), "-ac", str(channels), "-i", str(decoded),
              "-filter_threads", "1", "-af", ",".join(filters), "-f", "f32le", str(rendered)], directory)
        samples = _samples(rendered)
        if len(samples) != (end_frame - start_frame) * output_channels:
            raise MediaError("Rendered sample count differs from the selected region")
        analysis = _analyse(samples, output_channels)
        if analysis["clipped_samples"]:
            raise MediaError("This edit exceeds 0 dBFS; lower gain or EQ before rendering")
        pcm = array("h", (max(-32768, min(32767, round(sample * 32768))) for sample in samples))
        # Analyse the exact quantized samples that are about to be exported.
        # The earlier floating-point analysis is solely the no-clipping gate.
        quantized = array("f", (sample / 32768 for sample in pcm))
        analysis = _analyse(quantized, output_channels)
        if sys.byteorder != "little":
            quantized.byteswap()
        with rendered.open("wb") as output:
            quantized.tofile(output)
        if sys.byteorder != "little":
            pcm.byteswap()
        target = BytesIO()
        with wave.open(target, "wb") as output:
            output.setnchannels(output_channels)
            output.setsampwidth(2)
            output.setframerate(AUDIO_RATE)
            output.writeframes(pcm.tobytes())
        result = target.getvalue()
        metadata = {"kind": "audio", "mime": "audio/wav", "sha256": sha256(result).hexdigest(),
                    "byte_size": len(result), "duration": duration, "sample_rate": AUDIO_RATE,
                    "channels": output_channels, "frames": end_frame - start_frame,
                    "source_sha256": sha256(data).hexdigest(), "renderer_version": RENDERER_VERSION,
                    "loop_start_frame": None if edit["loop_start"] is None else round(edit["loop_start"] * AUDIO_RATE),
                    "loop_end_frame": None if edit["loop_end"] is None else round(edit["loop_end"] * AUDIO_RATE),
                    **analysis}
        metadata.update(_loudness(rendered, metadata, directory))
        return {"data": result, "mime": "audio/wav", "extension": "wav", "metadata": metadata, "recipe": edit}
