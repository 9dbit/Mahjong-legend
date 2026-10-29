# Approved Master V105 (locked reference)

The user approved source `ornate_mahjong_wild_slot_interface.png` (941 × 1672). SHA256: `746ccd38a86f2077c2d463a3f4dfcbec4f4b189500e687f2493ebecbd9e9ef6a`.

The available project reference ZIP is named `Mahjong_Wild_Approved_Master_Assets_v105_2026-10-30.zip`. Never bake the master screenshot's browser chrome, tile symbols, balances, win value or controls into the gameplay background.

For exact, source-faithful artwork, install the following 5 WebP files from the locked ZIP into this directory: `header-crown-approved.webp`, `side-left-dragon-jade.webp`, `side-right-dragon-jade.webp`, `top-left-corner-approved.webp`, and `top-right-corner-approved.webp`. Studio runtime compiler detects all five and switches to `data-master-art="v105-locked"`. Otherwise it retains the verified approved source imagery, new proportional geometry and top corner ornament via `v105-fallback`. Do not silently claim the locked source is live in fallback mode.

Only four of six outer tile visuals contribute to scoring, with five central rows. Math engine unchanged.

## Integrity gate

The compiler pins and validates the **exact SHA-256 of each of the five WebP derivatives** against the approved source asset ZIP. A partial or modified raster pack fails the build instead of silently changing the source-approved visual.
