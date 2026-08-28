# -*- coding: utf-8 -*-
import shutil, os
from lxml import etree

BASE = "E:/TRACE-X/build/unpacked"
NS = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}
A = NS['a']; P = NS['p']; R = NS['r']

def qa(tag): return f"{{{A}}}{tag}"
def qp(tag): return f"{{{P}}}{tag}"

def load(path):
    parser = etree.XMLParser(remove_blank_text=False)
    return etree.parse(path, parser)

def save(tree, path):
    tree.write(path, xml_declaration=True, encoding="UTF-8", standalone=True)

# ---------------------------------------------------------------
# SLIDE 1: title-page fill-ins
# ---------------------------------------------------------------
s1_path = f"{BASE}/ppt/slides/slide1.xml"
tree = load(s1_path)
root = tree.getroot()

replacements_s1 = {
    "TITLE PAGE": "TRACE-X \u2014 Predict. Explain. Intervene.",
    "Problem Statement ID \u2013": "Problem Statement ID \u2013 SIH26184",
    "Problem Statement Title-": "Problem Statement Title\u2013 Predictive Analytics Framework for Cybercrime Complaints to Forecast Likely Cash Withdrawal Locations",
    "Theme-": "Theme\u2013 Blockchain & Cybersecurity",
    "PS Category- Software/Hardware": "PS Category\u2013 Software",
    "Team ID-": "Team ID\u2013 [Insert Team ID]",
    "Team Name (Registered on portal)": "Team Name\u2013 [Insert Registered Team Name]",
}
count = 0
for t in root.iter(qa("t")):
    if t.text in replacements_s1:
        t.text = replacements_s1[t.text]
        count += 1
print("slide1 replacements:", count, "/", len(replacements_s1))

# Fix: the 6-line fill-in list at 24pt / 200% line spacing overflows the slide
# once "Problem Statement Title" wraps to 3 lines. Shrink font + line spacing
# so the full block fits within the slide bounds.
spTree1 = root.find(f"{qp('cSld')}/{qp('spTree')}")
tb9 = None
for sp in spTree1.findall(qp("sp")):
    nvpr = sp.find(f"{qp('nvSpPr')}/{qp('cNvPr')}")
    if nvpr is not None and "TextBox 9" in (nvpr.get("name") or ""):
        tb9 = sp
        break
if tb9 is not None:
    txBody9 = tb9.find(qp("txBody"))
    for p_el in txBody9.findall(qa("p")):
        pPr = p_el.find(qa("pPr"))
        if pPr is not None:
            lnSpc = pPr.find(qa("lnSpc"))
            if lnSpc is not None:
                spcPct = lnSpc.find(qa("spcPct"))
                if spcPct is not None:
                    spcPct.set("val", "115000")
        for rPr in p_el.iter(qa("rPr")):
            rPr.set("sz", "1800")
        for rPr in p_el.iter(qa("endParaRPr")):
            rPr.set("sz", "1800")
else:
    print("WARNING: TextBox 9 not found on slide1")
save(tree, s1_path)

# ---------------------------------------------------------------
# SLIDES 2-6: title (slide2 only), team badge, headline+support, diagram image
# ---------------------------------------------------------------
CONTENT = {
    2: dict(
        title_old="IDEA TITLE", title_new="TRACE-X",
        headline="Stop chasing withdrawn cash. Predict where it's headed.",
        support="~8,000 fraud complaints a day. Once cash is withdrawn, the trail goes cold \u2014 TRACE-X predicts the withdrawal before it happens.",
        image="slide2_flow.png",
    ),
    3: dict(
        title_old=None, title_new=None,
        headline="Not one model \u2014 a pipeline: graph, prediction, explanation, optimization.",
        support="Six connected stages turn a raw complaint into an explainable, resource-aware deployment decision.",
        image="slide3_pipeline.png",
    ),
    4: dict(
        title_old=None, title_new=None,
        headline="We've already answered the hard questions.",
        support="Restricted data, daily scale, false positives, geographic bias \u2014 each has a specific, engineered mitigation.",
        image="slide4_feasibility.png",
    ),
    5: dict(
        title_old=None, title_new=None,
        headline="Minutes of warning. A chance to recover.",
        support="The difference isn't incremental \u2014 a cold trail versus a live one, while the money is still in the system.",
        image="slide5_impact.png",
    ),
    6: dict(
        title_old=None, title_new=None,
        headline="WHERE WILL THE MONEY GO NEXT?",
        support="TRACE-X \u2014 Predict. Explain. Intervene. From reactive cybercrime investigation to proactive cash-out intelligence.",
        image="slide6_references.png",
    ),
}

