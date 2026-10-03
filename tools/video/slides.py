#!/usr/bin/env python3
"""Deck HTML to 1920x1080 stills, and a still to a video segment of exact length.

    slides.py build decks/keepout.json -o build/keepout/deck.html
    slides.py shoot build/keepout/deck.html -o build/keepout/slides
    slides.py segment build/keepout/slides/s3.png -o build/keepout/seg/s3.mp4 -d 11.4
    slides.py card -o build/keepout/slides/team.png \
        --kicker "Team" --title "Team clip goes here" --sub "12 seconds"

`build` turns a JSON slide list into one HTML file of `section.slide` elements.
Every slide kind that can carry a number also carries a `source` line, printed
under it, because a figure on screen without its source is not usable here.

`shoot` calls the callsheet deckshot script, which screenshots every
`section.slide` in the file and names each PNG after the section id.

`segment` makes the still move. A held frame reads as a dead video, so every
segment gets a slow push-in: the image is supersampled, then zoompan walks the
crop across the whole duration and lands on 1920x1080. Duration is exact to the
frame, because cut.py has already worked out what the narration needs.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

import enc

TOOLS = Path(__file__).resolve().parent
DECKSHOT = Path("/home/rogerkorantenng/dev/Hackathons/agentic-cinema/callsheet/deckshot.mjs")
W, H, FPS = 1920, 1080, 30
SUPERSAMPLE = 2  # zoompan on a 2x image is smooth; on a 1x image it stair-steps


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"{cmd[0]} failed:\n{r.stderr.strip()[:2000]}")
    return r


# ------------------------------------------------------------------------- shoot

def shoot(html_path: Path, out_dir: Path) -> list[Path]:
    if not DECKSHOT.exists():
        sys.exit(f"deckshot not found at {DECKSHOT}")
    out_dir.mkdir(parents=True, exist_ok=True)
    r = run(["node", str(DECKSHOT), str(html_path.resolve()), str(out_dir.resolve())],
            cwd=str(DECKSHOT.parent))
    print(r.stdout.strip())
    pngs = sorted(out_dir.glob("*.png"))
    for p in pngs:
        size = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)])
        wh = size.stdout.strip()
        if wh != f"{W},{H}":
            print(f"  note: {p.name} is {wh}, not {W}x{H}; it will be padded", file=sys.stderr)
    print(f"{len(pngs)} slides in {out_dir}")
    return pngs


# ------------------------------------------------------------------------- build

DECK_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);font-family:Inter,-apple-system,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}
section.slide{position:relative;width:1920px;height:1080px;background:var(--bg);
  color:var(--fg);padding:120px 150px 110px;display:flex;flex-direction:column;
  justify-content:center;overflow:hidden}
section.slide::before{content:"";position:absolute;top:0;left:0;width:100%;height:8px;
  background:var(--accent)}
.kicker{font-size:27px;letter-spacing:.22em;text-transform:uppercase;color:var(--accent);
  font-weight:600;margin-bottom:30px}
h1{font-size:112px;line-height:1.05;font-weight:700;letter-spacing:-.025em}
h2{font-size:62px;line-height:1.16;font-weight:700;letter-spacing:-.018em;max-width:1500px}
.sub{font-size:36px;line-height:1.45;margin-top:34px;color:var(--muted);max-width:1350px}
.stat{font-size:220px;line-height:.95;font-weight:700;letter-spacing:-.045em;
  color:var(--accent);font-variant-numeric:tabular-nums}
.stat .unit{font-size:88px;letter-spacing:-.02em;margin-left:14px}
.statline{font-size:52px;line-height:1.28;margin-top:36px;max-width:1450px;font-weight:500}
blockquote{font-size:56px;line-height:1.34;font-weight:500;max-width:1560px;
  border-left:8px solid var(--accent);padding-left:44px}
.attrib{font-size:30px;color:var(--muted);margin-top:38px;padding-left:52px}
ul{list-style:none;margin-top:44px}
li{font-size:42px;line-height:1.4;margin-bottom:28px;padding-left:46px;position:relative;
  max-width:1500px}
li::before{content:"";position:absolute;left:0;top:20px;width:22px;height:4px;
  background:var(--accent)}
li .num{color:var(--accent);font-weight:700;font-variant-numeric:tabular-nums}
table{margin-top:46px;border-collapse:collapse;font-size:36px;width:100%;max-width:1600px}
th{text-align:left;font-size:25px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);font-weight:600;padding:0 34px 20px 0;border-bottom:2px solid var(--line)}
td{padding:24px 34px 24px 0;border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums}
td.k{color:var(--fg);font-weight:500}
section.tight table{font-size:29px;margin-top:34px}
section.tight th{font-size:21px;padding-bottom:14px}
section.tight td{padding:15px 30px 15px 0}
section.tight h2{font-size:52px}
tr.bad td{color:var(--warn)}
figure{margin-top:40px;display:flex;justify-content:center;align-items:center;
  max-height:620px}
.mer{margin-top:26px;width:100%;flex:1;display:flex;align-items:center;justify-content:center}
.mer svg{width:100% !important;max-width:none !important;height:auto !important;
  max-height:760px}
section.slide.photo>.bg{position:absolute;inset:0;z-index:0}
/* The accent rule is a ::before on the section, so the photo layer covers it. */
section.slide.photo::before{z-index:2}
section.slide.photo>.bg img{width:100%;height:100%;object-fit:cover;
  filter:saturate(.78) contrast(1.10) brightness(1.18) blur(3px);
  /* The corpus tops out at 640x480, so a full-frame upscale shows its blocks.
     A background wants to be defocused anyway; the blur does both jobs. */
  transform:scale(1.03)}
/* The scrim is what makes type on a photograph legible. It is heaviest where the
   text sits and lifts off the far edge, so the picture is still a picture. */
section.slide.photo>.bg::after{content:"";position:absolute;inset:0;
  background:linear-gradient(100deg,
      rgba(8,11,13,.96) 0%, rgba(8,11,13,.90) 44%,
      rgba(8,11,13,.62) 70%, rgba(8,11,13,.28) 100%),
    linear-gradient(to top, rgba(8,11,13,.88) 0%, rgba(8,11,13,0) 24%)}
section.slide.photo>*:not(.bg){position:relative;z-index:1}
/* .source and .tag are pinned to the bottom edge; the rule above would otherwise
   drop them back into the flow and print them over the body text. */
section.slide.photo>.source,section.slide.photo>.tag{position:absolute}
section.slide.photo .source,section.slide.photo .credit{color:rgba(255,255,255,.52)}
section.slide.photo .credit{position:absolute;right:46px;bottom:34px;z-index:1;
  font-size:19px;color:rgba(255,255,255,.42);letter-spacing:.02em}
section.slide.diagram{justify-content:flex-start;padding-top:96px}
section.slide.diagram h2{font-size:52px;margin-bottom:6px}
figure img{max-width:1600px;max-height:620px;object-fit:contain;
  border:1px solid var(--line);border-radius:6px;background:#fff}
.source{position:absolute;left:150px;bottom:56px;font-size:23px;color:var(--muted);
  max-width:1620px;line-height:1.4}
.tag{position:absolute;right:150px;bottom:56px;font-size:23px;color:var(--muted);
  letter-spacing:.14em;text-transform:uppercase}
.warn::before{background:var(--warn)}
section.warn::before{background:var(--warn)}
section.warn .kicker{color:var(--warn)}
section.warn blockquote{border-left-color:var(--warn)}
"""

MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"
MERMAID_JS = TOOLS / "cache" / "mermaid.min.js"
FONT_CSS = TOOLS / "cache" / "inter.css"


def assets_beside(out_html: Path, uses_mermaid: bool) -> tuple[str, str]:
    """Copy the font and, if needed, mermaid next to the deck and link them.

    deckshot waits for networkidle. Any request that leaves the machine makes
    that wait a coin toss: the same deck renders in two seconds one minute and
    times out the next. With the font and the script local the page makes no
    network requests at all and the wait is instant and reliable.
    """
    copied = []
    if FONT_CSS.exists():
        for f in [FONT_CSS] + sorted(FONT_CSS.parent.glob("inter-*.woff2")):
            dest = out_html.parent / f.name
            if not dest.exists() or dest.stat().st_size != f.stat().st_size:
                shutil.copyfile(f, dest)
        copied.append(f'<link rel="stylesheet" href="{FONT_CSS.name}">')
    else:
        copied.append('<link rel="stylesheet" href="https://fonts.googleapis.com/'
                      'css2?family=Inter:wght@400;500;600;700&display=swap">')
    mer = ""
    if uses_mermaid:
        if not MERMAID_JS.exists():
            MERMAID_JS.parent.mkdir(parents=True, exist_ok=True)
            print(f"  fetching mermaid once into {MERMAID_JS}")
            run(["curl", "-sL", "--max-time", "180", "-o", str(MERMAID_JS), MERMAID_URL])
        dest = out_html.parent / MERMAID_JS.name
        if not dest.exists() or dest.stat().st_size != MERMAID_JS.stat().st_size:
            shutil.copyfile(MERMAID_JS, dest)
        mer = f'<script src="{MERMAID_JS.name}"></script>'
    return copied[0], mer


