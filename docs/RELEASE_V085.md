# Mahjong Wild UI 0.8.5

User-requested presentation revision, based on production commit
`58d7e197fa7556c0ce35fd38c5364ad6733ed356`. Math remains 0.8.0.

## Visible changes
- Tile faces and live slots are 2:3 (218 x 327 sprites). The board extends down;
  the original header, win plaque, meters and controls retain their scale.
  The frame is derived at 864 x 1859; only its vertical side-body region grows.
- x2 has stronger cyan brightness while inactive and gold emission while active.
- Pointer-down starts a cached decorative reel loop without waiting for the
  server. The verified server result is spliced into that moving view and settles
  left to right. No speculative results, extra requests, or changed math.
- Input-to-first-frame and server-wait timings join the opt-in diagnostics.
- Soft Tech/Continue Play, menus, sounds, retained DOM anti-blank protection,
  Turbo, Skip and server-authoritative replay remain.

## Source/build
`tools/build_portrait_ui.py` derives the assets without editing the master art.
`tools/runtime_v085_edits.json` contains reviewable line edits against hashed
v084 source files. `tools/build_responsive_runtime.py` checks source and target
SHA-256s and emits the new runtime under `web/assets/portrait-v085/`, updating
entrypoints and QA versions at build time. It refuses stale upstream sources.
The old v084 runtime is kept intact as the derivation source.

Run the existing three artwork builders, then the portrait builder and runtime
builder before tests. Docker uses --runtime-only (tests are excluded from the image); CI also derives the QA sources. `qa_portrait_v085.py`
checks four viewports, actual 2:3 geometry, delayed-result input, visible ceramic
pixels, exactly one paid request, Skip before response, rejected requests and
final-board/replay agreement. Offline mode is only a sandbox transport adapter;
HTTP/CSP, WebKit and the live deployment require their own verification.

Physical iPhone frame pacing/audio is not certified by headless browser tests.
This is still a virtual-credit-only prototype; no RTP or money features change.
