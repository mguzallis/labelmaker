"""
Shared label layout config.

Field zone positions below were measured directly from the Industrial
reference template (preview_page0.png, 1238x938px @ ~150dpi for an
8.25x6.25in canvas) by scanning for the actual brand colors (orange bars,
grey content boxes, navy header/footer) rather than eyeballed -- see the
detection commands run during development. Storing them as FRACTIONS of
canvas width/height (not fixed pixels) is what makes this layout reusable
across every dimension group and vertical: multiply by whatever canvas
size a given product's label needs.

This is the "shared field layout" that Construction (and future
verticals) reuse -- only the background art and logo swap per vertical,
per the plan confirmed for Construction.
"""

# Brand colors, per official Forza Brand Standards (Nov 2025)
COLOR_REGAL_BLUE = (27, 55, 100)     # #1B3764 -- primary navy
COLOR_BLAZE_ORANGE = (241, 97, 35)   # #F16022 -- primary orange / BOND accent
COLOR_NAVY = COLOR_REGAL_BLUE        # header/footer background
COLOR_ORANGE = COLOR_BLAZE_ORANGE    # section header bars (Adhesive/BOND default)
COLOR_GREY_BOX = (198, 201, 211)     # content box background (sampled, not in brand doc)
COLOR_WHITE = (255, 255, 255)
COLOR_DARK_TEXT = (30, 30, 30)

# Badge box text color (product code + color line) -- confirmed DIRECTLY
# from real product photos to vary, but NOT simply by vertical or by
# category (Marine and this Industrial example are both "Forza BOND," yet
# Marine's real label uses teal while two different Industrial products
# (a 5-gal pail and a cartridge) both use navy). The Brand Standards doc's
# "Industry Standards" pages list a hex per vertical, but that hex is
# evidently NOT always what's used for badge text -- don't generalize
# from a single confirmed example again. Only Marine is set here because
# only Marine has been directly confirmed against a real label; every
# other vertical defaults to navy until confirmed the same way.
VERTICAL_BADGE_TEXT_COLOR = {
    "Marine": (19, 120, 117),  # #137875 -- confirmed against a real Marine label (MC736)
}
DEFAULT_BADGE_TEXT_COLOR = COLOR_NAVY

# Per-category accent color, per brand standards "Product Standards" pages --
# each product line (BOND/SEAL/TAPE/COAT/CLEAN) has its own accent color used
# for its wordmark and the label's benefit bar / section headers. Category
# here maps Adhesive->BOND, Sealant->SEAL, Tape->TAPE (Forza's product-line
# names), which is distinct from the vertical (Industrial/Marine/etc).
CATEGORY_ACCENT_COLOR = {
    "Adhesive": (241, 96, 34),   # BOND -- #F16022
    "Sealant": (250, 175, 64),   # SEAL -- #FAAF40
    "Tape": (209, 24, 31),       # TAPE -- #D1181F
}

# Category -> logo lockup file (eagle + Forza + BOND/SEAL/TAPE), extracted
# from the official brand standards PDF. Per brand standards, the logo does
# NOT vary by vertical -- only by product category -- so this replaces any
# per-vertical logo asset.
CATEGORY_LOGO = {
    "Adhesive": "logos/eagle_bond_lockup.png",
    "Sealant": "logos/eagle_seal_lockup.png",
    "Tape": "logos/eagle_tape_lockup.png",
}

