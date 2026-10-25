# Mahjong Legend 0.9.1 — approved red/gold control panel

The user identified a visual regression in UI0.9.0: its continuous footer had become a flat jade panel. The approved artwork has a crimson and gold stage, an ornate red result banner, gold-framed emerald counters, ruby Turbo/Auto controls, and jade/gold Spin and bet controls.

## Visual correction

- Replace the jade SVG panel with one continuous red/gold stage image, including decorative clouds and stairs. Its coordinates remain shared across the result, controls, and PWA bottom extension.
- Restore the result banner, all three counter frames/icons, Turbo, Auto, minus, and plus from CSS sprite windows in the existing approved frame. Turbo/Auto use an alpha mask around their circular faces and captions to remove the source sheet's rectangular background patches. Their source pixels are reused; values and state remain live DOM content.
- Keep the approved rotating Spin disc and the enlarged targets: Spin80–96px, Turbo/Auto52–60px, and bet controls44px. Spin is retained and functional.
- Reserve78px for the ornate result/counter rows on phones, with a58px compact budget for very short windows, so visible SALDO/BET/MENANG labels and values remain legible without consuming the board. The board keeps its2:3 tile ratio, and the full-width crown, rounded lanterns, and animated light remain in place.
- Preserve the `--ff-console-art` published Studio override. This patch requires no configuration publication or data migration.

The new backing is an imagegen-derived background layer with the old baked buttons, values, and banner removed. The approved master is unchanged. Its provenance and exact sprite coordinates are recorded beside the asset in `web/assets/control-panel-v091/provenance.json`.

## Runtime and caching

Final HTML, public state/health, Studio version display, and release metadata identify UI0.9.1. The presentation cache and loader query keys advance to091. Component paths such as `studio-v090` and `fullframe-v086` remain stable families.

Game mathematics, paytable, payout distribution, persistent balances, round settlement, media processing, audio settings, and administrator credentials are unchanged. A pending round continues under its pinned release.

## Verification

The existing controls gate now requires the actual red/gold background and approved sprite sources, decodes each displayed image, and retains all target-size, collision, safe-area, hit-test, one-Spin, Turbo, and Auto checks. The existing Chromium/WebKit full-frame and integrated game gates remain required.

The main-branch production gate compares exact generated HTTP bytes, including the new background discovered through CSS, then verifies one virtual-credit Spin and replay. Automated safe-area tests remain simulations; they do not claim physical-device acceptance.
