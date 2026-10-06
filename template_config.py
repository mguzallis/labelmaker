"""
Template lookup config.

Templates are keyed by three things, in this order:
    category (Adhesive / Sealant / Tape)  -> vertical market -> dimension group

CATEGORY IS A REQUIRED EXPLICIT PROMPT, not inferred from the SDS.
Some SDS documents describe a product that reads as both adhesive and
sealant, so category can never be auto-detected reliably; the app must ask.

Tape has no SDS at all -- it only ships with a TDS. The label generator
must treat category="Tape" as a signal to SKIP the entire SDS-derived
hazard block (signal word, hazard/precautionary statements, pictograms,
storage, disposal, ingredients) and only populate fields sourced from the
TDS (Application Instructions, product name/description).

Dimension groups collapse the 13 product types down to their distinct
label footprints (several package types share identical label dimensions,
e.g. Gallon Can through 55 Gallon Drum are all 8.25x6.25), so we only need
one template per vertical per category per dimension group, not one per
product type.
"""

from product_sizes import PRODUCT_SIZES
from layout_config import COMPACT_ZONE_SET_BY_DIMENSION_GROUP

CATEGORIES = ["Adhesive", "Sealant", "Tape"]

REQUIRES_SDS = {
    "Adhesive": True,
    "Sealant": True,
    "Tape": False,
}

# Some product types are only ever produced as Adhesive (ForzaBOND) --
# no Sealant version exists, so the app shouldn't prompt for one or flag
# a missing Sealant template as an ingestion gap for these.
ADHESIVE_ONLY_PRODUCT_TYPES = [
    "108L Canister",
    "22L Canister",
    "Aerosol Can",
]


def available_categories_for_product(product_type):
    if product_type in ADHESIVE_ONLY_PRODUCT_TYPES:
        return ["Adhesive"]
    return CATEGORIES


def _dim_group_key(dims):
    """Turn a (w, h) tuple into a stable string key, e.g. (8.25, 6.25) -> '8.25x6.25'."""
    w, h = dims
    fmt = lambda n: str(int(n)) if n == int(n) else str(n)
    return f"{fmt(w)}x{fmt(h)}"


# All distinct dimension groups actually in use, derived from product_sizes.py
DIMENSION_GROUPS = sorted({
    _dim_group_key(v["item_label"])
    for v in PRODUCT_SIZES.values()
    if v["item_label"] is not None
})


def dimension_group_for_product(product_type):
    from product_sizes import get_label_dimensions
    return _dim_group_key(get_label_dimensions(product_type))


def is_compact_layout(dimension_group):
    """True for the three-column layout (Aerosol Can, 22L Canister, 108L
    Canister -- render_compact_label), False for everything else (the
    main two-column layout -- render_label). Callers need this to pick
    which render function to call for a given product; a dimension group
    not in this set always means the main layout, never an error (unlike
    compact_zone_px's dimension_group, which raises for an unmeasured
    compact dimension group specifically)."""
    return dimension_group in COMPACT_ZONE_SET_BY_DIMENSION_GROUP


# Vertical markets -- placeholder list, update once confirmed
VERTICAL_MARKETS = [
    "Marine",
    "Transportation",
    "Industrial",
    "Construction",
    "Composites",
    "Insulation",
    # add/remove as confirmed
]

# TEMPLATES[category][vertical][dimension_group] = path to background template file
# Filled in as template files are uploaded. None = not yet provided.
TEMPLATES = {
    category: {
        vertical: {dim: None for dim in DIMENSION_GROUPS}
        for vertical in VERTICAL_MARKETS
    }
    for category in CATEGORIES
}


def has_template(category, vertical, product_type):
    """Non-raising check: True if a real baked background is registered
    for this combination, False otherwise (including unknown category/
    vertical). Lets callers warn the user clearly about an unsupported
    combination BEFORE generating, rather than silently falling back to
    the lower-quality from-scratch rendering path with no explanation."""
    if category not in TEMPLATES or vertical not in TEMPLATES.get(category, {}):
        return False
    dim = dimension_group_for_product(product_type)
    return TEMPLATES[category][vertical].get(dim) is not None


def get_template(category, vertical, product_type):
    if category not in TEMPLATES:
        raise KeyError(f"Unknown category: {category!r}")
    if vertical not in TEMPLATES[category]:
        raise KeyError(f"Unknown vertical: {vertical!r}")
    dim = dimension_group_for_product(product_type)
    path = TEMPLATES[category][vertical].get(dim)
    if path == "DYNAMIC":
        # Deliberate opt-out of a baked background: render_label draws
        # everything (logo, vertical name, icon, bars, grey boxes) fresh
        # on the clean generic background when baked_background_path is
        # None. Used where an erased baked background kept producing
        # texture artifacts in the erased logo region -- using the real,
        # untouched background entirely avoids that class of bug.
        return None
    if path is None:
        raise ValueError(
            f"No template on file yet for category={category!r}, "
            f"vertical={vertical!r}, dimension={dim!r} "
            f"(product type: {product_type!r})"
        )
    return path


def get_box_label_template(category, vertical, product_type):
    """Same as get_template, but for the box_label background variant
    (e.g. Aerosol Can's case/box label, which is a visually different
    background from its item_label -- not just extra text on the same
    one). Returns None (not an exception) when no box-label variant
    exists for this product -- unlike get_template, where a missing
    template is always worth surfacing, a missing box-label variant is
    the normal case for most products and callers should just fall back
    to the regular item_label background."""
    return TEMPLATES_BOX_LABEL.get(category, {}).get(vertical, {}).get(
        dimension_group_for_product(product_type)
    )