# All zones as (x0, y0, x1, y1) fractions of full canvas width/height
ZONES = {
    # Top navy header area, before the orange bars
    "header": (0.0, 0.0, 1.0, 0.500),
    # Logo lockup sits in the left portion of the header
    "logo": (0.008, 0.095, 0.47, 0.32),
    # --- Label Icon Lockup (industry name + product code pill + icon +
    # product type), per official brand standards "Label Icon Lockups"
    # spec. This sits directly on the background -- no container box.
    # A thin accent-colored divider line runs full width just below the
    # logo, then the lockup starts at the same left margin as the logo.
    # Vertical name label (e.g. "Industrial") -- exact position measured
    # directly from the real Industrial .ai template.
    "vertical_name": (0.4923, 0.0862, 0.80, 0.1773),
    # White badge box with manual product-line code/color (e.g. "OS2 /
    # WHITE") + circular vertical-icon overlapping its top-right corner --
    # this is the REAL structure per the actual .ai template, not the
    # pill/divider-line version I built off the brand standards' "Label
    # Icon Lockup" diagram, which turned out to reflect a different
    # marketing mockup style rather than the actual working template.
    "badge": (0.4896, 0.1867, 0.9071, 0.32),
    # Product name/type, large text under the badge
    "product_name": (0.49, 0.335, 0.90, 0.395),

    # Orange section header bars
    # Moved up from 0.500/0.555 -- per direct feedback, there was a large
    # unused gap between product_name and these bars. New position still
    # reserves real clearance for product_name to wrap to two lines
    # (~41pt estimated need, ~54pt actually reserved).
    "orange_bar_left": (0.0186, 0.4167, 0.4330, 0.4718),
    "orange_bar_right": (0.4506, 0.4167, 0.9774, 0.4718),

    # Grey content boxes below the orange bars
    # Box top moved up (0.575 -> 0.4917) to match the bars' new position;
    # bottom unchanged, so boxes are now taller -- more room for content,
    # which was the other half of the same feedback.
    "box_left": (0.0186, 0.4917, 0.4330, 0.895),   # Signal word / hazard / precautionary
    "box_right": (0.4506, 0.4917, 0.9774, 0.895),  # Directions / storage / disposal / pictograms

    # Footer strip
    "footer": (0.0, 0.915, 1.0, 1.0),
    "footer_size_label": (0.0324, 0.9110, 0.35, 0.97),
    "footer_product_code": (0.2707, 0.9110, 0.65, 0.97),
    "footer_contact": (0.68, 0.915, 0.98, 1.0),

    # Pictogram row + Made in USA badge, bottom-right corner of box_right
    # NOT actually read by render_compact_label() -- that function computes
    # pictogram position/size procedurally (pic_col_w as a ratio of
    # box_right's own width, see label_renderer.py) rather than looking up
    # this zone. Kept here as a real, verified reference position (useful
    # for e.g. visual debugging/overlay checks) but changing this value
    # alone will NOT move where pictograms actually render -- change the
    # ratio constant in render_compact_label() for that.
    "pictograms": (0.80, 0.675, 0.975, 0.765),
    "made_in_usa": (0.80, 0.785, 0.975, 0.855),
}

# All fonts actually used (Kallisto, Co Text, Poppins) ship inside this
# package's own fonts/ directory, resolved relative to this file's
# location so the app works on any machine, regardless of what system
# fonts happen to be installed or what directory it's run from --
# nothing here depends on the user's OS having Google Fonts or
# Montserrat available. Poppins-Bold specifically is brand-critical (the
# orange/gold/red sales-description bar text on every label uses it),
# so it needed bundling just as much as Kallisto did.
import os as _os
_PACKAGE_DIR = _os.path.dirname(_os.path.abspath(__file__))
_FONTS_DIR = _os.path.join(_PACKAGE_DIR, "fonts")
FONTS = {
    "bold": _os.path.join(_FONTS_DIR, "Poppins-Bold.ttf"),
    "semibold": _os.path.join(_FONTS_DIR, "Poppins-Medium.ttf"),
    "regular": _os.path.join(_FONTS_DIR, "Poppins-Regular.ttf"),
    "kallisto": _os.path.join(_FONTS_DIR, "Kallisto-Heavy.otf"),  # real brand header font
    "cotext_bold": _os.path.join(_FONTS_DIR, "Co_Text_Bold.otf"),  # real font for the footer address block
    "cotext_regular": _os.path.join(_FONTS_DIR, "Co_Text.otf"),
    "cotext_light": _os.path.join(_FONTS_DIR, "Co_Text_Light.otf"),
}


def zone_px(name, canvas_w, canvas_h):
    """Convert a named zone's fractional bbox to pixel coordinates for a
    given canvas size."""
    x0, y0, x1, y1 = ZONES[name]
    return (
        round(x0 * canvas_w), round(y0 * canvas_h),
        round(x1 * canvas_w), round(y1 * canvas_h),
    )