# Unified text-zone and image-zone geometry (EMU), shared by slides 2-6
TEXT_X, TEXT_Y, TEXT_CX, TEXT_CY = 609600, 1230000, 10972800, 950000
IMG_X, IMG_Y, IMG_CX, IMG_CY = 609600, 2300000, 10972800, 3931300

def find_shape_by_name_substr(spTree, substr):
    for sp in spTree.findall(qp("sp")):
        nvpr = sp.find(f"{qp('nvSpPr')}/{qp('cNvPr')}")
        if nvpr is not None and substr in (nvpr.get("name") or ""):
            return sp
    return None

def set_xfrm(sp, x, y, cx, cy):
    spPr = sp.find(qp("spPr"))
    xfrm = spPr.find(qa("xfrm"))
    if xfrm is None:
        xfrm = etree.SubElement(spPr, qa("xfrm"))
        etree.SubElement(xfrm, qa("off"))
        etree.SubElement(xfrm, qa("ext"))
    off = xfrm.find(qa("off")); ext = xfrm.find(qa("ext"))
    off.set("x", str(x)); off.set("y", str(y))
    ext.set("cx", str(cx)); ext.set("cy", str(cy))

def make_run(text, sz, bold, color_hex, typeface):
    r = etree.Element(qa("r"))
    rPr = etree.SubElement(r, qa("rPr"))
    rPr.set("lang", "en-US"); rPr.set("sz", str(sz)); rPr.set("dirty", "0")
    if bold: rPr.set("b", "1")
    fill = etree.SubElement(rPr, qa("solidFill"))
    clr = etree.SubElement(fill, qa("srgbClr")); clr.set("val", color_hex)
    latin = etree.SubElement(rPr, qa("latin")); latin.set("typeface", typeface)
    t = etree.SubElement(r, qa("t")); t.text = text
    return r

def replace_textbox_content(sp, headline, support):
    txBody = sp.find(qp("txBody"))
    for p_el in txBody.findall(qa("p")):
        txBody.remove(p_el)
    p1 = etree.SubElement(txBody, qa("p"))
    pPr1 = etree.SubElement(p1, qa("pPr")); pPr1.set("marL", "0"); pPr1.set("indent", "0")
    buNone1 = etree.SubElement(pPr1, qa("buNone"))
    p1.append(make_run(headline, 2400, True, "1F497D", "Times New Roman"))
    p2 = etree.SubElement(txBody, qa("p"))
    pPr2 = etree.SubElement(p2, qa("pPr")); pPr2.set("marL", "0"); pPr2.set("indent", "0")
    spcBef = etree.SubElement(pPr2, qa("spcBef"))
    spcPts = etree.SubElement(spcBef, qa("spcPts")); spcPts.set("val", "600")
    etree.SubElement(pPr2, qa("buNone"))
    p2.append(make_run(support, 1600, False, "444444", "Arial"))

