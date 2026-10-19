"""Regenerates the brand images from the dashboard's own font (Geist, SIL OFL):

  docs/assets/banner.svg             README banner (lettering drawn as outlines, so it looks the same
                                     everywhere; logo and name share one horizontal centre line)
  dashboard/public/og-image.png      1200x630 social preview (text left-aligned, same centre line)
  dashboard/public/apple-touch-icon.png, icon-192.png, icon-512.png
  docs/assets/how-it-works.svg       README diagram of how a request flows through the gateway

Run from the repository root after ``npm install`` (the font comes from node_modules):

  pip install fonttools brotli pillow
  python scripts/brand_assets.py
"""
import pathlib, tempfile
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(".")
SRC = ROOT / "dashboard/node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="llmflow-brand-"))

def instance(weight):
    out = TMP / f"Geist-{weight}.ttf"
    f = TTFont(SRC)
    f = instancer.instantiateVariableFont(f, {"wght": weight})
    f.flavor = None  # plain TrueType, not the compressed web format
    f.save(out)
    return out

TTF = {600: instance(600), 400: instance(400)}

def outline(text, weight, size):
    """Return (svg_path_d, xmin, xmax, ymin, ymax) for ``text`` laid out on baseline y=0, in px,
    y pointing DOWN (SVG), x starting at 0 (advance origin)."""
    f = TTFont(TTF[weight]); gs = f.getGlyphSet(); cmap = f.getBestCmap(); upem = f["head"].unitsPerEm
    k = size / upem
    pen = SVGPathPen(gs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
    bounds = BoundsPen(gs)
    x = 0
    for ch in text:
        name = cmap[ord(ch)]
        t = (k, 0, 0, -k, x * k, 0)               # scale, flip y, move right
        gs[name].draw(TransformPen(pen, t))
        gs[name].draw(TransformPen(bounds, t))
        x += gs[name].width
    xmin, ymin, xmax, ymax = bounds.bounds       # already in SVG px (y down: ymin is the TOP)
    return pen.getCommands(), xmin, xmax, ymin, ymax

# ---------------------------------------------------------------- README banner (SVG)
W, H = 1280, 320
LOGO, GAP, SIZE_NAME, SIZE_TAG = 72, 24, 64, 22
LOGO_CY = 124
name_d, nx0, nx1, ny0, ny1 = outline("LLMFlow", 600, SIZE_NAME)
tag_text = "One OpenAI-compatible endpoint. The right model for every request."
tag_d, tx0, tx1, ty0, ty1 = outline(tag_text, 400, SIZE_TAG)

group_w = LOGO + GAP + (nx1 - nx0)
gx = W / 2 - group_w / 2                                   # group centred horizontally
logo_x, logo_y = gx, LOGO_CY - LOGO / 2
name_x = gx + LOGO + GAP - nx0                              # ink starts right after the gap
name_baseline = LOGO_CY - (ny0 + ny1) / 2                   # ink centre == logo centre
tag_x = W / 2 - (tx0 + tx1) / 2
tag_baseline = 224

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
  <title id="t">LLMFlow</title>
  <desc id="d">LLMFlow logo and name: an OpenAI-compatible gateway that routes each request to the right model.</desc>
  <rect width="{W}" height="{H}" rx="16" fill="#0d0d0d"/>
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="15.5" fill="none" stroke="#2a2a28"/>

  <!-- logo mark: centre line y={LOGO_CY} -->
  <g transform="translate({logo_x:.2f} {logo_y:.2f})">
    <rect width="{LOGO}" height="{LOGO}" rx="18" fill="#f4f2ee"/>
    <g transform="scale({LOGO/20})" fill="none" stroke="#0d0d0d" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 10h5M8 10l4-4h5M8 10h9M8 10l4 4h5"/>
    </g>
  </g>

  <!-- wordmark (outlines, Geist SemiBold): its letter shapes are centred on the same line -->
  <path transform="translate({name_x:.2f} {name_baseline:.2f})" fill="#f4f2ee" d="{name_d}"/>

  <!-- tagline (outlines, Geist Regular) -->
  <path transform="translate({tag_x:.2f} {tag_baseline})" fill="#a8a69f" d="{tag_d}"/>
</svg>
'''
(ROOT / "docs/assets/banner.svg").write_text(svg)
print(f"banner: logo centre y={LOGO_CY}, name ink centre y={name_baseline + (ny0 + ny1) / 2:.2f}, group x={gx:.1f}..{gx+group_w:.1f}")

# ---------------------------------------------------------------- social preview (PNG)
PW, PH, SS = 1200, 630, 2
INK, PAPER, MUTED, LINE = (13, 13, 13), (244, 242, 238), (168, 166, 159), (42, 42, 40)
def pf(weight, size): return ImageFont.truetype(str(TTF[weight]), size * SS)

def glyph(d, x, y, size, color, width):
    s = size / 20
    for a, b in [((3,10),(8,10)),((8,10),(12,6)),((12,6),(17,6)),((8,10),(17,10)),((8,10),(12,14)),((12,14),(17,14))]:
        p = (x + a[0]*s, y + a[1]*s); q = (x + b[0]*s, y + b[1]*s)
        d.line([p, q], fill=color, width=width)
        for c in (p, q):
            d.ellipse([c[0]-width/2, c[1]-width/2, c[0]+width/2, c[1]+width/2], fill=color)

def mark(size, bg, fg, rr=0.25, ss=4):
    S = size * ss; im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, S-1, S-1], radius=int(S*rr), fill=bg); glyph(d, 0, 0, S, fg, max(2, int(S*0.08)))
    return im.resize((size, size), Image.LANCZOS)

im = Image.new("RGB", (PW*SS, PH*SS), INK); d = ImageDraw.Draw(im)
d.rectangle([0, 0, PW*SS-1, PH*SS-1], outline=LINE, width=2*SS)
LEFT, LOGO_PX, LOGO_Y = 120, 120, 120          # left-aligned content; logo box 120..240
logo = mark(LOGO_PX*SS, PAPER, INK).convert("RGBA"); im.paste(logo, (LEFT*SS, LOGO_Y*SS), logo)
cy = (LOGO_Y + LOGO_PX/2) * SS                  # the shared horizontal centre line
name_font = pf(600, 88)
l, t, r, b = d.textbbox((0, 0), "LLMFlow", font=name_font, anchor="ls")   # ink box around the baseline
d.text(((LEFT + LOGO_PX + 28)*SS, cy - (t + b)/2), "LLMFlow", font=name_font, fill=PAPER, anchor="ls")
d.text((LEFT*SS, 360*SS), "Send every request to the right AI model.", font=pf(600, 46), fill=PAPER, anchor="ls")
d.text((LEFT*SS, 432*SS), "An OpenAI-compatible gateway that routes each request to the", font=pf(400, 30), fill=MUTED, anchor="ls")
d.text((LEFT*SS, 474*SS), "cheapest model that meets your quality setting.", font=pf(400, 30), fill=MUTED, anchor="ls")
d.text((LEFT*SS, 566*SS), "Open source  ·  Bring your own keys  ·  Encrypted at rest and in transit", font=pf(400, 24), fill=MUTED, anchor="ls")
im.resize((PW, PH), Image.LANCZOS).save(ROOT / "dashboard/public/og-image.png", optimize=True)
print(f"preview: logo centre y={LOGO_Y + LOGO_PX/2}, name ink centre y={(cy - (t + b)/2 + (t + b)/2)/SS:.2f}")

# ---------------------------------------------------------------- app icons
for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
    icon = mark(size, INK, PAPER, 0.22)
    icon = icon.convert("RGB") if name == "apple-touch-icon.png" else icon
    icon.save(ROOT / "dashboard/public" / name, optimize=True)
print("icons written")

# ---------------------------------------------------------------- "how it works" diagram (SVG)
DW, DH = 1280, 440
D_PAPER, D_MUTED, D_INK, D_PANEL, D_LINE = "#f4f2ee", "#a8a69f", "#0d0d0d", "#1a1a19", "#3a3a37"
parts = []

def tp(text, weight, size, x, y, fill, anchor="start", max_w=None):
    """Text as outlines (identical in every renderer). ``y`` is the baseline."""
    d, x0, x1, _y0, _y1 = outline(text, weight, size)
    if max_w is not None:
        assert x1 - x0 <= max_w, f"text too wide ({x1 - x0:.0f}px > {max_w}px): {text}"
    dx = x - (x0 + x1) / 2 if anchor == "middle" else x - x0
    parts.append(f'<path transform="translate({dx:.2f} {y})" fill="{fill}" d="{d}"/>')

def box(x, y, w, h, fill=D_PANEL, stroke="#2a2a28", rx=14):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}"/>')

def arrow(x1, x2, y):
    parts.append(f'<path d="M{x1} {y}H{x2 - 9}" stroke="{D_MUTED}" stroke-width="2" fill="none" stroke-linecap="round"/>')
    parts.append(f'<path d="M{x2 - 10} {y - 6}L{x2} {y}L{x2 - 10} {y + 6}Z" fill="{D_MUTED}"/>')

tp("How a request flows through LLMFlow", 600, 20, 40, 52, D_PAPER)

# your app
box(40, 150, 220, 130)
tp("Your app", 600, 22, 150, 205, D_PAPER, "middle", 190)
tp("OpenAI SDK, curl or any client", 400, 14, 150, 233, D_MUTED, "middle", 200)
tp("with an LLMFlow API key", 400, 14, 150, 254, D_MUTED, "middle", 200)
arrow(260, 330, 215)

# the gateway
box(330, 80, 620, 300, fill="#141413", stroke=D_LINE, rx=16)
parts.append(f'<g transform="translate(356 100)"><rect width="30" height="30" rx="8" fill="{D_PAPER}"/>'
             f'<g transform="scale(1.5)" fill="none" stroke="{D_INK}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
             f'<path d="M3 10h5M8 10l4-4h5M8 10h9M8 10l4 4h5"/></g></g>')
tp("LLMFlow", 600, 20, 396, 123, D_PAPER)
steps = [
    "Check the key, rate limit and daily budget",
    "Answer repeats from the cache at no cost",
    "Score how hard the request is (0 to 1)",
    "Pick the cheapest model that meets your quality setting",
    "Retry on another model if one fails",
]
for i, text in enumerate(steps):
    cy = 172 + i * 38
    parts.append(f'<circle cx="372" cy="{cy}" r="13" fill="{D_PAPER}"/>')
    tp(str(i + 1), 600, 14, 372, cy + 5, D_INK, "middle")
    tp(text, 400, 17, 400, cy + 6, D_PAPER, "start", 530)
arrow(950, 1020, 215)

# providers
tp("Your own provider keys", 400, 14, 1130, 80, D_MUTED, "middle", 220)
for i, name in enumerate(("Groq", "Gemini", "OpenAI")):
    y = 98 + i * 88
    box(1020, y, 220, 68)
    tp(name, 600, 20, 1130, y + 31, D_PAPER, "middle")
    tp("answers with your key", 400, 13, 1130, y + 52, D_MUTED, "middle", 200)

tp("Every reply says which model answered and why, in x-llmflow-* response headers.",
   400, 15, 640, 412, D_MUTED, "middle", 900)

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{DW}" height="{DH}" viewBox="0 0 {DW} {DH}" role="img" '
       f'aria-labelledby="t d">\n  <title id="t">How a request flows through LLMFlow</title>\n'
       f'  <desc id="d">Your app sends an OpenAI-style request with an LLMFlow API key. LLMFlow checks the key and budget, '
       f'serves repeats from cache, scores difficulty, picks the cheapest model that meets the quality setting, and falls '
       f'back if a model fails. The request is answered by a provider using your own key: Groq, Gemini or OpenAI.</desc>\n'
       f'  <rect width="{DW}" height="{DH}" rx="16" fill="{D_INK}"/>\n'
       f'  <rect x="0.5" y="0.5" width="{DW - 1}" height="{DH - 1}" rx="15.5" fill="none" stroke="#2a2a28"/>\n  '
       + "\n  ".join(parts) + "\n</svg>\n")
(ROOT / "docs/assets/how-it-works.svg").write_text(svg)
print("diagram written")