def mermaid_local(out_html: Path) -> str:
    """Put mermaid next to the deck and reference it relatively.

    deckshot waits for networkidle, and a CDN fetch makes that wait flaky: the
    same deck renders in two seconds one minute and times out the next. Fetched
    once into the cache, it is a local file and the page never touches the
    network.
    """
    if not MERMAID_JS.exists():
        MERMAID_JS.parent.mkdir(parents=True, exist_ok=True)
        print(f"  fetching mermaid once into {MERMAID_JS}")
        run(["curl", "-sL", "--max-time", "180", "-o", str(MERMAID_JS), MERMAID_URL])
    beside = out_html.parent / "mermaid.min.js"
    if not beside.exists() or beside.stat().st_size != MERMAID_JS.stat().st_size:
        shutil.copyfile(MERMAID_JS, beside)
    return beside.name

DECK_PAGE = """<!doctype html><html><head><meta charset="utf-8">
{font_link}
{mermaid_script}
<style>:root{{--bg:{bg};--fg:{fg};--muted:{muted};--accent:{accent};--line:{line};
  --warn:{warn}}}{css}</style></head><body>
{sections}
{mermaid_init}
</body></html>"""

MERMAID_INIT = """<script>
mermaid.initialize({{startOnLoad: true, theme: 'dark', securityLevel: 'loose',
  flowchart: {{useMaxWidth: false, htmlLabels: true, nodeSpacing: 55,
               rankSpacing: 90, padding: 14, curve: 'basis'}},
  themeVariables: {{darkMode: true, background: '{bg}', primaryColor: '{panel}',
    primaryTextColor: '{fg}', primaryBorderColor: '{line}', lineColor: '{accent}',
    secondaryColor: '{panel}', tertiaryColor: '{bg}', clusterBkg: '{panel}',
    clusterBorder: '{line}', edgeLabelBackground: '{bg}', fontSize: '26px',
    fontFamily: 'Inter, sans-serif'}}}});
</script>"""


def _slide_body(s: dict) -> str:
    kind = s.get("kind", "points")
    e = html.escape
    out = []
    if s.get("kicker"):
        out.append(f'<div class="kicker">{e(s["kicker"])}</div>')
    if kind == "title":
        out.append(f"<h1>{e(s['title'])}</h1>")
        if s.get("sub"):
            out.append(f'<div class="sub">{e(s["sub"])}</div>')
    elif kind == "stat":
        unit = f'<span class="unit">{e(s["unit"])}</span>' if s.get("unit") else ""
        out.append(f'<div class="stat">{e(s["stat"])}{unit}</div>')
        out.append(f'<div class="statline">{e(s["title"])}</div>')
    elif kind == "quote":
        out.append(f"<blockquote>{e(s['quote'])}</blockquote>")
        if s.get("attrib"):
            out.append(f'<div class="attrib">{e(s["attrib"])}</div>')
    elif kind == "mermaid":
        out.append(f"<h2>{e(s['title'])}</h2>")
        if s.get("sub"):
            out.append(f'<div class="sub" style="margin-top:14px">{e(s["sub"])}</div>')
        out.append(f'<div class="mer"><pre class="mermaid">{e(s["diagram"])}</pre></div>')
    elif kind == "image":
        out.append(f"<h2>{e(s['title'])}</h2>")
        out.append(f'<figure><img src="{e(s["image"])}" alt=""></figure>')
    elif kind == "table":
        out.append(f"<h2>{e(s['title'])}</h2><table><tr>"
                   + "".join(f"<th>{e(h)}</th>" for h in s["head"]) + "</tr>")
        for row in s["rows"]:
            cls = ' class="bad"' if str(row[0]).startswith("!") else ""
            cells = [str(c).lstrip("!") for c in row]
            out.append(f"<tr{cls}>" + f'<td class="k">{e(cells[0])}</td>'
                       + "".join(f"<td>{e(c)}</td>" for c in cells[1:]) + "</tr>")
        out.append("</table>")
    else:  # points
        out.append(f"<h2>{e(s['title'])}</h2>")
        if s.get("points"):
            out.append("<ul>" + "".join(f"<li>{e(p)}</li>" for p in s["points"]) + "</ul>")
        if s.get("sub"):
            out.append(f'<div class="sub">{e(s["sub"])}</div>')
    if s.get("photo"):
        out.insert(0, f'<div class="bg"><img src="{e(s["photo"])}" alt=""></div>')
        if s.get("credit"):
            out.append(f'<div class="credit">{e(s["credit"])}</div>')
    if s.get("source"):
        out.append(f'<div class="source">{e(s["source"])}</div>')
    if s.get("tag"):
        out.append(f'<div class="tag">{e(s["tag"])}</div>')
    return "\n  ".join(out)


