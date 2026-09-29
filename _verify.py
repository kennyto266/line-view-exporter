"""Verify test_output.svg (well-formed XML, structure, stats) and render a PNG preview."""
import math
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

SVG = r"C:\Users\Penguin8n\.zcode\workspace\default\line-view-exporter\test_output.svg"
PNG = r"C:\Users\Penguin8n\.zcode\workspace\default\line-view-exporter\test_preview.png"
NS = "{http://www.w3.org/2000/svg}"

tree = ET.parse(SVG)  # raises if malformed
root = tree.getroot()
vb = [float(x) for x in root.get("viewBox").split()]
print("well-formed XML: OK | viewBox:", vb)

groups = [g.get("id") for g in root.findall(NS + "g")]
texts = [t.text for t in root.findall(NS + "text")]
print("groups:", groups)
print("texts:", texts)

scale = 2.0
img = Image.new("RGB", (int(vb[2] * scale), int(vb[3] * scale)), "white")
d = ImageDraw.Draw(img)

n_paths = 0
n_segs = 0
per_group = {}
for g in root.findall(NS + "g"):
    gid = g.get("id", "?")
    stroke = g.get("stroke", "#000000")
    dash = "stroke-dasharray" in g.attrib
    sw = float(g.get("stroke-width", "0.5"))
    col = (0, 0, 0) if stroke == "#000000" else (160, 160, 160)
    count = 0
    for p in g.findall(NS + "path"):
        n_paths += 1
        # SVG allows the command letter to stick to its numbers: "M208.5 440.7L198.4 440.7"
        for cmd, xs, ys in re.findall(r"([ML])(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", p.get("d")):
            nxt = (float(xs) * scale, float(ys) * scale)
            if cmd == "L" and cur is not None:
                count += 1
                n_segs += 1
                dx, dy = nxt[0] - cur[0], nxt[1] - cur[1]
                ln = math.hypot(dx, dy)
                if not dash:
                    d.line([cur, nxt], fill=col, width=max(1, int(sw * scale)))
                else:
                    pos, on = 0.0, True
                    while pos < ln:
                        step = 6.0 if on else 4.0
                        step = min(step, ln - pos)
                        if on:
                            a = (cur[0] + dx * pos / ln, cur[1] + dy * pos / ln)
                            b = (cur[0] + dx * (pos + step) / ln, cur[1] + dy * (pos + step) / ln)
                            d.line([a, b], fill=col, width=max(1, int(sw * scale)))
                        pos += step
                        on = not on
            cur = nxt
    per_group[gid] = count

# scale bar lines
for ln in root.iter(NS + "line"):
    x1, y1 = float(ln.get("x1")) * scale, float(ln.get("y1")) * scale
    x2, y2 = float(ln.get("x2")) * scale, float(ln.get("y2")) * scale
    d.line([(x1, y1), (x2, y2)], fill=(0, 0, 0), width=2)

# text labels
from PIL import ImageFont
for t in root.findall(NS + "text"):
    fs = float(t.get("font-size", "9")) * scale
    try:
        font = ImageFont.truetype("arial.ttf", int(fs))
    except OSError:
        font = ImageFont.load_default()
    d.text(
        (float(t.get("x")) * scale, float(t.get("y")) * scale),
        t.text or "",
        fill=(0, 0, 0),
        font=font,
        anchor="ms" if t.get("text-anchor") == "middle" else "ls",
    )

img.save(PNG)
print("paths:", n_paths, "| line segments:", n_segs)
print("segments per group:", per_group)
print("preview saved:", PNG)
