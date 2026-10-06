"""
Product size -> label dimension config.

"item_label" is the dimension that matters for THIS tool (the product
label itself). "box_label" / box_quantity / pallet_quantity are shipping/
logistics data included for completeness in case they're useful later
(e.g. auto-generating case labels down the road), but the label generator
only uses item_label dimensions to size the canvas.

Dimensions are stored as (width_in, height_in) tuples, inches.
A dash ("-") in the source table means "not applicable / not produced at
that packaging level" and is stored as None.
"""

def _dim(s):
    if s is None or s == "-":
        return None
    w, h = s.split("x")
    return (float(w), float(h))


PRODUCT_SIZES = {
    "10.1oz Cartridge": {
        "item_label": _dim("8x6"),
        "box_label": _dim("8x6"),
        "box_quantity": 12,
        "pallet_quantity": None,
    },
    "28oz Cartridge": {
        "item_label": _dim("8x8"),
        "box_label": _dim("8x8"),
        "box_quantity": 12,
        "pallet_quantity": 432,
    },
    "10oz Sausage": {
        "item_label": _dim("8x6"),
        "box_label": _dim("8x6"),
        "box_quantity": 20,
        "pallet_quantity": None,
    },
    "20oz Sausage": {
        "item_label": _dim("6x4"),
        "box_label": _dim("6x4"),
        "box_quantity": 20,
        "pallet_quantity": 960,
    },
    "Gallon Can": {
        "item_label": _dim("8.25x6.25"),
        "box_label": _dim("8.25x6.25"),
        "box_quantity": 4,
        "pallet_quantity": 216,
    },
    "2 Gallon Can": {
        "item_label": _dim("8.25x6.25"),
        "box_label": None,
        "box_quantity": None,
        "pallet_quantity": None,
    },
    "3.5 Gallon Can": {
        "item_label": _dim("8.25x6.25"),
        "box_label": None,
        "box_quantity": None,
        "pallet_quantity": None,
    },
    "5 Gallon Pail": {
        "item_label": _dim("8.25x6.25"),
        "box_label": None,
        "box_quantity": None,
        "pallet_quantity": 36,
    },
    "52 Gallon Drum": {
        "item_label": _dim("8.25x6.25"),
        "box_label": None,
        "box_quantity": None,
        "pallet_quantity": 208,
    },
    "55 Gallon Drum": {
        "item_label": _dim("8.25x6.25"),
        "box_label": None,
        "box_quantity": None,
        "pallet_quantity": 220,
    },
    "22L Canister": {
        # Width/height were transposed here -- confirmed against the real
        # blank label template. Nominal spec size is 11.5x3.5 (per the
        # source template's filename/naming); the template PDF itself
        # renders slightly wider at 11.693in -- treat 11.5 as the correct
        # stored spec and 11.693 as that template's own render quirk, not
        # the other way around.
        "item_label": _dim("11.5x3.5"),
        "box_label": None,
        "box_quantity": None,
        "pallet_quantity": 36,
    },
    "108L Canister": {
        # NOT verified against a real template yet (unlike 22L Canister and
        # Aerosol Can, both of which turned out to have transposed
        # dimensions here). Treat this value as unconfirmed -- do not
        # assume it's already correct, and do not assume it shares either
        # of the other two products' aspect ratio.
        "item_label": _dim("12x4.125"),
        "box_label": None,
        "box_quantity": None,
        "pallet_quantity": 9,
    },
    "Aerosol Can": {
        # Width/height were transposed here -- confirmed against the real
        # blank label template (8.25in wide x 6.5in tall), corrected.
        "item_label": _dim("8.25x6.5"),
        "box_label": _dim("8.25x6.5"),
        "box_quantity": 12,
        "pallet_quantity": 1080,
    },
}


def get_label_dimensions(product_type):
    """Return (width_in, height_in) for the product label canvas."""
    entry = PRODUCT_SIZES.get(product_type)
    if not entry:
        raise KeyError(f"Unknown product type: {product_type!r}")
    dims = entry["item_label"]
    if dims is None:
        raise ValueError(f"No item label dimension defined for {product_type!r}")
    return dims


def list_product_types():
    return list(PRODUCT_SIZES.keys())


if __name__ == "__main__":
    for name in list_product_types():
        try:
            print(f"{name}: {get_label_dimensions(name)} in")
        except ValueError as e:
            print(f"{name}: {e}")
