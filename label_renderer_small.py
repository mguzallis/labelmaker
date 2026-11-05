"""4x2in two-column label (Dual Cartridge item label, small format).

Same look as the main two-column layout (render_label) but condensed to fit a
2in tall label: the left box carries Signal Word + Hazard Statements (no
precautionary statements -- a short "see SDS" line stands in), the right box
carries the selected Directions plus a one-paragraph Storage and Disposal.
Drawn fresh on the vertical's background art (no baked template needed), so it
works for every vertical.
"""
import os
import re

from PIL import Image, ImageDraw, ImageOps

from layout_config import (
    COLOR_NAVY, COLOR_GREY_BOX, COLOR_WHITE, COLOR_DARK_TEXT,
    CATEGORY_ACCENT_COLOR, CATEGORY_LOGO, VERTICAL_BADGE_TEXT_COLOR, DEFAULT_BADGE_TEXT_COLOR,
)
from label_renderer import _font, _apply_text_shadow, Section, fit_and_draw_box

SMALL_DIMENSION = (4, 2)
SEE_SDS_LINE = "See the SDS for precautionary statements, first aid, and full storage and disposal details."


def _first_sentences(text, n=1):
    text = re.sub(r"^\s*Product\s+(?=Dispose)", "", text or "", flags=re.I).strip()
    if not text:
        return ""
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text) if p]
    return " ".join(parts[:n])


def _fit_image(path, box):
    img = Image.open(path).convert("RGBA")
    scale = min((box[2] - box[0]) / img.width, (box[3] - box[1]) / img.height)
    return img.resize((max(int(img.width * scale), 1), max(int(img.height * scale), 1)), Image.LANCZOS)


