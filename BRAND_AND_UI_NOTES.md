# Mahjong Legend v0.4: Brand and UX handoff

## UI inspiration and original implementation

Reference reviewed: PG Soft *Mahjong Ways 2*, Game Information, main-game UI and control descriptions. The source shows a portrait-oriented reel-first game layout, multiplier strip above reels, thin message band below, Balance/Bet/Win row, and a centered circular Spin control with Turbo/Auto and stake controls nearby.

The Mahjong Legend UI is not a pixel-perfect or asset-identical copy of the PG Soft copyrighted game. It preserves the general layout hierarchy, while using its own header, original CSS ornamentation, hand-drawn vector-like Mahjong suits, brand name, and the previously validated independent math model.

Reference PDF: https://www.pgsoft.com/uploads/Games/Pdf/Mahjong_Ways_2_Gameinformation_EN.pdf

## Branding tokens

Edit the top `:root` block in `web/style.css`:

| Token | v0.4 sample | Usage |
| --- | --- | --- |
| `--brand-red` | `#9b4632` | Vermilion machine frame |
| `--brand-red-deep` | `#5e221e` | Frame shadow |
| `--brand-bronze` | `#a8673c` | Beveled details |
| `--brand-gold` | `#edcf77` | Metallic ornament |
| `--brand-gold-light` | `#fff1b0` | Active highlights |
| `--brand-jade` | `#159c8b` | Spin wheel, multiplier |
| `--brand-jade-bright` | `#46c8b1` | Accent glow |
| `--brand-green` | `#276f53` | Background elements |
| `--tile-ivory` | `#f8f5ea` | Tile faces |
| `--tile-edge` | `#d3d0bb` | Tile bevels |

Note: some supporting gradients currently use literal sampled tonal values. Once a final palette is locked, consolidate these into derived palette tokens to make full theme changes one-click.

## Graphic replacement points

- `web/app.js`: `makeDotArt()`, `makeBambooArt()`, `tileFace()`, `makeIngot()`, `dragonTiles`, `charTiles`
- `web/style.css`: `.tile`, `.tile.enhanced`, `.wild-art`, `.scatter-art`, `.reel-theatre`, `.scene`
- `web/index.html`: `.game-header`, `.spin-control` SVG

Original drawing SVGs are generated in code, so they work offline and can be replaced with licensed WebP/AVIF/SVG later. No third-party graphic assets are packaged.

## UI flow

Launch -> full game -> select virtual Bet -> Spin -> animation / cascade / Wild / bonus -> updated Balance and Win -> repeat.

Game menu -> Rules / Paytable / History / Fairness / Settings. Press Escape or the X icon to close dialogs. Keyboard Space spins from the game viewport. Auto Spin is limited to 10, 25 or 50 rounds and can be stopped after the active spin. Turbo changes animation timing only, not outcomes.

## Known boundaries

- Client Playwright smoke tests use realistic math engine fixtures and mocked fetch, separately from live HTTP endpoint unit tests.
- Browser live HTTP testing must be repeated on a less restricted development machine.
- Version: UI 0.4, math engine and simulation baseline 0.3.0.
- Currently local-only demo with virtual credits that cannot be redeemed.
- UI is responsive, not yet packaged as a native app or deployed to staging.
