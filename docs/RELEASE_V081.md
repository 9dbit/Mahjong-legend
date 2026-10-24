# Mahjong Wild UI 0.8.1

Presentation-only update. The engine and math configuration remain 0.8.0, with base multipliers [1,2,3,5] and bonus [2,3,5,8]. No new RTP estimate is claimed.

- Actual reel strips scroll downward with a sampled smootherstep curve: slow, fast, slow. Cosmetic filler never enters the math engine.
- Winning regular tiles crack for 185 ms, then split into nine fragments containing their actual texture. Refill awaits the 640 ms shatter timeline. Turbo scales this duration; reduced motion bypasses it.
- Enhanced winning tiles retain their separate Gold-to-Wild path.
- Spin disk uses a continuous integrated angle with acceleration/deceleration, not an abruptly restarted CSS animation loop.
- Existing approved logo pixels receive aligned emissive and shine masks. No extra lettering is rendered over the logo.
- Tile symbols get low-intensity colored emission; board and controls get restrained glow.
- Meter label/value gaps, long readouts, skip label, footer and dialog controls are bounded within their intended areas.
- All game timelines remain cancellable, including rapid skip and page hide. No paid request is automatically retried.

Build: run tools/build_locked_ui.py, then tools/build_presentation_fx.py. Both run in Docker and CI. QA covers engine replay, visible fracture frames, reel speed profile, six viewports, menu panels, turbo, reduced motion and single-debit skip in Chromium and WebKit. Browser engine emulation does not replace physical iPhone testing.
