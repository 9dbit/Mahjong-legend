# Mahjong Legend v0.5: Motion & Sound

This version upgrades the **existing playable browser game**; it does not replace or alter the v0.3 deterministic math engine, payout tables, RNG, or replay verification.

## Visual interaction sequence

1. **Start:** the paid virtual-credit spin is requested from the authoritative server. The displayed balance is debited immediately for feedback while server results are awaited.
2. **Reels:** the visual-only preview spins all five reels, with staggered settling and individual porcelain tile-stop effects. This cosmetic preview has no influence on payouts or the RNG. The displayed symbols at each stop are taken from the server event transcript.
3. **Win:** the engine's winning indices are highlighted; a floating amount and the animated Win meter reflect the award exactly.
4. **Cascade:** winning ordinary symbols dissolve; enhanced winning symbols flash and become Wild. Survivors move from their previous row into the updated positions; new tiles enter from above. Every new board comes from `event.after` in the authoritative replay.
5. **Multiplier:** the active multiplier level lights up for each cascade. Values come from the server's math configuration, not hard-coded PG Soft rules.
6. **Bonus:** the board and free-spin phase receive a distinct glow and fanfare. Retriggers, caps, and round-end celebrations are transcript-driven.
7. **Finish:** total winnings and remaining virtual balance are synchronized with the server state, and the committed seed can still be independently replay-verified.

## Original procedural sound effects

Audio is synthesized in-browser via Web Audio API, using gentle filtered percussive sounds and original pitched envelopes. No third-party music, PG Soft samples, or external audio downloads are included.

- **Spin**: short upward whoosh / mechanical attack.
- **Reel stops**: five slightly differentiated porcelain clacks.
- **Cascade**: tile-release click and brief tonal glide.
- **Multiplier**: two-note lift.
- **Wild transformation**: sparkling glissando.
- **Bonus / retrigger**: four-note ascending motif.
- **Win / Big Win**: short ascending tones and a brighter five-note flourish.
- **Buttons**: lightweight tactile tone.

Sound is enabled by default; the browser activates it on an explicit tap/click, as required by mobile audio-autoplay restrictions. Settings include **Sound ON/OFF** and **SFX volume 0–100%**, persisted locally when permitted by browser storage. Players can toggle sound instantly.

## UX and accessibility

- Mobile-first portrait layout, no landing page.
- Render animations use GPU-friendly transforms and opacity where feasible.
- The physical **Spin / Skip**, **Turbo**, and limited **Auto Spin** controls remain working.
- `prefers-reduced-motion` removes decorative animations and shortens the event sequence.
- No result changes from sound toggles, animation speed, or skipped animations.

## Validation

- 32/32 Python engine and virtual-credit tests passed, no math engine changes.
- Browser smoke passed at 390x844, 375x667, 320x568, and 1440x900, with no JS exceptions or horizontal scroll.
- Motion events verified with deterministic seeds: two cascades including Gold-to-Wild, and a separate eight-free-spin round.
- Web Audio instrumentation confirmed synthesized effects start on a user-initiated spin (17 oscillator starts in a specific test spin).
- Actual iPhone Safari speaker output and physical-device FPS have **not** been verified by this local Chromium test.

## Design and ownership

Gameplay layout and motion hierarchy are researched against the public Mahjong Ways 2 rules and interface. All Mahjong Legend illustrations, ornaments, transitions, sound synthesis, and branding remain **original**. This is a virtual-credit-only game prototype; it does not include deposits, withdrawals, redeemable credits, PG Soft assets, or PG Soft affiliation.
