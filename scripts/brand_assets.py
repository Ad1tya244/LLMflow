"""Regenerates the brand images from the dashboard's own font (Geist, SIL OFL):

  docs/assets/banner.svg             README banner (lettering drawn as outlines, so it looks the same
                                     everywhere; logo and name share one horizontal centre line)
  dashboard/public/og-image.png      1200x630 social preview (text left-aligned, same centre line)
  dashboard/public/apple-touch-icon.png, icon-192.png, icon-512.png

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