def build(deck_json: Path, out_html: Path) -> Path:
    spec = json.loads(deck_json.read_text())
    sections = []
    seen = set()
    for i, s in enumerate(spec["slides"], 1):
        ident = s.get("id") or f"s{i:02d}"
        if ident in seen:
            sys.exit(f"duplicate slide id {ident!r}")
        seen.add(ident)
        cls = "slide warn" if s.get("warn") else "slide"
        if s.get("photo"):
            cls += " photo"
        if s.get("kind") == "mermaid":
            cls += " diagram"
        # A five-row table at full size runs into the source line along the
        # bottom. Shrink the type rather than dropping a row.
        if s.get("kind") == "table" and len(s.get("rows", [])) >= 5:
            cls += " tight"
        sections.append(f'<section class="{cls}" id="{ident}">\n  '
                        f"{_slide_body(s)}\n</section>")
    bg = spec.get("bg", "#0d1013")
    fg = spec.get("fg", "#f4f6f8")
    accent = spec.get("accent", "#d94f2b")
    line = spec.get("line", "#252b31")
    panel = spec.get("panel", "#1a2028")
    uses_mermaid = any(x.get("kind") == "mermaid" for x in spec["slides"])
    out_html.parent.mkdir(parents=True, exist_ok=True)
    font_link, mermaid_script = assets_beside(out_html, uses_mermaid)
    doc = DECK_PAGE.format(
        bg=bg, fg=fg, muted=spec.get("muted", "#8d97a1"), accent=accent,
        line=line, warn=spec.get("warn", "#e0a33e"),
        css=DECK_CSS, sections="\n".join(sections),
        font_link=font_link, mermaid_script=mermaid_script,
        mermaid_init=MERMAID_INIT.format(bg=bg, fg=fg, accent=accent, line=line,
                                         panel=panel) if uses_mermaid else "")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(doc)
    print(f"{out_html}  {len(sections)} slides: {', '.join(sorted(seen))}")
    return out_html


# -------------------------------------------------------------------------- card

CARD = """<!doctype html><html><head><meta charset="utf-8">
{font_link}
<style>
 * {{ margin:0; padding:0; box-sizing:border-box; }}
 body {{ background:{bg}; }}
 section.slide {{ width:1920px; height:1080px; display:flex; flex-direction:column;
   justify-content:center; padding:0 180px; background:{bg}; color:{fg};
   font-family:Inter,-apple-system,system-ui,sans-serif; }}
 .rule {{ width:120px; height:6px; background:{accent}; margin-bottom:44px; }}
 .kicker {{ font-size:30px; letter-spacing:.22em; text-transform:uppercase;
   color:{accent}; font-weight:500; margin-bottom:34px; }}
 h1 {{ font-size:{tsize}px; line-height:1.08; font-weight:700; letter-spacing:-.02em; }}
 .sub {{ font-size:38px; line-height:1.45; margin-top:40px; color:{muted}; max-width:1300px; }}
 .foot {{ position:absolute; bottom:90px; left:180px; font-size:26px; color:{muted};
   letter-spacing:.06em; }}
</style></head><body>
<section class="slide" id="{ident}">
  <div class="rule"></div>
  {kicker_html}
  <h1>{title}</h1>
  {sub_html}
  {foot_html}
</section></body></html>"""


