# Forza Label Generator — Handoff Summary

This package contains the working code and processed assets for an automated
Forza product label generator, in the middle of a transition to a new,
more reliable approach. Read this whole file before doing anything else.

## What this project is
A tool that takes a product's SDS + TDS PDFs, a few text fields (product
code, name, size, etc.), and generates a print-ready label PNG automatically
— pulling hazard statements, pictograms, ingredients/CAS numbers, storage
and disposal text, and application directions straight from the source
documents.

There are TWO distinct label layouts, used for different package sizes:

1. **Main two-column layout** (`render_label()` in `label_renderer.py`) —
   used for Cartridges, Sausages, Pails, Drums, Cans. Logo + badge box at
   top, two content columns below, footer with size/product code/lot.
2. **Compact three-column layout** (`render_compact_label()` in
   `label_renderer.py`) — used for Aerosol, 22L Canister, 108L Canister.
   Directions/Storage on the left, logo+badge+size in the center, Signal
   Word/Hazard/Contains+pictograms on the right.

There's also `app.py`, a Streamlit form that ties the whole pipeline
together (upload SDS/TDS → parse → fill in text fields → generate →
download).

## THE BIG PIVOT IN PROGRESS — read this carefully
For most of this project, `render_label()` and `render_compact_label()`
built every fixed visual element (logos, badge boxes, drop shadows,
rounded corners, footer branding) **from scratch in Python** — drawing
shapes, compositing icons, hand-tuning shadow blur/offset values, etc.
This worked, but every subtle visual mismatch against the real reference
labels cost a slow round of back-and-forth (wrong corner radius, wrong
shadow opacity, icon halos, drift from the real Kallisto/Poppins/Co-Text
fonts, etc.).

**We are moving away from that**, toward: take a REAL blank/reference
label PDF (rendered at 300dpi), surgically erase only the specific
DYNAMIC text regions (product code, product name, sales bar text, footer
size/AP#/lot#), and use the rest of that real image completely untouched
as the background. Only the erased regions get new dynamic text drawn on
top at render time. This guarantees every fixed element (logo position,
box shape, real multiply-blend transparency on the grey boxes, exact
shadow rendering, footer branding) is pixel-perfect because it IS the
real file, not a reconstruction.

**Proof of concept completed and approved-in-progress:** see
`baked_backgrounds_wip/cartridge_marine_v15_current.png` — this is a
real Marine/10.1oz Cartridge label (from `AP881_N2_M-OS789-GRY_10_1Cartridge_8x6_PDFsize.pdf`,
which Mike provided but is NOT included in this package — re-upload it
if you need to regenerate this from scratch) with dynamic regions erased
and ready for text overlay. This took ~15 iterations to get right. Key
lessons learned, in case you hit the same bugs again on a different
size/vertical:

- **Corner radius must be measured from the real PDF, not guessed.**
  Guessed radii don't match the shadow that was baked in with the real
  (usually much smaller/subtler) radius, leaving a visible mismatch/notch
  at the corner.
- **When a fixed graphic (like the vertical icon) overlaps dynamic text
  in the source file, don't try to "restore" pixels from the flattened
  render in the overlap zone** — if text was drawn on top of part of the
  icon in the original, those icon pixels were never rendered anywhere
  and can't be recovered. Instead, place our own clean pre-extracted
  icon asset (from `vertical_badge_icons/`) on top with its own
  programmatic shadow.
- **When patching a gradient/background region, sample from the exact
  same row (y-position) you're pasting into**, not a different vertical
  position — this background is a gradient, so color shifts with height,
  and sampling from the wrong row creates a visible seam.
- **Don't tile a small sample to fill a wide area** — any tiny artifact
  in the sample repeats as a visible pattern. Take one wide sample and
  stretch it once instead.
- **Measure box edges precisely via pixel-scanning**, not assumption —
  more than once, an assumed coordinate (e.g. "box bottom is at y=370")
  turned out to be wrong by ~19pt when directly measured, causing subtle
  patch-boundary artifacts.
- Confirmed via direct inspection of the PDF's ExtGState objects: the
  grey content boxes use a **real Multiply blend mode at 75-90% opacity**
  (not a flat opaque fill) — this is why the background shows through
  them. This is preserved for free using the "real file as background"
  approach, but would need to be replicated manually if you ever go back
  to drawing boxes from scratch.

## What's NOT done yet
- Only ONE size/vertical combo (10.1oz Cartridge, Marine) has been
  converted to the new baked-background approach. All other
  sizes/verticals still use the old from-scratch rendering in
  `render_label()`/`render_compact_label()`.
- Mike has been gathering real reference PDFs for every vertical
  (Marine, Industrial, Transportation, Insulation, Construction,
  Composites confirmed; Foam explicitly skipped) and multiple package
  sizes, to repeat this same erase-and-bake process across the board.
  These raw PDFs are NOT included in this package (too large) — Mike
  will need to re-upload them in the new chat.
- Known data bugs in `product_sizes.py` that were found but the exact
  fix may not be applied yet — check current file contents:
  - `22L Canister` and `Aerosol Can` had their width/height swapped in
    storage (stored portrait when the real templates are landscape).
  - `108L Canister`'s stored dimensions (12x4.125) don't match the real
    template, which is actually 11.693x3.5 — same as 22L Canister.
- The compact layout (`render_compact_label()`) has several manual
  fixes already applied (stacked logo, rounded corners, icon
  centering, Contains/pictogram positioning) but has NOT yet been
  converted to the baked-background approach at all.
- `VERTICAL_BADGE_TEXT_COLOR` in `layout_config.py` only has Marine
  confirmed (teal, `#137875`) — an early attempt to apply each
  vertical's brand color to ALL verticals' badge text was proven wrong
  by real examples (two different Industrial products both showed navy,
  not the vertical's orange) — don't re-apply that assumption without
  new confirmed evidence per vertical.

## Suggested next steps in the new chat
1. Re-upload the real reference PDFs for whichever size/vertical you
   want to convert next.
2. Reuse the erase-and-bake process demonstrated on the Cartridge/Marine
   example — measure real box/badge/icon/footer coordinates directly
   from the PDF (via PyMuPDF's `get_drawings()`, `search_for()`, and
   direct pixel-scanning), erase only the dynamic text regions, verify
   with zoomed-in crops against the untouched baseline before declaring
   it done.
3. Eventually wire the renderer to look up and load the correct baked
   background per size+vertical, instead of drawing from scratch.
