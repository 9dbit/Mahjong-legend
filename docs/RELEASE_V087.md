# Mahjong Wild UI 0.8.7 — continuous crown and presentation polish

## User feedback and resulting behavior

The v0.8.6 crown was allocated the height left after the reels. On the user's
short Safari viewport, this reduced the logo scene to a narrow center panel
between enlarged decorative side strips. The stage filled the screen, but
the crown still looked cut apart.

The layout now reserves the original 864:305 crown geometry at the full stage
width before sizing the board. One continuous background from the approved
portrait frame paints the entire crown; its legacy three children are hidden.
The board gives up some height while retaining 2:3 tile faces. The lower panel
budget is reduced slightly to move the controls downward as well. Controls
remain inside their safe insets, with a circular Spin disk.

The two lanterns formerly inherited the complete side-frame distortion. Their
upper 256 source rows now scale separately from the flexible dragon body. A
10% vertical correction makes the source's gently oval lanterns rounder. The
lower 89 rows preserve the foot ornaments. Only the middle 593 rows absorb
the remaining height. Compact layouts cap ornament heights to avoid overlap;
they do not promise the same lantern proportions or touch target sizes as a
normal phone portrait viewport.

Warm radial light and fine rays above the crest pulse and sweep using CSS
opacity and transforms. Masks fade the light at its bounds. The effect pauses
while reels run and becomes a subtle static glow for reduced-motion users.
It remains separate from the existing lettering shine and does not intercept
touches.

## Audio

A shared output GainNode after the SFX and music buses multiplies the existing
mix by 1.30. Saved slider values, music/SFX balance, mute and gesture unlocking
are preserved. This is a 30% signal-amplitude increase in the application;
hardware speaker volume and perceived loudness are outside that measurement.
There is no new compressor or limiter.

The focused audio QA renders the actual AudioNode graph through the browser's
OfflineAudioContext, compares output against an independently calculated
baseline, and checks saved mute and mute after unlocking produce zero output.
Real asset loading and gesture unlocking remain covered by the menu/audio
suite. Physical-iPhone audibility is still an open device check.

## Build and cache identity

Build from clean source inputs in this order:

```sh
python tools/build_locked_ui.py
python tools/build_presentation_fx.py
python tools/build_approved_ui.py
python tools/build_portrait_ui.py
python tools/build_responsive_runtime.py
python tools/build_fullframe_ui.py
```

The last two commands accept `--runtime-only` in the production Docker image.
The `fullframe-v086` directory remains the component family; generated HTML,
server metadata, reels, release.json and QA identify the release as **0.8.7**.
Asset queries and the service-worker presentation cache use **087**. The
builder recognizes v085/v086 derivatives and is idempotent for v087. Original
integrity-checked inputs must not be replaced by generated outputs in Git.

## Verification gates

- Existing unit, API, replay, artwork, motion, menus, reel and delayed-input
  suites remain required.
- Full-frame QA checks eight viewports per engine, asymmetric safe areas,
  standalone resume and resize during one accepted Spin.
- `qa_logo_v087.py` checks full-width crown source painting, downward movement
  against a frozen v086 baseline, lantern source-row joins, animation, reduced
  motion and a compact viewport in Chromium and WebKit.
- `qa_audio_gain_v087.py` checks actual 1.30 output gain and persisted settings
  in both engines.
- Main-only live verification compares all 32 release file hashes, then checks
  a real HTTPS Spin, reel ordering and deterministic replay.

Deployment completion is established by CI and Railway receipts, not by this
release note. Hosted WebKit and injected safe areas are not physical iPhone
or Home Screen installation verification. An already-open PWA should be closed
and reopened after the update; the app never forces a reload during a Spin.

The original artwork references and math 0.8.0 configuration are unchanged.