def register_template(category, vertical, dimension_group, filepath):
    """Call this once a template file has been uploaded and saved, to wire
    it into the lookup table."""
    if dimension_group not in DIMENSION_GROUPS:
        raise ValueError(f"Unknown dimension group: {dimension_group!r}")
    TEMPLATES[category][vertical][dimension_group] = filepath


# Known-good baked backgrounds, registered at import time so every caller
# gets them without a separate init step. All seven Marine dimension
# groups now have a measured zone set (layout_config.py) AND a real baked
# background registered here.
for dim in ["8x6", "8.25x6.25", "6x4", "8x8", "11.5x3.5", "12x4.125", "8.25x6.5"]:
    register_template("Adhesive", "Marine", dim, f"baked_backgrounds_wip/marine_{dim}_v1_current.png")
    register_template("Sealant", "Marine", dim, f"baked_backgrounds_wip/marine_{dim}_v1_current.png")

# Industrial's 8x8 (28oz Cartridge) uses a consensus 2-column position
# measured from Transportation/Composites/Construction rather than its
# own real template, since Industrial's own 28oz reference used an
# anomalous 3-column layout that every other vertical's 28oz Cartridge
# disagreed with (see layout_config.py note, and /areas/label-generator.md)
# -- standardized to the common layout rather than propagating the
# one-off exception.
for dim in ["8x6", "8x8", "6x4", "8.25x6.25", "8.25x6.5", "11.5x3.5", "12x4.125"]:
    register_template("Sealant", "Industrial", dim, f"baked_backgrounds_wip/industrial_{dim}_v1_current.png")
    register_template("Adhesive", "Industrial", dim, f"baked_backgrounds_wip/industrial_{dim}_v1_current.png")
    register_template("Sealant", "Transportation", dim, f"baked_backgrounds_wip/transportation_{dim}_v1_current.png")
    register_template("Adhesive", "Transportation", dim, f"baked_backgrounds_wip/transportation_{dim}_v1_current.png")

# Composites' 8x8 (28oz Cartridge) and 8.25x6.25 (5 Gallon Pail) both used
# anomalous 3-column layouts in their own real references (same pattern as
# Industrial's 8x8) -- standardized to the common 2-column position
# (consensus for 8.25x6.25, matching Transportation/Composites/Construction
# for 8x8) rather than propagating either one-off exception.
# Insulation has no 28oz Cartridge (8x8) background -- no source material
# was provided for this vertical/size combination. Deliberately left
# unregistered rather than guessed at; get_template() will raise clearly.
for dim in ["8x6", "8x8", "6x4", "8.25x6.25", "8.25x6.5", "11.5x3.5", "12x4.125"]:
    register_template("Sealant", "Composites", dim, f"baked_backgrounds_wip/composites_{dim}_v1_current.png")
    register_template("Adhesive", "Composites", dim, f"baked_backgrounds_wip/composites_{dim}_v1_current.png")
    register_template("Adhesive", "Construction", dim, f"baked_backgrounds_wip/construction_{dim}_v1_current.png")
    register_template("Sealant", "Construction", dim, f"baked_backgrounds_wip/construction_{dim}_v1_current.png")

# Main-layout sizes for Industrial and Composites switched to dynamic
# rendering (no baked background at all) -- repeated attempts at erasing
# the logo from these verticals' real blank PDFs kept producing visible
# texture artifacts (smeared/flattened hex decorations) in the erased
# region, no matter the erasure technique used. Using the real, untouched
# generic background with everything (logo, vertical name, icon, bars,
# grey boxes) drawn fresh by render_label eliminates that whole class of
# bug, since nothing is erased or reconstructed.
for dim in ["8x6", "8x8", "6x4", "8.25x6.25"]:
    register_template("Sealant", "Industrial", dim, "DYNAMIC")
    register_template("Adhesive", "Industrial", dim, "DYNAMIC")
    register_template("Sealant", "Composites", dim, "DYNAMIC")
    register_template("Adhesive", "Composites", dim, "DYNAMIC")
    register_template("Sealant", "Transportation", dim, "DYNAMIC")
    register_template("Adhesive", "Transportation", dim, "DYNAMIC")
    register_template("Sealant", "Construction", dim, "DYNAMIC")
    register_template("Adhesive", "Construction", dim, "DYNAMIC")
for dim in ["8.25x6.5", "11.5x3.5", "12x4.125"]:
    register_template("Sealant", "Insulation", dim, f"baked_backgrounds_wip/insulation_{dim}_v1_current.png")
    register_template("Adhesive", "Insulation", dim, f"baked_backgrounds_wip/insulation_{dim}_v1_current.png")
for dim in ["8x6", "6x4", "8.25x6.25"]:
    register_template("Sealant", "Insulation", dim, "DYNAMIC")
    register_template("Adhesive", "Insulation", dim, "DYNAMIC")

# Box-label backgrounds, keyed the same way as TEMPLATES but for products
# whose box/case label is a genuinely different background image, not
# just extra dynamic text on the item_label one. This was WRONGLY
# populated with an Aerosol Can entry at first -- direct pixel-diff of
# the two real source PDFs showed they're identical except for the
# literal "Count: 12" text, which is exactly what the existing
# case_quantity parameter already draws dynamically (same mechanism
# Cartridge/Sausage box labels use). Registering a separate background
# for Aerosol would have baked that one fixed count in as a permanent
# image instead of dynamic text, and silently ignored whatever count the
# user actually entered. Deliberately empty until a product shows up
# whose box label is a real visual variant, not just added text.
TEMPLATES_BOX_LABEL = {}


if __name__ == "__main__":
    print("Categories:", CATEGORIES)
    print("Dimension groups in use:", DIMENSION_GROUPS)
    print("Verticals (placeholder, confirm list):", VERTICAL_MARKETS)