# The main two-column layout's grey boxes and orange bars are now
# standardized to Marine's exact position for every vertical (see
# ZONES["box_left"]/["box_right"] and the orange-bar drawing code) -- but
# the badge box itself was NOT moved to match; each vertical's real blank
# template has its own native badge box position/size, baked in as-is
# rather than redrawn, so product-code text needs to be positioned
# against THAT real position, not Marine's. Measured directly from each
# vertical's real reference label (per dimension group -- badge position
# varies by aspect ratio, same reasoning as the compact layout's
# per-dimension-group zones). Keyed by (vertical_name, dimension_group).
# Per-vertical override for bar/box fractions -- bars now draw
# dynamically (for Adhesive/Sealant color-swap), using ZONES["orange_bar_
# left/right"] as a generic default. When a vertical's real, measured bar
# position differs from that generic fraction (confirmed for Industrial,
# whose real blank has its bar ~18pt lower than the generic position),
# the dynamic bar would misalign with the already-baked-in grey box
# below it. Entries here override both the bar's drawn position AND the
# box's text-positioning fraction (the box SHAPE itself stays baked in;
# this only affects where dynamic content is positioned relative to it).
BAR_BOX_ZONES_BY_VERTICAL = {
    ('Industrial', '8x6'): {
        'orange_bar_left': (0.0186, 0.4589, 0.4350, 0.5155),
        'orange_bar_right': (0.4506, 0.4589, 0.9721, 0.5155),
        'box_left': (0.0186, 0.5355, 0.4350, 0.8949),
        'box_right': (0.4506, 0.5355, 0.9721, 0.8949),
    },
    ('Industrial', '8x8'): {
        'orange_bar_left': (0.0186, 0.4929, 0.4330, 0.5421),
        'orange_bar_right': (0.4506, 0.4929, 0.9774, 0.5421),
        'box_left': (0.0186, 0.5620, 0.4330, 0.8950),
        'box_right': (0.4506, 0.5620, 0.9774, 0.8950),
    },
    ('Composites', '8x6'): {
        'orange_bar_left': (0.0186, 0.5328, 0.4330, 0.5894),
        'orange_bar_right': (0.4506, 0.5328, 0.9774, 0.5894),
        'box_left': (0.0186, 0.6093, 0.4330, 0.8949),
        'box_right': (0.4506, 0.6093, 0.9774, 0.8949),
    },
    ('Composites', '8x8'): {
        'orange_bar_left': (0.0186, 0.4929, 0.4330, 0.5421),
        'orange_bar_right': (0.4506, 0.4929, 0.9774, 0.5421),
        'box_left': (0.0186, 0.5620, 0.4330, 0.8950),
        'box_right': (0.4506, 0.5620, 0.9774, 0.8950),
    },
    ('Composites', '8.25x6.25'): {
        'orange_bar_left': (0.0186, 0.3125, 0.4330, 0.3611),
        'orange_bar_right': (0.4506, 0.3125, 0.9774, 0.3611),
        'box_left': (0.0186, 0.3811, 0.4330, 0.8950),
        'box_right': (0.4506, 0.3811, 0.9774, 0.8950),
    },
}


def bar_box_zone_px(name, vertical_name, dimension_group, canvas_w, canvas_h):
    """Like zone_px, but checks BAR_BOX_ZONES_BY_VERTICAL for a
    vertical-specific override first, falling back to the generic ZONES
    fraction when none exists (the common case -- most verticals' real
    bar/box positions already match the generic fraction)."""
    override = BAR_BOX_ZONES_BY_VERTICAL.get((vertical_name, dimension_group), {})
    fractions = override.get(name, ZONES[name])
    x0, y0, x1, y1 = fractions
    return (
        round(x0 * canvas_w), round(y0 * canvas_h),
        round(x1 * canvas_w), round(y1 * canvas_h),
    )


