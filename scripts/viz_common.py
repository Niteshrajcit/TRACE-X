"""Shared drawing helpers for TRACE-X slide visuals (Pillow-based, flat icon style)."""
from PIL import Image, ImageDraw, ImageFont

# ---- Palette (drawn from the template's own theme + accent, nothing new introduced) ----
BLUE = (0, 112, 192)          # 0070C0 - the template's real accent (footer band)
NAVY = (31, 73, 125)          # 1F497D - theme dk2 (title-slide heading color)
NAVY_DARK = (20, 48, 82)
RED = (192, 80, 77)           # C0504D - theme accent2 (used sparingly: risk / "today")
GREEN = (60, 140, 90)         # success/positive accent, muted
DARK = (34, 34, 34)
GRAY = (120, 128, 140)
GRAY_LIGHT = (232, 236, 241)
GRAY_MED = (176, 183, 195)
WHITE = (255, 255, 255)

FONT_DIR = "C:/Windows/Fonts/"


def font(name, size):
    paths = {
        "arial": "arial.ttf", "arialbd": "arialbd.ttf", "ariali": "ariali.ttf",
        "times": "times.ttf", "timesbd": "timesbd.ttf",
    }
    return ImageFont.truetype(FONT_DIR + paths[name], size)


def new_canvas(w, h, bg=WHITE):
    img = Image.new("RGB", (w, h), bg)
    return img, ImageDraw.Draw(img)


def text_center(draw, xy, text, fnt, fill=DARK, anchor="mm"):
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)


def wrap_text(text, fnt, max_width, draw):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_multiline_center(draw, cx, top_y, lines, fnt, fill=DARK, line_gap=1.25):
    asc, desc = fnt.getmetrics()
    lh = int((asc + desc) * line_gap)
    for i, ln in enumerate(lines):
        draw.text((cx, top_y + i * lh), ln, font=fnt, fill=fill, anchor="ma")


def rrect(draw, box, radius, fill=None, outline=None, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def arrow_h(draw, x1, x2, y, color=GRAY, width=6, head=16):
    draw.line([(x1, y), (x2 - head, y)], fill=color, width=width)
    draw.polygon([(x2, y), (x2 - head, y - head * 0.6), (x2 - head, y + head * 0.6)], fill=color)


def circle_icon_bg(draw, cx, cy, r, fill, outline=None, owidth=4):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=outline, width=owidth)


# ---- Simple flat monochrome glyph icons, drawn with primitives, centered at (cx,cy) ----

def icon_document(draw, cx, cy, s, color):
    w, h = s * 0.7, s * 0.9
    x0, y0 = cx - w / 2, cy - h / 2
    x1, y1 = cx + w / 2, cy + h / 2
    fold = s * 0.22
    draw.polygon([(x0, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, y1), (x0, y1)], outline=color, width=int(s*0.06))
    draw.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=color)
    for i in range(3):
        ly = y0 + h * 0.42 + i * h * 0.16
        draw.line([(x0 + w * 0.16, ly), (x1 - w * 0.16, ly)], fill=color, width=int(s * 0.05))


def icon_magnifier(draw, cx, cy, s, color):
    r = s * 0.32
    ox, oy = cx - s * 0.08, cy - s * 0.08
    draw.ellipse([ox - r, oy - r, ox + r, oy + r], outline=color, width=int(s * 0.09))
    hx1, hy1 = ox + r * 0.75, oy + r * 0.75
    hx2, hy2 = cx + s * 0.34, cy + s * 0.34
    draw.line([(hx1, hy1), (hx2, hy2)], fill=color, width=int(s * 0.12))


def icon_cash(draw, cx, cy, s, color):
    w, h = s * 0.85, s * 0.55
    box = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
    draw.rounded_rectangle(box, radius=int(s*0.06), outline=color, width=int(s * 0.06))
    draw.ellipse([cx - h * 0.28, cy - h * 0.28, cx + h * 0.28, cy + h * 0.28], outline=color, width=int(s * 0.05))


def icon_broken(draw, cx, cy, s, color):
    r = s * 0.4
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=int(s * 0.08))
    d = r * 0.55
    draw.line([(cx - d, cy - d), (cx + d, cy + d)], fill=color, width=int(s * 0.09))
    draw.line([(cx - d, cy + d), (cx + d, cy - d)], fill=color, width=int(s * 0.09))


def icon_network(draw, cx, cy, s, color):
    pts = [(cx, cy - s * 0.38), (cx - s * 0.36, cy + s * 0.2), (cx + s * 0.36, cy + s * 0.2), (cx, cy + s*0.42)]
    for a in pts:
        for b in pts:
            if a != b:
                draw.line([a, b], fill=color, width=max(2, int(s * 0.025)))
    for p in pts:
        rr = s * 0.09
        draw.ellipse([p[0]-rr, p[1]-rr, p[0]+rr, p[1]+rr], fill=color)


def icon_pin(draw, cx, cy, s, color):
    r = s * 0.34
    top = cy - s * 0.42
    draw.pieslice([cx - r, top, cx + r, top + 2 * r], 180, 360, fill=color)
    draw.polygon([(cx - r, top + r), (cx + r, top + r), (cx, cy + s * 0.42)], fill=color)
    hole_r = r * 0.4
    draw.ellipse([cx - hole_r, top + r - hole_r, cx + hole_r, top + r + hole_r], fill=WHITE)


