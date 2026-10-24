# Mahjong Wild UI 0.8.2

This is a real runtime replacement, not a new generated concept image.
The reference is the user-approved 864 x 1536 PWA artwork dated 2026-10-24.

- The exact source is committed at `web/assets/reference/approved_pwa_20261024.jpg`.
- The clock and battery drawing are removed from `approved_pwa_native_status.webp`; actual OS status indicators remain native. This preprocessing uses local masked inpainting, not generative artwork.
- `tools/build_approved_ui.py` preserves source pixels outside cleared runtime fields and derives ceramic sprites, logo emission masks, numeral sprites, disk and safe-area extensions.
- Real server outcomes continue to drive 23 tile positions, cascade, multiplier, counters and winning amounts. No image sample balance or winning amount is represented as a real result.
- Menu tabs, paytable, history, settings, fairness, auto-spin and reset confirmation use one ruby / jade / gold theme.
- Nine irregular textured ceramic fragments have ivory/jade depth edges. Sparks and fragments are awaited before refill. Gold-to-Wild remains a separate action.
- A gesture-unlocked shared audio mixer prevents the first click from being dropped. One original 76 BPM pentatonic music loop (Jade Serenity, 50.526 seconds) has AAC and Ogg versions. Music and effects have independent volume controls; saved mute preferences are preserved. Music starts only after user input.
- Root-scoped PWA manifest and service worker; only presentation resources can be cached. API requests, outcomes and session state are never cached. Offline spin is blocked.
- Live UI release is 0.8.2; math release remains 0.8.0. Base x1/x2/x3/x5, bonus x2/x3/x5/x8, weights, cap and replay math are unchanged. Earlier RTP estimates remain unvalidated.

Visual scope: source decorations and layout are used directly, not promised pixel-identical dynamic data. Some symbols absent from the reference retain prior numeral overlays. The 4/5/5/5/4 active reel geometry is retained. Device safe areas and OS status UI differ by device; physical iPhone verification is still required.

Build: `python tools/build_locked_ui.py && python tools/build_presentation_fx.py && python tools/build_approved_ui.py`
Tests: `python -m unittest discover -s tests -q`
Browser checks: `python tools/qa_locked_ui.py`, `python tools/qa_motion_v081.py`, `python tools/qa_approved_v082.py`.
The two latter scripts support `--engine webkit`; `--offline --browser /usr/bin/chromium` is a sandbox-only fallback, not a substitute for HTTP/CSP CI checks.
