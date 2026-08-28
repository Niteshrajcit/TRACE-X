import sys
sys.path.insert(0, "E:/TRACE-X/scripts")
from viz_common import *

W, H = 2400, 860
img, d = new_canvas(W, H)

label_f = font("arialbd", 34)
box_f = font("arialbd", 33)
sub_f = font("arial", 26)
row_f = font("arialbd", 30)

def box(cx, cy, w, h, fill, outline, text, icon_fn=None, icon_color=WHITE, muted_text=None):
    x0, y0, x1, y1 = cx-w/2, cy-h/2, cx+w/2, cy+h/2
    rrect(d, [x0,y0,x1,y1], radius=18, fill=fill, outline=outline, width=4)
    icon_cy = cy - h*0.12
    if icon_fn:
        icon_fn(d, cx, icon_cy, h*0.62, icon_color)
    lines = wrap_text(text, box_f, w*0.86, d)
    ty = cy + h*0.10
    draw_multiline_center(d, cx, ty, lines, box_f, fill=icon_color, line_gap=1.15)

row_h = 300
row1_cy = 235
row2_cy = 620

# Row labels
d.text((70, row1_cy), "TODAY", font=row_f, fill=RED, anchor="lm")
d.text((70, row1_cy+44), "(reactive)", font=sub_f, fill=GRAY, anchor="lm")
d.text((70, row2_cy), "TRACE-X", font=row_f, fill=BLUE, anchor="lm")
d.text((70, row2_cy+44), "(proactive)", font=sub_f, fill=GRAY, anchor="lm")

bw, bh = 430, 210
gap = 60
start_x = 430

# Row 1: Complaint -> Investigation Begins -> Cash Withdrawn -> Trail Cold
r1_boxes = [
    ("Complaint\nFiled", icon_document, GRAY_LIGHT, GRAY_MED, DARK),
    ("Investigation\nBegins", icon_magnifier, GRAY_LIGHT, GRAY_MED, DARK),
    ("Cash\nWithdrawn", icon_cash, GRAY_MED, GRAY_MED, WHITE),
    ("Trail\nCold", icon_broken, RED, RED, WHITE),
]
xs = [start_x + i*(bw+gap) for i in range(4)]
for x, (label, icon_fn, fill, outline, tcol) in zip(xs, r1_boxes):
    text = label.replace("\n", " ")
    box(x, row1_cy, bw, bh, fill, outline, text, icon_fn, tcol)
for i in range(3):
    arrow_h(d, xs[i]+bw/2+8, xs[i+1]-bw/2-8, row1_cy, color=GRAY, width=7, head=20)

# Row 2: Complaint -> Prediction -> Intervention
r2_boxes = [
    ("Complaint\nFiled", icon_document, GRAY_LIGHT, BLUE, DARK),
    ("Prediction\n(Where + When)", icon_pin, BLUE, BLUE, WHITE),
    ("Intervention\n(Team Deployed)", icon_check, NAVY, NAVY, WHITE),
]
bw2 = 470
xs2 = [start_x + i*(bw2+gap) for i in range(3)]
# center row2 within same total span as row1 for visual alignment
total1 = xs[-1] + bw/2
total2 = xs2[-1] + bw2/2
shift = (total1 - total2)/2
xs2 = [x+shift for x in xs2]
for x, (label, icon_fn, fill, outline, tcol) in zip(xs2, r2_boxes):
    text = label.replace("\n", " ")
    box(x, row2_cy, bw2, bh, fill, outline, text, icon_fn, tcol)
for i in range(2):
    arrow_h(d, xs2[i]+bw2/2+8, xs2[i+1]-bw2/2-8, row2_cy, color=BLUE, width=8, head=22)

# vertical divider between rows
d.line([(40, 440), (W-40, 440)], fill=GRAY_LIGHT, width=3)

# money-still-in-system tag under last box of row2
tag_cx, tag_cy = xs2[-1], row2_cy + bh/2 + 55
d.text((tag_cx, tag_cy), "Money still in the system", font=font("ariali", 26), fill=GREEN, anchor="mm")

out = "E:/TRACE-X/analysis/visuals/slide2_flow.png"
img.save(out)
print("saved", out)