BADGE_ZONES_BY_VERTICAL = {
    ('Industrial','8x8'): (0.5575, 0.0879, 0.8304, 0.1821),  # measured directly from the real blank PDF (AP702), corrected
    ('Composites','8x8'): (0.528, 0.1921, 0.838, 0.2958),  # measured directly from the real blank PDF (AP1156)
    ('Composites','8.25x6.25'): (0.687, 0.1557, 0.895, 0.2469),  # measured directly from the real blank PDF (AP1158)
    ('Industrial','8x6'): (0.4898, 0.1894, 0.8538, 0.3238),
    ('Industrial','6x4'): (0.4905, 0.1552, 0.8530, 0.3059),
    ('Industrial','8.25x6.25'): (0.4926, 0.1807, 0.8678, 0.3180),
    # Industrial's own 8x8 reference used an anomalous 3-column layout
    # (see HANDOFF_SUMMARY/label-generator notes) -- no real badge
    # position to measure, so this one deliberately has no entry and
    # falls back to Marine's.
    ('Transportation','8x6'): (0.4898, 0.1894, 0.8538, 0.3238),
    ('Transportation','8x8'): (0.5054, 0.2352, 0.8380, 0.3274),
    ('Transportation','6x4'): (0.4905, 0.1552, 0.8530, 0.3059),
    ('Transportation','8.25x6.25'): (0.4918, 0.1756, 0.8702, 0.3140),
    ('Composites','8x6'): (0.4894, 0.1866, 0.8538, 0.3211),
    ('Composites','6x4'): (0.5438, 0.1403, 0.8757, 0.2781),
    # Composites' own 8x8 and 8.25x6.25 references used anomalous
    # layouts too -- same reasoning, no entry, falls back to Marine's.
    ('Construction','8x6'): (0.5406, 0.1537, 0.8715, 0.2759),
    ('Construction','8x8'): (0.5312, 0.2099, 0.8663, 0.3028),
    ('Construction','6x4'): (0.5366, 0.1299, 0.8683, 0.2677),
    ('Construction','8.25x6.25'): (0.5301, 0.1647, 0.8680, 0.2882),
    ('Insulation','8x6'): (0.4910, 0.1884, 0.8637, 0.3259),
    ('Insulation','6x4'): (0.4900, 0.1785, 0.8519, 0.3288),
    ('Insulation','8.25x6.25'): (0.4907, 0.1869, 0.8751, 0.3276),
    # Insulation has no 8x8 product at all -- no entry needed.
}


# Same reasoning as BADGE_ZONES_BY_VERTICAL -- each vertical's real icon
# graphic (factory, hard hat, truck, etc.) is baked at its own native
# position, not computed from the icon_size/icon_center_x formula (which
# was calibrated against Marine's own badge box proportions). That
# formula's output -- specifically icon_x -- feeds directly into the
# product-code text's avail_w calculation, so a wrong icon_x silently
# shrinks or enlarges the calibrated code font size too. Measured
# directly from each vertical's real reference image. Composites has no
# entry (its icon graphic's bounding box isn't roughly square, unlike
# every other vertical's, so the same measurement approach didn't apply
# cleanly) -- falls back to the formula for Composites specifically.
ICON_ZONES_BY_VERTICAL = {
    ('Industrial','8x6'): (0.7641, 0.1005, 0.9498, 0.3481),
    ('Industrial','6x4'): (0.7637, 0.0556, 0.9486, 0.3330),
    ('Industrial','8.25x6.25'): (0.7753, 0.0900, 0.9668, 0.3427),
    ('Transportation','8x6'): (0.7710, 0.0799, 0.9885, 0.3699),
    ('Transportation','8x8'): (0.7625, 0.1708, 0.9497, 0.3582),
    ('Transportation','6x4'): (0.7708, 0.0500, 0.9748, 0.3559),
    ('Transportation','8.25x6.25'): (0.7768, 0.0987, 0.9672, 0.3498),
    ('Construction','8x6'): (0.7748, 0.0630, 0.9819, 0.3387),
    ('Construction','8x8'): (0.7689, 0.1410, 0.9778, 0.3498),
    ('Construction','6x4'): (0.7613, 0.0153, 0.9887, 0.3556),
    ('Construction','8.25x6.25'): (0.7705, 0.0740, 0.9791, 0.3491),
    ('Insulation','8x6'): (0.7769, 0.1162, 0.9632, 0.3646),
    ('Insulation','6x4'): (0.7676, 0.0997, 0.9484, 0.3708),
    ('Insulation','8.25x6.25'): (0.7855, 0.1133, 0.9776, 0.3669),
}