def render_small_label(
    *, canvas_size_in, background_path, vertical_name, category, sds_data,
    tds_bullets_selected, product_name, sales_description_1, sales_description_2,
    product_code, size_label, badge_color=None, badge_icon_path=None,
    internal_label_number=None, lot_number="LOT#", output_path=None, dpi=300,
    **_ignored,
):
    w_in, h_in = canvas_size_in
    W, H = 1200, 600   # fixed working grid (4x2 at 300dpi); resized at the end if dpi differs
    canvas = ImageOps.fit(Image.open(background_path).convert("RGB"), (W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    accent = CATEGORY_ACCENT_COLOR.get(category, CATEGORY_ACCENT_COLOR["Adhesive"])
    code_color = VERTICAL_BADGE_TEXT_COLOR.get(vertical_name, DEFAULT_BADGE_TEXT_COLOR)

    # ---- top: logo | vertical name + badge pill + product name
    logo = _fit_image(CATEGORY_LOGO[category], (20, 14, 430, 200))
    canvas.paste(logo, (20 + (410 - logo.width) // 2, 14 + (186 - logo.height) // 2), logo)

    vf = _font("kallisto", 40)
    vw = vf.getlength(vertical_name)
    px0, px1, py0, py1 = 520, 1075, 66, 142
    items = [((int(785 - vw / 2), 12), vertical_name, vf)]
    pf = _font("bold", 30)
    pn_lines = []
    cur = ""
    for wd in (product_name or "").split():
        t = (cur + " " + wd).strip()
        if pf.getlength(t) <= 620:
            cur = t
        else:
            pn_lines.append(cur); cur = wd
    pn_lines.append(cur)
    pn_lines = pn_lines[:2]
    for i, l in enumerate(pn_lines):
        items.append(((int(785 - pf.getlength(l) / 2), 150 + i * 34), l, pf))
    canvas = _apply_text_shadow(canvas, items, W, H)
    draw = ImageDraw.Draw(canvas)
    draw.text(items[0][0], vertical_name, font=vf, fill=COLOR_WHITE)
    for (xy, l, f) in items[1:]:
        draw.text(xy, l, font=f, fill=COLOR_WHITE)

    draw.rounded_rectangle((px0, py0, px1, py1), 36, fill=COLOR_WHITE)
    code_avail = (px1 - px0) - 40
    size = 62 if not badge_color else 54
    cf = _font("kallisto", size)
    while cf.getlength(product_code) > code_avail and size > 20:
        size -= 1
        cf = _font("kallisto", size)
    if badge_color:
        sf = _font("kallisto", max(int(size * 0.42), 14))
        bb = cf.getbbox(product_code); sb = sf.getbbox(badge_color.upper())
        total = (bb[3] - bb[1]) + 8 + (sb[3] - sb[1])
        y0 = py0 + ((py1 - py0) - total) // 2
        draw.text(((px0 + px1) // 2 - cf.getlength(product_code) / 2, y0 - bb[1]), product_code, font=cf, fill=code_color)
        draw.text(((px0 + px1) // 2 - sf.getlength(badge_color.upper()) / 2, y0 + (bb[3] - bb[1]) + 8 - sb[1]),
                  badge_color.upper(), font=sf, fill=code_color)
    else:
        draw.text(((px0 + px1) // 2, (py0 + py1) // 2), product_code, font=cf, fill=code_color, anchor="mm")
    if badge_icon_path and os.path.exists(badge_icon_path):
        icon = Image.open(badge_icon_path).convert("RGBA").resize((150, 150), Image.LANCZOS)
        canvas.paste(icon, (1030, 34), icon)
        draw = ImageDraw.Draw(canvas)

    # ---- orange bars
    bar_f = _font("bold", 20)
    for (x0, x1, text) in ((12, 590, sales_description_1), (610, 1188, sales_description_2)):
        draw.rounded_rectangle((x0, 212, x1, 248), 6, fill=accent)
        t = (text or "").upper()
        s = 20
        f = bar_f
        while f.getlength(t) > (x1 - x0) - 24 and s > 12:
            s -= 1; f = _font("bold", s)
        draw.text(((x0 + x1) // 2, 230), t, font=f, fill=COLOR_WHITE, anchor="mm")

    # ---- grey boxes
    LB = (12, 258, 590, 520)
    RB = (610, 258, 1188, 520)
    for b in (LB, RB):
        draw.rounded_rectangle(b, 8, fill=COLOR_GREY_BOX)

    sds = sds_data or {}
    hazards = [h["text"] for h in sds.get("hazard_statements", []) if h.get("text")]
    left_sections = []
    if sds.get("signal_word"):
        left_sections.append(Section("SIGNAL WORD", sds["signal_word"].upper(), kind="text", protected=True))
    if hazards:
        left_sections.append(Section("HAZARD STATEMENTS", hazards, kind="bulleted", bullet="", protected=True))
    left_sections.append(Section("", SEE_SDS_LINE, kind="text", body_bold=True, protected=True))

    right_sections = [
        Section("DIRECTIONS FOR USE", "FOR INDUSTRIAL USE ONLY", kind="text", protected=True, body_bold=True),
        Section("", tds_bullets_selected, kind="bulleted", protected=True),
    ]
    sd = " ".join(x for x in (_first_sentences(sds.get("storage"), 1), _first_sentences(sds.get("disposal"), 1)) if x)
    if sd:
        right_sections.append(Section("STORAGE AND DISPOSAL", sd, kind="text"))

    pics = list(sds.get("pictograms", []))
    pic_size = 70 if len(pics) <= 4 else 58
    has_usa = category in ("Adhesive", "Sealant")
    pic_col_w = 216 if (pics or has_usa) else 0   # wide enough for the two-line USA disclaimer
    hdr, body = int(0.027 * H), int(0.0225 * H)
    # same scale for both boxes, like the main layout
    ls, _, _ = fit_and_draw_box(None, LB, left_sections, hdr, body, LB[2] - LB[0] - 24,
                                fill_header=accent, min_scale=0.7, measure_only=True)
    rs, _, _ = fit_and_draw_box(None, RB, right_sections, hdr, body, RB[2] - RB[0] - pic_col_w - 24,
                                fill_header=accent, min_scale=0.7, measure_only=True)
    shared = min(ls, rs)
    _, _, dl = fit_and_draw_box(draw, LB, left_sections, hdr, body, LB[2] - LB[0] - 24,
                                fill_header=accent, min_scale=0.7, forced_scale=shared)
    _, _, dr = fit_and_draw_box(draw, RB, right_sections, hdr, body, RB[2] - RB[0] - pic_col_w - 24,
                                fill_header=accent, min_scale=0.7, forced_scale=shared)

    # ---- pictograms + Made in USA badge/disclaimer (right edge of right box)
    pdir = "pictograms"
    DIS = ["*Manufactured in the USA with domestic", "and limited foreign- sourced components."]
    dfont = _font("regular", 10)
    col_w = pic_col_w
    cx_mid = RB[2] - 10 - col_w / 2
    usa_top = RB[3] - 8
    if has_usa:
        dis_h = len(DIS) * 12
        usa = _fit_image("assets/made_in_usa_badge.png", (0, 0, 120, 56))
        usa_y = RB[3] - 8 - dis_h - 3 - usa.height
        canvas.paste(usa, (int(cx_mid - usa.width / 2), usa_y), usa)
        dy = usa_y + usa.height + 3
        for line in DIS:
            lw = dfont.getlength(line)
            draw.text((max(RB[0] + 8, min(cx_mid - lw / 2, RB[2] - 6 - lw)), dy), line, font=dfont, fill=COLOR_DARK_TEXT)
            dy += 12
        usa_top = usa_y
    rows_n = (len(pics) + 1) // 2
    block_h = rows_n * pic_size + max(rows_n - 1, 0) * 4
    y = RB[1] + max(((usa_top - 6) - RB[1] - block_h) // 2, 6)   # vertically centred above the badge
    for i, code in enumerate(pics):
        cand = [f for f in os.listdir(pdir) if f.startswith(code)]
        if not cand:
            continue
        img = Image.open(os.path.join(pdir, cand[0])).convert("RGBA").resize((pic_size, pic_size), Image.LANCZOS)
        col, row = i % 2, i // 2
        n_in_row = 2 if (row + 1) * 2 <= len(pics) else len(pics) - row * 2
        row_w = n_in_row * pic_size + (n_in_row - 1) * 12
        canvas.paste(img, (int(cx_mid - row_w / 2 + col * (pic_size + 12)), y + row * (pic_size + 4)), img)

    # ---- footer
    ff = _font("kallisto", 22)
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 552), size_label, font=ff, fill=COLOR_WHITE)
    draw.text((330, 552), f"{internal_label_number or product_code}    {lot_number}", font=ff, fill=COLOR_WHITE)
    fl = _fit_image("assets/footer_logo.png", (860, 530, 1190, 596))
    canvas.paste(fl, (1190 - fl.width, 596 - fl.height), fl)

    final = (round(w_in * dpi), round(h_in * dpi))
    if final != (W, H):
        canvas = canvas.resize(final, Image.LANCZOS)
    if output_path:
        canvas.save(output_path)
    return canvas, {"left": dl, "right": dr}
