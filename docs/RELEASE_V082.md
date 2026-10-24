# Mahjong Legend — UI v0.8.2

The public-facing game name remains **Mahjong Wild**. This presentation release
preserves the approved dragon/frame artwork and math v0.8.0 byte-for-byte.

## Requested changes

- Winning ceramic tiles reveal illuminated cracks, then split into nine irregular
  pieces carrying the original winning tile texture, with jade thickness, golden
  impact stars and drifting sparks. Replacement tiles wait for the effects to
  finish. Decorative effects remain inside the board's frame and clear on Skip.
- Gold-to-Wild behavior, smooth reel acceleration/deceleration, and server outcomes
  are preserved. Removed the inherited hover/activity ring that doubled Spin art.
- **Jade Garden**, an original gentle oriental instrumental, supplies soft
  plucked-string and flute-like tones at 68 BPM. The 28.235-second loop and thirteen
  SFX assets are generated deterministically with the Python standard library.
  Total uncompressed audio is under 1.8 MB. No third-party recording is used.
- First-gesture audio waits for a running Web Audio context. There is one music
  loop, a separate bounded reel sound, synchronized ceramic sounds, all button
  feedback, volume/mute controls, and a visible **Tes Suara** control. New users
  start with music at 22%; saved explicit OFF settings remain OFF. Backgrounding
  pauses audio, and resume does not create duplicate loops.
- Rules, Paytable, History, Fairness, Settings, Auto Spin, and Reset confirmation
  share red lacquer, jade, gold edges, dimensional buttons and real tile artwork.
  Menus include keyboard navigation, visible focus, mobile scrolling, and stateful
  sound controls. Reset requires its own themed confirmation.
- The PWA background covers the full viewport independently of the locked 9:16
  game. Board/control content stays inside safe-area insets. Home Screen metadata,
  standalone manifest and icons are included. Normal browser chrome remains under
  browser control. The server is required for play; no API or balance is cached.

## Build and verification

Docker and CI build the locked sprites, aligned light masks, Home Screen icons,
and original audio before testing. The CI workflow runs the Python regression
suite, existing gameplay/motion tests in Chromium and WebKit, and the focused
`qa_presentation_v082.py` checks for ceramic effects, real Web Audio RMS, one-loop
invariants, first-click audio, menu geometry, safe areas, and skip/replay behavior.
On main, public HTTPS verification checks the actual runtime files and real Spin
and replay against the authorized Railway URL.

Browser audio graph measurements are not a listening test of physical iPhone
speakers. Browser visibility and safe-area checks include simulated conditions;
installed-PWA behavior on a physical device still needs acceptance testing.

## Math scope

Base multipliers remain **×1 → ×2 → ×3 → ×5**; bonus remains **×2 → ×3 → ×5 → ×8**.
No outcome, RNG, paytable, bet, or payout rule changes are included. RTP has not
been revalidated since the earlier ×4-to-×5 math change. All credits remain
virtual and non-redeemable.