def icon_zone_px(vertical_name, dimension_group, canvas_w, canvas_h):
    """Real measured icon position for vertical+dimension_group, or None
    if unmeasured (Marine, or a vertical/size without a usable
    measurement) -- callers should fall back to the formula-based
    icon_x/icon_size calculation in that case."""
    fractions = ICON_ZONES_BY_VERTICAL.get((vertical_name, dimension_group))
    if fractions is None:
        return None
    x0, y0, x1, y1 = fractions
    return (
        round(x0 * canvas_w), round(y0 * canvas_h),
        round(x1 * canvas_w), round(y1 * canvas_h),
    )


def badge_zone_px(vertical_name, dimension_group, canvas_w, canvas_h):
    """Same idea as zone_px, but for the main layout's badge box
    specifically -- looks up the real measured position for this
    vertical+dimension_group, falling back to Marine's (ZONES["badge"])
    when no measurement exists (Marine itself, or a vertical/size with an
    anomalous reference that couldn't be measured)."""
    fractions = BADGE_ZONES_BY_VERTICAL.get((vertical_name, dimension_group), ZONES["badge"])
    x0, y0, x1, y1 = fractions
    return (
        round(x0 * canvas_w), round(y0 * canvas_h),
        round(x1 * canvas_w), round(y1 * canvas_h),
    )


# Which zone set to use per dimension group. Aerosol Can is the reference
# the fractions were measured from, so it's safe as a fallback -- but that
# fallback is ONLY safe for a dimension group confirmed to share its
# aspect ratio. Aerosol (8.25x6.5, ~1.27:1), 22L Canister (11.693x3.5,
# ~3.34:1), and 108L Canister (12x4.125, ~2.91:1) are three genuinely
# different aspect ratios -- one shared fractional zone set cannot
# produce correct proportions for all three (confirmed both by comparing
# the ratios directly and by each real template's own box/badge/icon
# positions no longer matching COMPACT_ZONES once measured directly).
# All three are now measured from real blank templates and have their own
# dedicated zone set below.
#
# Note one real structural difference between them, not just proportions:
# Aerosol and 22L Canister both place the Made-in-USA badge up near the
# pictograms in box_right (COMPACT_ZONES / COMPACT_ZONES_22L's
# "made_in_usa" zone). 108L Canister's real template instead places it as
# a small badge in box_left's footer, next to the Forza logo
# (COMPACT_ZONES_108L's "footer_usa_badge_fixed") -- it has no
# "made_in_usa" zone in box_right at all. Don't assume one convention for
# a product using this zone set without checking which its own template
# actually uses.
COMPACT_ZONE_SET_BY_DIMENSION_GROUP = {
    # Keyed by dimension-group string (e.g. "8.25x6.5", matching
    # template_config.DIMENSION_GROUPS / product_sizes.get_label_dimensions),
    # NOT by product type name -- this dict was originally keyed by product
    # name ("22L Canister" etc.) despite its own name saying "dimension
    # group", which silently broke the first real call to
    # compact_zone_px(dimension_group=...) with an actual dimension string.
    # Since each of these three products currently has a 1:1 unique
    # dimension group, this happens to only be a naming fix, not a
    # behavior change -- but if a second product ever shared one of these
    # dimension groups, keying by product name would have been wrong
    # regardless (it would need the SAME zone set as whichever product it
    # shares dimensions with, which is exactly what dimension-group keying
    # already gets you for free).
    "8.25x6.5": "COMPACT_ZONES",       # Aerosol Can
    "11.5x3.5": "COMPACT_ZONES_22L",   # 22L Canister
    "12x4.125": "COMPACT_ZONES_108L",  # 108L Canister
}