def icon_target(draw, cx, cy, s, color):
    for rr, w in [(s*0.4, s*0.07), (s*0.24, s*0.07)]:
        draw.ellipse([cx-rr, cy-rr, cx+rr, cy+rr], outline=color, width=int(w))
    dr = s * 0.07
    draw.ellipse([cx-dr, cy-dr, cx+dr, cy+dr], fill=color)


def icon_bell(draw, cx, cy, s, color):
    w, h = s * 0.5, s * 0.55
    top = cy - h / 2
    draw.pieslice([cx - w/2, top, cx + w/2, top + w], 180, 360, outline=color, width=int(s*0.07))
    draw.line([(cx - w/2, top + w/2), (cx - w/2 - s*0.05, cy + h*0.18)], fill=color, width=int(s*0.07))
    draw.line([(cx + w/2, top + w/2), (cx + w/2 + s*0.05, cy + h*0.18)], fill=color, width=int(s*0.07))
    draw.line([(cx - w/2 - s*0.05, cy + h*0.18), (cx + w/2 + s*0.05, cy + h*0.18)], fill=color, width=int(s*0.07))
    rr = s * 0.07
    draw.ellipse([cx-rr, cy+h*0.18, cx+rr, cy+h*0.18+2*rr], fill=color)


def icon_shield(draw, cx, cy, s, color):
    w, h = s * 0.6, s * 0.75
    top = cy - h/2
    pts = [(cx-w/2, top), (cx+w/2, top), (cx+w/2, top+h*0.55), (cx, top+h), (cx-w/2, top+h*0.55)]
    draw.polygon(pts, outline=color, width=int(s*0.06))
    draw.line([(cx-w*0.18, top+h*0.42), (cx-w*0.02, top+h*0.6), (cx+w*0.22, top+h*0.28)], fill=color, width=int(s*0.06), joint="curve")


def icon_clock(draw, cx, cy, s, color):
    r = s * 0.4
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=int(s*0.07))
    draw.line([(cx, cy), (cx, cy - r*0.6)], fill=color, width=int(s*0.06))
    draw.line([(cx, cy), (cx + r*0.4, cy + r*0.1)], fill=color, width=int(s*0.06))


def icon_people(draw, cx, cy, s, color):
    for dx in (-s*0.2, s*0.2):
        rr = s * 0.14
        draw.ellipse([cx+dx-rr, cy-s*0.28-rr, cx+dx+rr, cy-s*0.28+rr], fill=color)
        draw.pieslice([cx+dx-s*0.18, cy-s*0.08, cx+dx+s*0.18, cy+s*0.32], 180, 360, fill=color)


def icon_bank(draw, cx, cy, s, color):
    w = s * 0.75
    top = cy - s * 0.35
    draw.polygon([(cx, top), (cx - w/2, top + s*0.18), (cx + w/2, top + s*0.18)], fill=color)
    base_top = top + s * 0.2
    draw.rectangle([cx - w/2, base_top, cx + w/2, base_top + s*0.42], outline=color, width=int(s*0.06))
    for i in range(4):
        lx = cx - w/2 + w*(i+0.5)/4
        draw.line([(lx, base_top), (lx, base_top+s*0.42)], fill=color, width=int(s*0.045))
    draw.line([(cx - w/2 - s*0.06, base_top + s*0.42), (cx + w/2 + s*0.06, base_top + s*0.42)], fill=color, width=int(s*0.06))


def icon_check(draw, cx, cy, s, color):
    r = s * 0.42
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=int(s*0.07))
    draw.line([(cx - r*0.45, cy), (cx - r*0.1, cy + r*0.35), (cx + r*0.5, cy - r*0.35)], fill=color, width=int(s*0.09), joint="curve")


def icon_database(draw, cx, cy, s, color):
    w, h = s * 0.6, s * 0.7
    top = cy - h/2
    rx = w/2
    ry = s * 0.12
    draw.ellipse([cx-rx, top-ry, cx+rx, top+ry], outline=color, width=int(s*0.05))
    draw.line([(cx-rx, top), (cx-rx, top+h)], fill=color, width=int(s*0.05))
    draw.line([(cx+rx, top), (cx+rx, top+h)], fill=color, width=int(s*0.05))
    draw.arc([cx-rx, top+h-ry, cx+rx, top+h+ry], 0, 180, fill=color, width=int(s*0.05))
    for f in (0.33, 0.66):
        yy = top + h*f
        draw.arc([cx-rx, yy-ry, cx+rx, yy+ry], 0, 180, fill=color, width=int(s*0.05))


def icon_chart(draw, cx, cy, s, color):
    base = cy + s * 0.32
    bw = s * 0.16
    heights = [0.3, 0.55, 0.8]
    xs = [cx - s*0.3, cx, cx + s*0.3]
    for x, hh in zip(xs, heights):
        draw.rectangle([x-bw/2, base - s*hh, x+bw/2, base], fill=color)
    draw.line([(cx - s*0.42, base), (cx + s*0.42, base)], fill=color, width=int(s*0.045))