def card(out: Path, title: str, kicker: str = "", sub: str = "", foot: str = "",
         bg: str = "#0d1013", fg: str = "#f4f6f8", accent: str = "#d94f2b",
         muted: str = "#9aa4ad") -> Path:
    tsize = 96 if len(title) > 44 else 120
    out.parent.mkdir(parents=True, exist_ok=True)
    font_link, _ = assets_beside(out, False)
    doc = CARD.format(
        font_link=font_link,
        bg=bg, fg=fg, accent=accent, muted=muted, tsize=tsize, ident=out.stem,
        title=html.escape(title),
        kicker_html=f'<div class="kicker">{html.escape(kicker)}</div>' if kicker else "",
        sub_html=f'<div class="sub">{html.escape(sub)}</div>' if sub else "",
        foot_html=f'<div class="foot">{html.escape(foot)}</div>' if foot else "")
    tmp = out.parent / f".{out.stem}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(doc)
    staging = out.parent / f".{out.stem}.shot"
    staging.mkdir(exist_ok=True)
    run(["node", str(DECKSHOT), str(tmp.resolve()), str(staging.resolve())],
        cwd=str(DECKSHOT.parent))
    made = staging / f"{out.stem}.png"
    made.replace(out)
    shutil.rmtree(staging, ignore_errors=True)
    tmp.unlink(missing_ok=True)
    print(f"{out}")
    return out


# ----------------------------------------------------------------------- segment

def segment(png: Path, out: Path, seconds: float, zoom: float = 1.07,
            direction: str = "in", anchor: str = "center", fps: int = FPS) -> Path:
    frames = max(1, round(seconds * fps))
    sw, sh = W * SUPERSAMPLE, H * SUPERSAMPLE

    if direction == "in":
        z = f"1+({zoom - 1})*on/{max(frames - 1, 1)}"
    elif direction == "out":
        z = f"{zoom}-({zoom - 1})*on/{max(frames - 1, 1)}"
    else:  # none
        z = "1"

    if anchor == "center":
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif anchor == "top":
        x, y = "iw/2-(iw/zoom/2)", "0"
    elif anchor == "bottom":
        x, y = "iw/2-(iw/zoom/2)", "ih-(ih/zoom)"
    elif anchor == "left":
        x, y = "0", "ih/2-(ih/zoom/2)"
    else:
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"

    vf = (f"scale={sw}:{sh}:force_original_aspect_ratio=decrease,"
          f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=black,"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={fps},"
          f"format=yuv420p")

    out.parent.mkdir(parents=True, exist_ok=True)
    run([enc.FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-i", str(png),
         "-vf", vf, "-frames:v", str(frames), "-r", str(fps),
         *enc.video(), "-g", str(fps * 2), "-an", str(out)])
    print(f"{out}  {frames} frames  {frames / fps:.3f} s")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="slide json -> deck html")
    b.add_argument("json")
    b.add_argument("-o", "--out", required=True)

    s = sub.add_parser("shoot", help="deck html -> one png per section.slide")
    s.add_argument("html")
    s.add_argument("-o", "--out", required=True)

    g = sub.add_parser("segment", help="png -> mp4 of an exact length, with a push-in")
    g.add_argument("png")
    g.add_argument("-o", "--out", required=True)
    g.add_argument("-d", "--duration", type=float, required=True)
    g.add_argument("--zoom", type=float, default=1.07)
    g.add_argument("--direction", default="in", choices=["in", "out", "none"])
    g.add_argument("--anchor", default="center",
                   choices=["center", "top", "bottom", "left"])

    c = sub.add_parser("card", help="render a title or end card straight to png")
    c.add_argument("-o", "--out", required=True)
    c.add_argument("--title", required=True)
    c.add_argument("--kicker", default="")
    c.add_argument("--sub", default="")
    c.add_argument("--foot", default="")
    c.add_argument("--bg", default="#0d1013")
    c.add_argument("--fg", default="#f4f6f8")
    c.add_argument("--accent", default="#d94f2b")

    a = ap.parse_args()
    if a.cmd == "build":
        build(Path(a.json).resolve(), Path(a.out).resolve())
    elif a.cmd == "shoot":
        shoot(Path(a.html).resolve(), Path(a.out).resolve())
    elif a.cmd == "segment":
        segment(Path(a.png).resolve(), Path(a.out).resolve(), a.duration,
                a.zoom, a.direction, a.anchor)
    elif a.cmd == "card":
        card(Path(a.out).resolve(), a.title, a.kicker, a.sub, a.foot,
             a.bg, a.fg, a.accent)


if __name__ == "__main__":
    main()