def compact_zone_px(name, canvas_w, canvas_h, dimension_group=None):
    """Same as zone_px, but for the compact three-column layout (Aerosol/
    22L/108L Canister), which is structurally different enough from the
    main template that it needs its own zone set.

    dimension_group selects which measured zone set to use (products with
    different aspect ratios need their own set -- a single shared
    fractional zone set only produces correct proportions for the exact
    aspect ratio it was measured from). Pass the dimension-group string
    (e.g. \"11.5x3.5\", matching template_config.DIMENSION_GROUPS /
    product_sizes.get_label_dimensions -- NOT a product type name);
    omitting it falls back to the original Aerosol-measured
    COMPACT_ZONES for backward compatibility, which is only correct for
    that exact 8.25x6.5 aspect ratio.
    """
    if dimension_group is not None:
        set_name = COMPACT_ZONE_SET_BY_DIMENSION_GROUP.get(dimension_group)
        if set_name is None:
            raise ValueError(
                f"No measured compact-layout zone set for {dimension_group!r}. "
                "Reusing another dimension group's zones here would silently "
                "misplace every element (see COMPACT_ZONE_SET_BY_DIMENSION_GROUP "
                "comment) -- a real blank template needs to be measured first."
            )
        zones = globals()[set_name]
    else:
        zones = COMPACT_ZONES
    x0, y0, x1, y1 = zones[name]
    return (
        round(x0 * canvas_w), round(y0 * canvas_h),
        round(x1 * canvas_w), round(y1 * canvas_h),
    )


# Measured directly from a real label PDF (AP1593, 13oz Aerosol Box Label,
# 594x468pt = 8.25x6.5in). This is the Aerosol Can zone set ONLY.
# Earlier comments here claimed this same layout applies to 22L and 108L
# Canister too -- that turned out to be wrong (see
# COMPACT_ZONE_SET_BY_DIMENSION_GROUP above): those two are different
# aspect ratios and need their own measured zone sets, not this one.
COMPACT_ZONES = {
    "left_box": (0.0257, 0.0565, 0.3056, 0.9365),
    "right_box": (0.6977, 0.0565, 0.9777, 0.9365),
    "logo_lockup": (0.3409, 0.2378, 0.6843, 0.4301),
    "orange_divider": (0.3058, 0.4629, 0.6977, 0.4680),
    "vertical_name": (0.3411, 0.4940, 0.6037, 0.5711),  # widened right edge -- real doc's is tight to "Marine" specifically, ours needs room for longer names
    "badge_box": (0.3389, 0.5700, 0.6037, 0.6631),
    "boat_icon": (0.5384, 0.5190, 0.6730, 0.6899),  # "boat_icon" name kept for traceability to source measurement; holds whatever vertical icon is passed in
    "product_name": (0.3388, 0.6760, 0.6626, 0.7065),
    "orange_bar": (0.3057, 0.7653, 0.6978, 0.8255),
    "size_text": (0.3388, 0.8578, 0.6037, 0.8778),  # x0 shifted to left-align under badge box rather than the source's centered position, matching main template convention
    "qty_text": (0.3388, 0.8833, 0.6037, 0.9033),
    "footer_ap": (0.1327, 0.9486, 0.2500, 0.9622),
    "footer_lot": (0.8245, 0.9486, 0.9500, 0.9622),
    "left_header1": (0.0375, 0.0666, 0.2900, 0.0990),
    "left_header2": (0.0375, 0.5132, 0.2900, 0.5455),
    "right_header1": (0.7076, 0.0685, 0.9600, 0.1009),
    "right_header2": (0.7076, 0.1303, 0.9600, 0.1626),
    "right_header3": (0.7076, 0.3216, 0.9600, 0.3540),
    "contains_header": (0.7073, 0.7959, 0.9600, 0.8258),
    "forza_inc": (0.0381, 0.8668, 0.2900, 0.9200),
    # Fixed footer block (logo, address, USA badge) -- measured directly
    # from the real label and meant to NEVER move regardless of content,
    # per explicit instruction that these three always sit in the same
    # spot.
    "footer_logo_fixed": (0.0303, 0.8162, 0.1515, 0.8568),
    "footer_address_fixed": (0.0381, 0.8667, 0.2900, 0.9350),
    "footer_usa_badge_fixed": (0.1852, 0.8120, 0.2660, 0.8632),
}

