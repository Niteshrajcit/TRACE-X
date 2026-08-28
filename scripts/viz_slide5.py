import sys
sys.path.insert(0, "E:/TRACE-X/scripts")
from viz_common import *

W, H = 2400, 860
img, d = new_canvas(W, H)

card_hdr = font("arialbd", 44)
step_f = font("arialbd", 30)
tag_f = font("arial", 24)
who_hdr = font("arialbd", 28)
who_body = font("arial", 24)

# Two comparison cards, top area
card_y0, card_y1 = 30, 470
card_w = 1120
gap = 40
lx0 = 60
rx0 = lx0 + card_w + gap

# LEFT: WITHOUT
rrect(d, [lx0, card_y0, lx0+card_w, card_y1], radius=18, fill=GRAY_LIGHT, outline=GRAY_MED, width=4)
d.text((lx0+card_w/2, card_y0+55), "WITHOUT TRACE-X", font=card_hdr, fill=GRAY, anchor="mm")
steps_l = ["Money Withdrawn", "Investigation Begins", "Case Goes Cold"]
sy = card_y0 + 150
for i, s in enumerate(steps_l):
    cy = sy + i*100
    d.ellipse([lx0+70-26, cy-26, lx0+70+26, cy+26], outline=GRAY, width=5)
    d.text((lx0+70, cy), str(i+1), font=step_f, fill=GRAY, anchor="mm")
    d.text((lx0+130, cy), s, font=step_f, fill=GRAY, anchor="lm")
    if i < len(steps_l)-1:
        d.line([(lx0+70, cy+26), (lx0+70, cy+74)], fill=GRAY_MED, width=4)

# RIGHT: WITH
rrect(d, [rx0, card_y0, rx0+card_w, card_y1], radius=18, fill=BLUE, outline=BLUE, width=4)
d.text((rx0+card_w/2, card_y0+55), "WITH TRACE-X", font=card_hdr, fill=WHITE, anchor="mm")
steps_r = ["Complaint Filed", "Prediction Generated", "Alert + Intervention"]
for i, s in enumerate(steps_r):
    cy = sy + i*100
    d.ellipse([rx0+70-26, cy-26, rx0+70+26, cy+26], outline=WHITE, width=5)
    d.text((rx0+70, cy), str(i+1), font=step_f, fill=WHITE, anchor="mm")
    d.text((rx0+130, cy), s, font=step_f, fill=WHITE, anchor="lm")
    if i < len(steps_r)-1:
        d.line([(rx0+70, cy+26), (rx0+70, cy+74)], fill=WHITE, width=4)

d.text((rx0+card_w/2, card_y1-45), "Money still in the system", font=font("ariali", 26), fill=(220,235,250), anchor="mm")

# Bottom row: who benefits
who_y0, who_y1 = 510, 850
seg_w = (W-120) / 3
who = [
    (icon_people, "INVESTIGATORS", "A ranked, explainable deployment plan\u2014not a red dot and a guess"),
    (icon_bank, "BANKS & I4C", "An early, auditable alert through secure\nchannels, before cash leaves the system"),
    (icon_shield, "CITIZENS", "A real chance at recovery instead of\na closed case"),
]
for i, (icon_fn, title, body) in enumerate(who):
    x0 = 60 + i*seg_w
    cx = x0 + seg_w/2
    icon_cy = who_y0 + 60
    d.ellipse([cx-50, icon_cy-50, cx+50, icon_cy+50], fill=NAVY)
    icon_fn(d, cx, icon_cy, 62, WHITE)
    d.text((cx, icon_cy+90), title, font=who_hdr, fill=NAVY, anchor="mm")
    lines = body.split("\n")
    draw_multiline_center(d, cx, icon_cy+130, lines, who_body, fill=DARK, line_gap=1.25)

out = "E:/TRACE-X/analysis/visuals/slide5_impact.png"
img.save(out)
print("saved", out)
