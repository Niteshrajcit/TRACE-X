import sys
sys.path.insert(0, "E:/TRACE-X/scripts")
from viz_common import *

W, H = 2400, 860
img, d = new_canvas(W, H)

label_f = font("arialbd", 32)
cap_f = font("arial", 24)
stack_f = font("arial", 24)
stack_hdr = font("arialbd", 26)

stages = [
    ("DATA", icon_database, "Complaints +\ntransactions", GRAY),
    ("GRAPH", icon_network, "Accounts, rings,\nhistory linked", BLUE),
    ("PREDICTION", icon_pin, "Where + when\nit surfaces", BLUE),
    ("EXPLANATION", icon_magnifier, "Why it's\nranked high", BLUE),
    ("OPTIMIZATION", icon_target, "Best team\ndeployment", NAVY),
    ("ACTION", icon_bell, "Alert +\napproval", NAVY_DARK),
]

n = len(stages)
top_y = 90
cy = 330
r = 92
margin = 110
usable = W - 2*margin
step = usable / (n-1)
xs = [margin + i*step for i in range(n)]

# connecting line
d.line([(xs[0], cy), (xs[-1], cy)], fill=GRAY_LIGHT, width=10)
for i in range(n-1):
    arrow_h(d, xs[i]+r+6, xs[i+1]-r-10, cy, color=GRAY_MED, width=6, head=18)

for x, (name, icon_fn, cap, color) in zip(xs, stages):
    d.ellipse([x-r, cy-r, x+r, cy+r], fill=color)
    icon_fn(d, x, cy, r*1.15, WHITE)
    d.text((x, cy - r - 34), name, font=label_f, fill=DARK, anchor="mm")
    lines = cap.split("\n")
    draw_multiline_center(d, x, cy + r + 26, lines, cap_f, fill=GRAY, line_gap=1.2)

# Technical stack strip at the bottom
strip_y0 = 610
strip_y1 = 830
rrect(d, [70, strip_y0, W-70, strip_y1], radius=16, fill=GRAY_LIGHT, outline=None)
d.text((110, strip_y0+22), "CORE STACK", font=stack_hdr, fill=NAVY, anchor="la")
stack_items = "Neo4j (graph)   \u2022   XGBoost / GNN + survival models (prediction)   \u2022   SHAP (explanation)   \u2022   H3 + PostGIS (geospatial)   \u2022   React + Mapbox (dashboard)"
lines = wrap_text(stack_items, stack_f, W-260, d)
for i, ln in enumerate(lines):
    d.text((110, strip_y0+70+i*36), ln, font=stack_f, fill=DARK, anchor="la")

out = "E:/TRACE-X/analysis/visuals/slide3_pipeline.png"
img.save(out)
print("saved", out)