# 22L Canister's own zone set. Now measured directly from a real FILLED
# reference label (22L_template.pdf, MC722 Marine Non-Flammable Contact
# Adhesive), which confirmed something the earlier blank template
# couldn't show: the Made-in-USA badge here follows the SAME footer
# convention as 108L Canister (small badge in box_left's footer, next to
# the Forza logo) -- NOT a "made_in_usa" zone up in box_right next to
# pictograms, which is what the box_right transplant placement had
# guessed before this reference existed. logo_lockup is now also a real
# measurement instead of a proportional remap. Only the zones that hold
# dynamic SDS/TDS content not relevant to this specific reference's own
# text (headers, pictograms, size_text, qty_text, footer_ap, footer_lot)
# remain proportionally remapped from COMPACT_ZONES, same method as
# COMPACT_ZONES_108L.
COMPACT_ZONES_22L = {
    # -- measured directly, from the real filled 22L reference --
    "left_box": (0.0779, 0.0464, 0.2901, 0.9123),
    "right_box": (0.7114, 0.0464, 0.9235, 0.9123),
    "badge_box": (0.4217, 0.5877, 0.5675, 0.7226),
    "boat_icon": (0.5315, 0.5139, 0.6057, 0.7617),
    "vertical_name": (0.4229, 0.4778, 0.5308, 0.5893),
    "orange_divider": (0.2901, 0.4698, 0.7114, 0.4794),
    "orange_bar": (0.2901, 0.8341, 0.7114, 0.9032),
    "logo_lockup": (0.3271, 0.0800, 0.6712, 0.4495),
    "footer_logo_fixed": (0.0831, 0.8214, 0.1485, 0.9008),
    "footer_address_fixed": (0.1510, 0.8262, 0.1985, 0.8869),
    "footer_usa_badge_fixed": (0.1663, 0.7778, 0.2708, 0.8929),
    # -- proportionally remapped from COMPACT_ZONES, not directly measured --
    # y-range measured directly from real AP363 ("Non-Flammable Contact
    # Adhesive") -- the old proportionally-remapped y-range overlapped
    # badge_box, which is the actual bug this fixes. x-range widened back
    # out from that same measurement (which only spans this one specific
    # product name's width) so longer product names aren't forced to
    # shrink more than necessary -- the renderer already auto-shrinks
    # text to fit within whatever width is given here.
    "product_name": (0.3258, 0.7291, 0.6737, 0.8200),
    "left_header1": (0.0868, 0.0563, 0.2783, 0.0882),
    "left_header2": (0.0868, 0.4958, 0.2783, 0.5276),
    "right_header1": (0.7189, 0.0582, 0.9101, 0.0901),
    "right_header2": (0.7189, 0.1190, 0.9101, 0.1508),
    "right_header3": (0.7189, 0.3073, 0.9101, 0.3391),
    "contains_header": (0.7187, 0.7740, 0.9101, 0.8034),
    "pictograms": (0.8712, 0.7362, 0.9180, 0.8505),  # measured from real AP363 (2 icons); NOT read by render_compact_label -- see note above the COMPACT_ZONES pictograms entry
    # size_text/footer_lot/footer_ap all measured directly from real
    # AP363, which revealed a real structural difference from Aerosol:
    # these three aren't spread across the label (size in center column,
    # AP-number under left box, LOT# under right box) -- the real 22L
    # design clusters all three together in one row under box_right's
    # right portion. The old proportionally-remapped positions put
    # size_text overlapping orange_bar (and put footer_ap/footer_lot at
    # the wrong ends of the canvas entirely). x-ranges for footer_lot/
    # footer_ap are estimated sub-splits of one combined text span (the
    # real PDF draws "LOT# ... AP363 N2" as a single text run), not
    # independently measured -- reasonable, not exact.
    "size_text": (0.7183, 0.9175, 0.8101, 0.9426),
    "qty_text": (0.3258, 0.8833, 0.6104, 0.9033),
    "footer_lot": (0.8149, 0.9175, 0.8588, 0.9426),
    "footer_ap": (0.8635, 0.9175, 0.9179, 0.9426),
    # No footer_usa_badge_fixed measured or remapped -- the Made-in-USA
    # badge is handled separately for this dimension group via the
    # transplanted badge overlay already baked into
    # marine_3.5x11.693_v1_current.png, not drawn by the renderer.
}

