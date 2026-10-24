# Mahjong Wild UI 0.8.4 | Smooth Spin + Soft Tech

Source of truth: existing approved mobile 9:16 art, **unchanged**. UI updated; virtual-credit math remains `0.8.0`.

## Rendering

- Spins use exactly five **GPU compositor-animated tile atlas canvases** (one per column). Their 4/5/5/5/4 original DOM tiles remain painted underneath for the entire animation. Canvas atlases are rendered **once** per Spin, not re-uploaded to the GPU every animation frame.
- CSS cubic-bezier(.72, 0, .28, 1) provides slow-fast-slow motion. Reels start 1 to 5 and stop 1 to 5 with 135 ms stagger; turbo 70 ms. No column is ever removed before the final decoded tiles are ready.
- Asset preparation is a non-destructive step; decode or animation failure resolves to the authoritative server board, with a logged fallback. Frame monitors record slow frames but do not rasterize artwork in the animation loop.
- Backing resolution bounded to 1.5 DPR and 3900 pixels high; extra glows pause during rolling. Skip, resize, tab background and reduced-motion are supported.

## Soft Tech intro

- Splash matches the Soft Tech branding used by the user's UNO LUCK project; import of its exact brand logo is separate from this approved Mahjong artwork.
- `CONTINUE PLAY` remains disabled until assets and game state are ready. Tapping it invokes the existing `MahjongWildAudio.unlock()` synchronously, respecting saved mute and music settings. No second AudioContext is created.

## Anonymous diagnostics

- Last 30 Spin timing summaries are kept locally, exported via Settings > EKSPOR LOG SPIN.
- **Explicit opt-in**, OFF by default: Settings > Kirim log performa anonim. Only durations, frame gaps, column start/stop order, viewport size and sanitized errors are sent to `/api/diagnostics/spin` with no cookies. Balance, bets, seeds, session IDs, IP addresses, user agent, and game outcomes are not included in payload or server logs.
- Railway deploy logs: search for `MW_SPIN_DIAG`. Public retrieval of other users' logs does not exist.

## Validation and limits

Run `python -m unittest discover -s tests -q`, `python tools/qa_reels_v083.py`, `python tools/qa_approved_v082.py` and motion tests in Chromium and WebKit. CI checks the exact public release after deployment. Browser automation is not a substitute for a physical iPhone GPU check.
