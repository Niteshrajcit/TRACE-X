import sys
sys.path.insert(0, "E:/TRACE-X/scripts")
from viz_common import *

W, H = 2400, 860
img, d = new_canvas(W, H)

hdr_f = font("arialbd", 30)
body_f = font("arial", 24)
pill_f = font("arialbd", 26)
tag_f = font("arialbd", 24)
sec_f = font("arialbd", 32)

sources = [
    ("NCRB", "National Crime Records Bureau \u2014 annual cybercrime statistics used to calibrate base rates", icon_chart),
    ("I4C", "Indian Cyber Crime Coordination Centre \u2014 aggregate cybercrime reports for typology patterns", icon_shield),
    ("PUBLIC GEO DATA", "Public ATM / branch location registries \u2014 the geospatial layer for cash-out points", icon_pin),
]

d.text((60, 40), "DATA SOURCES", font=sec_f, fill=NAVY, anchor="la")

pill_y0 = 100
pill_h = 130
gap = 26
pw = W - 120
for i, (name, desc, icon_fn) in enumerate(sources):
    y0 = pill_y0 + i*(pill_h+gap)
    y1 = y0 + pill_h
    x0, x1 = 60, 60+pw
    rrect(d, [x0, y0, x1, y1], radius=pill_h//2, fill=GRAY_LIGHT, outline=BLUE, width=3)
    cap_cx = x0 + pill_h/2
    d.ellipse([cap_cx-pill_h/2+8, y0+8, cap_cx+pill_h/2-8, y1-8], fill=BLUE)
    icon_fn(d, cap_cx, (y0+y1)/2, pill_h*0.55, WHITE)
    label_x = x0 + pill_h + 30
    d.text((label_x, y0+38), name, font=pill_f, fill=NAVY, anchor="lm")
    lines = wrap_text(desc, body_f, pw - pill_h - 80, d)
    for j, ln in enumerate(lines[:2]):
        d.text((label_x, y0+78+j*32), ln, font=body_f, fill=DARK, anchor="lm")

# Key terms glossary strip
gy0 = pill_y0 + 3*(pill_h+gap) + 30
d.text((60, gy0), "KEY TERMS", font=sec_f, fill=NAVY, anchor="la")
terms = [
    ("CASH-OUT", "money leaving the traceable banking system"),
    ("CORRIDOR", "the geographic path money tends to move before withdrawal"),
    ("LEAD TIME", "minutes of warning bought before the withdrawal happens"),
]
tag_y = gy0 + 55
tag_h = 150
tw = (W - 120 - 2*30) / 3
for i, (term, desc) in enumerate(terms):
    x0 = 60 + i*(tw+30)
    x1 = x0 + tw
    rrect(d, [x0, tag_y, x1, tag_y+tag_h], radius=16, fill=WHITE, outline=GRAY_MED, width=3)
    d.text((x0+28, tag_y+22), term, font=tag_f, fill=BLUE, anchor="la")
    lines = wrap_text(desc, body_f, tw-56, d)
    for j, ln in enumerate(lines):
        d.text((x0+28, tag_y+68+j*32), ln, font=body_f, fill=DARK, anchor="la")

out = "E:/TRACE-X/analysis/visuals/slide6_references.png"
img.save(out)
print("saved", out)