# 108L Canister's own zone set, measured directly from a real blank 108L
# template (12x4.125in canvas, 864x297pt) -- this one HAS its
# Made-in-USA badge, disclaimer text, and full Forza/BOND logo lockup
# baked in already (unlike the 22L blank, which had none of those to
# measure from), so more of this set is directly measured rather than
# proportionally remapped. Only the zones that don't exist as visible
# content on this blank template (headers, pictograms, size_text,
# qty_text, product_name -- all dynamic, SDS/TDS-driven content) are
# remapped from COMPACT_ZONES' position within its own box_left/
# box_right/center-column, same approach as COMPACT_ZONES_22L.
#
# Structural note: this template puts the Made-in-USA badge as a small
# fixed element in box_left's footer (next to the Forza logo), NOT up in
# box_right with the pictograms like Aerosol/22L Canister do -- hence
# "footer_usa_badge_fixed" here instead of a "made_in_usa" zone.
COMPACT_ZONES_108L = {
    # -- measured directly --
    "left_box": (0.0089, 0.0428, 0.2557, 0.9199),
    "right_box": (0.7457, 0.0428, 0.9925, 0.9199),
    "badge_box": (0.4087, 0.5909, 0.5784, 0.7279),
    "boat_icon": (0.5365, 0.5163, 0.6228, 0.7672),
    "vertical_name": (0.4101, 0.4795, 0.5356, 0.5926),
    "orange_divider": (0.2557, 0.4714, 0.7457, 0.4811),
    "orange_bar": (0.2557, 0.8407, 0.7457, 0.9104),
    "logo_lockup": (0.2991, 0.0776, 0.6985, 0.4486),
    "footer_logo_fixed": (0.0214, 0.8360, 0.0874, 0.8889),
    "footer_address_fixed": (0.0939, 0.8327, 0.1491, 0.8939),
    "footer_usa_badge_fixed": (0.1694, 0.7980, 0.2382, 0.8519),
    # -- proportionally remapped from COMPACT_ZONES, not directly measured --
    "left_header1": (0.0193, 0.0529, 0.2419, 0.0852),
    "left_header2": (0.0193, 0.4980, 0.2419, 0.5302),
    "right_header1": (0.7544, 0.0548, 0.9769, 0.0871),
    "right_header2": (0.7544, 0.1164, 0.9769, 0.1486),
    "right_header3": (0.7544, 0.3070, 0.9769, 0.3393),
    "contains_header": (0.7542, 0.7798, 0.9769, 0.8096),
    "pictograms": (0.9316, 0.7414, 0.9860, 0.8571),  # measured from real AP402 (2 icons); NOT read by render_compact_label -- see note above the COMPACT_ZONES pictograms entry
    # size_text/footer_lot/footer_ap all measured directly from real
    # AP402 -- same real structural difference from Aerosol documented
    # in COMPACT_ZONES_22L's equivalent comment (all three cluster
    # together under box_right instead of spreading across the label).
    "size_text": (0.7537, 0.9250, 0.8334, 0.9505),
    "qty_text": (0.2972, 0.8833, 0.6282, 0.9033),
    # Same fix as COMPACT_ZONES_22L's product_name -- y-range measured
    # directly from real AP402, x-range widened back out for longer names.
    "product_name": (0.2972, 0.7342, 0.7018, 0.8263),
    "footer_lot": (0.8899, 0.9250, 0.9250, 0.9505),
    "footer_ap": (0.9296, 0.9250, 0.9901, 0.9505),
}
