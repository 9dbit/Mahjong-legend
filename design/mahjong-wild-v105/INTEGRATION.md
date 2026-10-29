# Mahjong Wild approved master V105 (LOCKED)

Source SHA-256 `746ccd38a86f2077c2d463a3f4dfcbec4f4b189500e687f2493ebecbd9e9ef6a`; original resolution `941 x 1672`.

## Asset ownership

`header-crown-approved.webp` carries the original crown and logo art only; it does not include the browser status bar.

`side-left-dragon-jade.webp` and `side-right-dragon-jade.webp` contain transparent masks in the actual game field, preserving only dragons, lanterns, ornamental gold/jade foreground and lower corner overlays.

`top-left-corner-approved.webp` and `top-right-corner-approved.webp` include gold/jade upper corner ornaments.

`footer-look-reference-only.webp` is QA/reference only, **never use as game controls or HUD**.

## Browser placement geometry

Canvas scene W=941 H=1549 after cropping browser chrome y=83. Scoring field x=179..762, y=373..1240. For a stage reel width B, use side overlay width `260*B/583` and left offset `-179*B/583`; right same. Side overlay height is equal to board height. Master crown ratio `941 / (294-83)`.

No game engine/payout logic may be reconstructed from these reference graphics.
