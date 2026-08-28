import sys
sys.path.insert(0, "E:/TRACE-X/scripts")
from viz_common import *

W, H = 2400, 860
img, d = new_canvas(W, H)

hdr_f = font("arialbd", 30)
body_f = font("arial", 25)
tag_f = font("arialbd", 22)
road_f = font("arialbd", 24)
road_cap_f = font("arial", 21)

cards = [
    (icon_broken, "RESTRICTED REAL DATA", "Synthetic transaction graphs calibrated\nagainst published NCRB / I4C statistics", RED),
    (icon_chart, "8,000 COMPLAINTS / DAY", "Risk computed per H3 cell, hop-bounded\ngraph queries, batched scoring", BLUE),
    (icon_check, "A WRONG PREDICTION", "Same cost as random patrol \u2014 zero false-\naccusation risk, no autonomous action", BLUE),
    (icon_shield, "GEOGRAPHIC BIAS", "Audited for over-flagging; outputs are\nleads only, human approval required", NAVY),
]

grid_x0, grid_y0 = 60, 30
card_w, card_h = 1120, 260
gap_x, gap_y = 40, 24

for i, (icon_fn, title, body, color) in enumerate(cards):
    row, col = divmod(i, 2)
    x0 = grid_x0 + col*(card_w+gap_x)
    y0 = grid_y0 + row*(card_h+gap_y)
    x1, y1 = x0+card_w, y0+card_h
    rrect(d, [x0,y0,x1,y1], radius=16, fill=GRAY_LIGHT, outline=color, width=4)
    icon_cx, icon_cy = x0+90, y0+card_h/2
    d.ellipse([icon_cx-48, icon_cy-48, icon_cx+48, icon_cy+48], fill=color)
    icon_fn(d, icon_cx, icon_cy, 60, WHITE)
    tx = x0+175
    d.text((tx, y0+48), title, font=hdr_f, fill=NAVY, anchor="lm")
    for j, ln in enumerate(body.split("\n")):
        d.text((tx, y0+98+j*36), ln, font=body_f, fill=DARK, anchor="lm")

# Roadmap strip
road_y0 = grid_y0 + 2*card_h + gap_y + 40
road_y1 = 850
rrect(d, [60, road_y0, W-60, road_y1], radius=16, fill=WHITE, outline=GRAY_LIGHT, width=3)
d.text((100, road_y0+18), "IMPLEMENTATION ROADMAP", font=road_f, fill=NAVY, anchor="la")

steps = ["Foundation", "Intelligence", "Interface", "Optimizer", "Action & Polish"]
line_y = road_y0 + 95
lx0, lx1 = 160, W-160
d.line([(lx0, line_y), (lx1, line_y)], fill=GRAY_MED, width=6)
n = len(steps)
for i, s in enumerate(steps):
    x = lx0 + i*(lx1-lx0)/(n-1)
    d.ellipse([x-24, line_y-24, x+24, line_y+24], fill=BLUE)
    d.text((x, line_y), str(i+1), font=font("arialbd", 22), fill=WHITE, anchor="mm")
    d.text((x, line_y+50), s, font=road_cap_f, fill=DARK, anchor="ma")

out = "E:/TRACE-X/analysis/visuals/slide4_feasibility.png"
img.save(out)
print("saved", out)