def add_picture(spTree, rel_id, shape_id, name, x, y, cx, cy):
    pic = etree.SubElement(spTree, qp("pic"))
    nvPicPr = etree.SubElement(pic, qp("nvPicPr"))
    cNvPr = etree.SubElement(nvPicPr, qp("cNvPr")); cNvPr.set("id", str(shape_id)); cNvPr.set("name", name)
    cNvPicPr = etree.SubElement(nvPicPr, qp("cNvPicPr"))
    picLocks = etree.SubElement(cNvPicPr, qa("picLocks")); picLocks.set("noChangeAspect", "1")
    etree.SubElement(nvPicPr, qp("nvPr"))
    blipFill = etree.SubElement(pic, qp("blipFill"))
    blip = etree.SubElement(blipFill, qa("blip")); blip.set(f"{{{R}}}embed", rel_id)
    etree.SubElement(blipFill, qa("stretch")).append(etree.Element(qa("fillRect")))
    spPr = etree.SubElement(pic, qp("spPr"))
    xfrm = etree.SubElement(spPr, qa("xfrm"))
    off = etree.SubElement(xfrm, qa("off")); off.set("x", str(x)); off.set("y", str(y))
    ext = etree.SubElement(xfrm, qa("ext")); ext.set("cx", str(cx)); ext.set("cy", str(cy))
    prst = etree.SubElement(spPr, qa("prstGeom")); prst.set("prst", "rect")
    etree.SubElement(prst, qa("avLst"))
    return pic

def add_image_relationship(slide_num, image_filename):
    rels_path = f"{BASE}/ppt/slides/_rels/slide{slide_num}.xml.rels"
    rels_tree = load(rels_path)
    rels_root = rels_tree.getroot()
    existing_ids = [r.get("Id") for r in rels_root]
    max_num = max(int(i.replace("rId", "")) for i in existing_ids)
    new_id = f"rId{max_num+1}"
    rel = etree.SubElement(rels_root, f"{{{NS['rel']}}}Relationship")
    rel.set("Id", new_id)
    rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image")
    rel.set("Target", f"../media/{image_filename}")
    save(rels_tree, rels_path)
    return new_id

media_dir = f"{BASE}/ppt/media"
viz_dir = "E:/TRACE-X/analysis/visuals"

for n, cfg in CONTENT.items():
    path = f"{BASE}/ppt/slides/slide{n}.xml"
    tree = load(path)
    root = tree.getroot()
    spTree = root.find(f"{qp('cSld')}/{qp('spTree')}")

    # Title text (slide2 only)
    if cfg["title_old"]:
        for t in root.iter(qa("t")):
            if t.text == cfg["title_old"]:
                t.text = cfg["title_new"]

    # Team badge oval -> TRACE-X (explicit smaller bold size so it fits on one line)
    for sp in spTree.findall(qp("sp")):
        for t in sp.iter(qa("t")):
            if t.text == "Your Team Name":
                t.text = "TRACE-X"
                run = t.getparent()
                rPr = run.find(qa("rPr"))
                if rPr is None:
                    rPr = etree.SubElement(run, qa("rPr"))
                    run.insert(0, rPr)
                rPr.set("sz", "1400")
                rPr.set("b", "1")

    # Content textbox: reposition + replace with headline/support
    tb = find_shape_by_name_substr(spTree, "TextBox 8")
    set_xfrm(tb, TEXT_X, TEXT_Y, TEXT_CX, TEXT_CY)
    replace_textbox_content(tb, cfg["headline"], cfg["support"])

    # Copy image into media, add relationship, add <p:pic>
    src_img = f"{viz_dir}/{cfg['image']}"
    dst_name = f"tracex_{cfg['image']}"
    shutil.copy(src_img, f"{media_dir}/{dst_name}")
    rel_id = add_image_relationship(n, dst_name)
    add_picture(spTree, rel_id, 9000 + n, f"TRACE-X Diagram {n}", IMG_X, IMG_Y, IMG_CX, IMG_CY)

    save(tree, path)
    print(f"slide{n} updated, image rel={rel_id}")

print("DONE")
