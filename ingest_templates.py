"""
Template ingestion.

Forza's .ai template files are PDF-compatible, so we open them with
PyMuPDF (fitz) like any PDF. Each file has been observed to contain either
1 artboard (the real trim-size template) or up to 4 (duplicates of a
slightly larger bleed/mockup artboard alongside the real one). In every
file seen so far, artboard/page index 0 is the correctly-trimmed template
that matches our known label dimensions -- this script verifies that
assumption per-file rather than trusting it blindly, and flags any file
where page 0 doesn't match a known dimension group.

Filename convention observed:
    APXXX_N1_PRODUCT NAME_<size descriptor>_<dims>_PDFsize_<BOND|SEAL>.ai
  - BOND  -> category "Adhesive"
  - SEAL  -> category "Sealant"
  - (no Tape templates seen yet)
  - top-level folder name = vertical market (e.g. "Industrial")

Dimensions in filenames are sometimes given in the opposite orientation
from product_sizes.py (e.g. "8.25x6.5" in a filename vs (6.5, 8.25) in
config) -- these are the same physical size, just landscape vs portrait
notation, so matching is done on sorted (min,max) dimension pairs with a
small tolerance, not exact ordered tuples.
"""

import os
import re
import fitz

from product_sizes import PRODUCT_SIZES
from template_config import DIMENSION_GROUPS, register_template

OUTPUT_DIR = "templates_rendered"
RENDER_DPI = 300
DIM_TOLERANCE_IN = 0.05  # inches; flags mismatches beyond this rather than silently accepting

SUFFIX_TO_CATEGORY = {
    "BOND": "Adhesive",
    "SEAL": "Sealant",
    "TAPE": "Tape",
}


def _norm_pair(w, h):
    """Orientation-independent dimension key: sorted (min, max)."""
    return tuple(sorted((round(w, 3), round(h, 3))))


def _known_dim_groups_normalized():
    """Map normalized (min,max) dims -> dimension group key string,
    built from product_sizes.py (the source of truth for label sizes)."""
    out = {}
    for entry in PRODUCT_SIZES.values():
        dims = entry["item_label"]
        if dims is None:
            continue
        norm = _norm_pair(*dims)
        key = f"{dims[0]:g}x{dims[1]:g}"
        out[norm] = key
    return out


def detect_category(filename):
    upper = filename.upper()
    for suffix, category in SUFFIX_TO_CATEGORY.items():
        if suffix in upper:
            return category
    return None


def find_trim_page(doc, known_dims_norm):
    """Return (page_index, dimension_group_key) for the first page whose
    size matches a known dimension group within tolerance. Returns
    (None, None) if no page matches."""
    for i, page in enumerate(doc):
        w_in = page.rect.width / 72
        h_in = page.rect.height / 72
        norm = _norm_pair(w_in, h_in)
        for known_norm, group_key in known_dims_norm.items():
            if (abs(norm[0] - known_norm[0]) <= DIM_TOLERANCE_IN and
                    abs(norm[1] - known_norm[1]) <= DIM_TOLERANCE_IN):
                return i, group_key
    return None, None


def ingest_directory(root_dir, dpi=RENDER_DPI):
    """Walk root_dir, treating each immediate subfolder as a vertical
    market name, rasterize the correct artboard from each .ai file found,
    and register it into the template config.

    Returns a report dict: {"registered": [...], "unmatched": [...]}
    """
    known_dims_norm = _known_dim_groups_normalized()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    registered = []
    unmatched = []

    for vertical in sorted(os.listdir(root_dir)):
        vertical_path = os.path.join(root_dir, vertical)
        if not os.path.isdir(vertical_path):
            continue
        for fname in sorted(os.listdir(vertical_path)):
            if not fname.lower().endswith(".ai"):
                continue
            fpath = os.path.join(vertical_path, fname)
            category = detect_category(fname)
            if category is None:
                unmatched.append((fpath, "could not detect category (BOND/SEAL/TAPE) from filename"))
                continue

            try:
                doc = fitz.open(fpath)
            except Exception as e:
                unmatched.append((fpath, f"failed to open: {e}"))
                continue

            page_idx, dim_group = find_trim_page(doc, known_dims_norm)
            if page_idx is None:
                unmatched.append((fpath, "no page matched a known dimension group"))
                continue

            page = doc[page_idx]
            pix = page.get_pixmap(dpi=dpi)
            out_name = f"{category}_{vertical}_{dim_group}.png".replace(" ", "_")
            out_path = os.path.join(OUTPUT_DIR, out_name)
            pix.save(out_path)

            register_template(category, vertical, dim_group, out_path)
            registered.append({
                "source": fpath,
                "category": category,
                "vertical": vertical,
                "dimension_group": dim_group,
                "page_index": page_idx,
                "output": out_path,
            })

    return {"registered": registered, "unmatched": unmatched}


if __name__ == "__main__":
    import json
    report = ingest_directory("templates_incoming/LABEL TEMPLATES")
    print(f"Registered {len(report['registered'])} templates:")
    for r in report["registered"]:
        print(f"  [{r['category']:9s}] {r['vertical']:12s} {r['dimension_group']:10s} <- {os.path.basename(r['source'])}")
    if report["unmatched"]:
        print(f"\n{len(report['unmatched'])} files NOT matched:")
        for path, reason in report["unmatched"]:
            print(f"  {os.path.basename(path)}: {reason}")
