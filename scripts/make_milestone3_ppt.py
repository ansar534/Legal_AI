"""Generate the Milestone 3 deck.

    python scripts/make_milestone3_ppt.py

Writes docs/Milestone3_Legal_AI.pptx. Content mirrors docs/MILESTONE3_SLIDES.md
and docs/MILESTONE3_ANALYSIS.md, so the slides and the written analysis cannot
drift apart.
"""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

OUT = Path(__file__).resolve().parents[1] / "docs" / "Milestone3_Legal_AI.pptx"

TEAL_DARK = RGBColor(0x17, 0x44, 0x4C)
TEAL = RGBColor(0x0F, 0x76, 0x72)
NAVY = RGBColor(0x10, 0x3A, 0x5E)
INK = RGBColor(0x1F, 0x28, 0x33)
MUTED = RGBColor(0x5A, 0x67, 0x73)
BG = RGBColor(0xF1, 0xF3, 0xF5)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LINE = RGBColor(0xD6, 0xDE, 0xE2)
WASH = RGBColor(0xEC, 0xF3, 0xF3)
RED = RGBColor(0x9B, 0x33, 0x2B)

SANS = "Segoe UI"
MONO = "Consolas"


def flat(shape):
    shape.shadow.inherit = False
    return shape


def box(slide, x, y, w, h, fill=WHITE, line=LINE, width=1.0, radius=None,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, dash=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    flat(s)
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(width)
        if dash is not None:
            s.line.dash_style = dash
    s.text_frame.clear()
    return s


def text(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    tf.clear()
    return tf


def para(tf, runs, size=12, color=INK, bold=False, font=SANS, space_before=0,
         space_after=4, align=PP_ALIGN.LEFT, line=1.15, bullet=None, first=False,
         indent=0.0):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    p.line_spacing = line
    if indent:
        p.paragraph_format.left_indent = Inches(indent) if hasattr(p, "paragraph_format") else None
    if isinstance(runs, str):
        runs = [(runs, {})]
    if bullet:
        runs = [(bullet, {"color": TEAL, "bold": True})] + list(runs)
    for body, style in runs:
        r = p.add_run()
        r.text = body
        f = r.font
        f.size = Pt(style.get("size", size))
        f.bold = style.get("bold", bold)
        f.italic = style.get("italic", False)
        f.name = style.get("font", font)
        f.color.rgb = style.get("color", color)
    return p


def code(s, **kw):
    return (s, {"font": MONO, "size": kw.get("size", 10.5), **kw})


def header(slide, title, subtitle):
    band = box(slide, 0, 0, 13.333, 0.98, fill=TEAL_DARK, line=None,
               shape=MSO_SHAPE.RECTANGLE)
    tf = band.text_frame
    tf.margin_left = Inches(0.45)
    tf.margin_top = Inches(0.13)
    tf.vertical_anchor = MSO_ANCHOR.TOP
    para(tf, title, size=27, bold=True, color=WHITE, space_after=0, first=True)
    para(tf, subtitle, size=11.5, color=RGBColor(0xBF, 0xD6, 0xD8), space_after=0)


def slide_base(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = box(s, 0, 0, 13.333, 7.5, fill=BG, line=None, shape=MSO_SHAPE.RECTANGLE)
    s.shapes._spTree.remove(bg._element)
    s.shapes._spTree.insert(2, bg._element)
    return s


def arrow(slide, x1, y1, x2, y2, color=TEAL, width=1.5):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1),
                                   Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    c.line.fill.fore_color.rgb = color
    tail = c.line._get_or_add_ln()
    from pptx.oxml.ns import qn
    end = tail.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
    tail.append(end)
    return c


def label(slide, x, y, w, body, size=9.5, color=MUTED, bold=False, align=PP_ALIGN.LEFT):
    tf = text(slide, x, y, w, 0.24)
    para(tf, body, size=size, color=color, bold=bold, align=align, space_after=0, first=True)


# ---------------------------------------------------------------------------
# Slide 1 — container architecture
# ---------------------------------------------------------------------------
def slide_architecture(prs):
    s = slide_base(prs)
    header(s, "Container Architecture",
           "Slide 1 · Legal AI Hub — one image, two machines  ·  services, ports, volumes, network")

    # Browser entry point.
    b = box(s, 0.5, 1.12, 3.15, 0.42, fill=WHITE, line=TEAL, radius=0.45)
    tf = b.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.12)
    para(tf, [("Browser", {"bold": True, "color": NAVY}),
              ("  →  host port ", {"color": MUTED}),
              code("8501", color=TEAL, size=11)],
         size=11, space_after=0, first=True)
    arrow(s, 1.1, 1.54, 1.1, 1.72)

    # Docker host.
    box(s, 0.5, 1.72, 8.3, 5.2, fill=WHITE, line=TEAL_DARK, width=1.25, radius=0.03)
    label(s, 0.72, 1.86, 7.0,
          "Docker host  —  identical on the laptop and on the Azure VM (Milestone 2)",
          size=10, color=TEAL_DARK, bold=True)

    # Bridge network.
    box(s, 0.75, 2.3, 7.8, 2.5, fill=WASH, line=TEAL, width=1.0, radius=0.04)
    label(s, 0.95, 2.42, 6.0,
          "network: legal-ai-net   (user-defined bridge · only 8501 published)",
          size=9.5, color=TEAL)

    # App container.
    c = box(s, 1.0, 2.8, 7.3, 1.82, fill=WHITE, line=TEAL_DARK, width=1.0, radius=0.04)
    flat(box(s, 1.0, 2.8, 0.1, 1.82, fill=TEAL, line=None, shape=MSO_SHAPE.RECTANGLE))
    tf = c.text_frame
    tf.margin_left = Inches(0.3)
    tf.margin_top = Inches(0.13)
    para(tf, [("service: app", {"bold": True, "color": NAVY, "size": 14}),
              ("      ", {}),
              code("legal-ai-hub:v1", color=TEAL, size=12.5)],
         space_after=5, first=True)
    para(tf, [("Streamlit multi-page UI, 6 RAG features  ·  container port ", {"color": MUTED}),
              code("8501", color=INK), ("  ·  runs as ", {"color": MUTED}),
              code("USER appuser (uid 10001)", color=INK)],
         size=10.5, space_after=6)
    para(tf, [("Baked into the image:  ", {"bold": True, "color": TEAL_DARK}),
              code("/opt/venv", color=INK), (" deps  ·  ", {"color": MUTED}),
              code("/opt/hf-cache", color=INK), (" MiniLM weights  ·  ", {"color": MUTED}),
              code("/app/data", color=INK), (" 510 seed docs", {"color": MUTED})],
         size=10.5, space_after=3)
    para(tf, [("Injected at run time:  ", {"bold": True, "color": RED}),
              ("all four API keys, via compose ", {"color": MUTED}),
              code("env_file", color=INK), (" — never in a layer", {"color": MUTED})],
         size=10.5, space_after=0)

    arrow(s, 4.65, 4.62, 4.65, 5.12)
    label(s, 4.78, 4.84, 3.0, "named volume mounts", size=9, color=MUTED)

    # Volumes.
    vols = [
        ("legal-ai-chroma", "/app/chromadb", "contract Q&A, policies,\naudit, contract risk", "143 MB"),
        ("legal-ai-litigation", "/app/vector_store", "litigation support", "59 MB"),
        ("legal-ai-regulations", "/app/.chromadb", "live regulations search", "grows on use"),
    ]
    x = 0.9
    for name, path, purpose, size in vols:
        v = box(s, x, 5.12, 2.4, 1.46, fill=WHITE, line=LINE, radius=0.08)
        tf = v.text_frame
        tf.margin_left = Inches(0.16)
        tf.margin_top = Inches(0.11)
        para(tf, name, size=10.5, bold=True, color=NAVY, space_after=2, first=True)
        para(tf, [code("→ " + path, color=TEAL, size=9.5)], space_after=4)
        para(tf, purpose, size=9, color=MUTED, space_after=3, line=1.05)
        para(tf, size, size=9, bold=True, color=TEAL_DARK, space_after=0)
        x += 2.6
    label(s, 0.9, 6.62, 7.5,
          "Vector indexes are the only mutable state — they survive  docker compose down  and image version swaps.",
          size=9)

    # External services.
    arrow(s, 8.8, 2.45, 9.1, 2.45)
    e = box(s, 9.1, 1.72, 3.72, 1.5, fill=WHITE, line=LINE, radius=0.06)
    tf = e.text_frame
    tf.margin_left = Inches(0.18)
    tf.margin_top = Inches(0.12)
    para(tf, "HTTPS egress only", size=11, bold=True, color=NAVY, space_after=4, first=True)
    para(tf, "Groq · CourtListener · Apify · Regulations.gov",
         size=10, color=MUTED, space_after=4)
    para(tf, "No inbound path except 8501. Keys supplied per environment.",
         size=9.5, color=MUTED, space_after=0)

    # Right-hand notes.
    tf = text(s, 9.1, 3.42, 3.75, 3.5)
    para(tf, "WHAT THIS BUYS US", size=10, bold=True, color=TEAL_DARK, space_after=8, first=True)
    notes = [
        [("One service, one artifact: ", {"bold": True}),
         code("legal-ai-hub:v1", color=TEAL)],
        [("Port mapping is unchanged from Milestone 2, so the app answers on the ", {}),
         ("same URL", {"bold": True})],
        [("1.51 GB", {"bold": True}), (" on disk, ", {}), ("513 MB", {"bold": True}),
         (" to pull — ", {}), ("86 % smaller", {"bold": True}),
         (" than our first build (10.73 GB)", {})],
        [("Same ", {}), code("sha256:", color=TEAL), (" digest on the laptop and the VM — byte-for-byte one artifact", {})],
        [("Zero secrets in the image, verified by scanning ", {}),
         ("all layers", {"bold": True}), (" of the saved tarball", {})],
    ]
    for n in notes:
        para(tf, n, size=10.5, color=INK, bullet="▪  ", space_after=9, line=1.12)

    return s


# ---------------------------------------------------------------------------
# Slide 2 — before and after
# ---------------------------------------------------------------------------
def slide_before_after(prs):
    s = slide_base(prs)
    header(s, "Before and After",
           "Slide 2 · Hand-built VM versus a versioned container artifact")

    # Last field marks the "after" cell as a literal command, rendered in mono.
    rows = [
        ("Deploy steps", "~12 manual commands over SSH", "docker compose pull && up -d", True),
        ("Time to deploy", "25–40 minutes", "~2 minutes (pull + start)", False),
        ("Python runtime", "whatever apt happened to give us", "pinned python:3.12-slim", True),
        ("Dependencies", "pip resolved live, different each run", "frozen into an image layer at build time", False),
        ("510 seed documents", "scp'd to the VM by hand", "shipped inside the image", False),
        ("Embedding model", "downloaded from HF on first use", "pre-baked, runs fully offline", False),
        ("Rollback", "reinstall and hope", "TAG=v1 and restart", True),
        ("Reproducibility", "\u201cworks on my machine\u201d", "same sha256 digest on both machines", False),
    ]

    head_h, row_h = 0.34, 0.345
    table_h = head_h + row_h * len(rows)
    gs = s.shapes.add_table(len(rows) + 1, 3, Inches(0.5), Inches(1.18),
                            Inches(8.3), Inches(table_h))
    tbl = gs.table
    tbl.first_row = True
    tbl.horz_banding = False
    tbl.columns[0].width = Inches(1.95)
    tbl.columns[1].width = Inches(3.1)
    tbl.columns[2].width = Inches(3.25)
    tbl.rows[0].height = Inches(head_h)
    for r in range(1, len(rows) + 1):
        tbl.rows[r].height = Inches(row_h)

    heads = ("", "Milestone 2 — manual VM", "Milestone 3 — container")
    for c, body in enumerate(heads):
        cell = tbl.cell(0, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = TEAL_DARK
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.12)
        cell.text_frame.clear()
        para(cell.text_frame, body, size=10.5, bold=True, color=WHITE,
             space_after=0, first=True)

    for r, (field, before, after, is_cmd) in enumerate(rows, start=1):
        for c, body in enumerate((field, before, after)):
            cell = tbl.cell(r, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if r % 2 else RGBColor(0xF7, 0xFA, 0xFA)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = Inches(0.12)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.text_frame.clear()
            if c == 0:
                para(cell.text_frame, body, size=10, bold=True, color=NAVY,
                     space_after=0, first=True)
            elif c == 1:
                para(cell.text_frame, body, size=10, color=MUTED, space_after=0, first=True)
            else:
                para(cell.text_frame,
                     [code(body, color=TEAL_DARK, size=10)] if is_cmd
                     else [(body, {"color": TEAL_DARK, "bold": True})],
                     size=10, space_after=0, first=True)

    # Stat cards.
    stats = [
        ("1.51 GB", "final image · 513 MB to pull"),
        ("86 %", "smaller than our naive first build"),
        ("0", "secrets found in 513 MB of layers"),
    ]
    y = 1.18
    for value, caption in stats:
        card = box(s, 9.1, y, 3.72, 0.84, fill=WHITE, line=LINE, radius=0.08)
        flat(box(s, 9.1, y, 0.09, 0.84, fill=TEAL, line=None, shape=MSO_SHAPE.RECTANGLE))
        tf = card.text_frame
        tf.margin_left = Inches(0.26)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        para(tf, value, size=20, bold=True, color=NAVY, space_after=1, first=True)
        para(tf, caption, size=9.5, color=MUTED, space_after=0)
        y += 0.98

    # Budget guardrails card.
    card = box(s, 9.1, 4.12, 3.72, 1.48, fill=WHITE, line=LINE, radius=0.07)
    tf = card.text_frame
    tf.margin_left = Inches(0.22)
    tf.margin_top = Inches(0.13)
    para(tf, "BUDGET GUARDRAILS STILL ACTIVE", size=9.5, bold=True, color=TEAL_DARK,
         space_after=6, first=True)
    para(tf, [("Subscription-scoped budget ", {"color": MUTED}),
              code("legal-ai-monthly", color=INK, size=9.5),
              (" — covers registry, VM, disk, IP and egress.", {"color": MUTED})],
         size=9.5, space_after=5, line=1.1)
    para(tf, [("Alerts at ", {"color": MUTED}),
              ("10 % · 20 % · 25 % · 50 % · 100 %", {"bold": True, "color": NAVY}),
              (" of actual spend, emailing the whole team.", {"color": MUTED})],
         size=9.5, space_after=0, line=1.1)

    # The problem solved.
    card = box(s, 0.5, 4.42, 8.3, 2.5, fill=WHITE, line=LINE, radius=0.04)
    flat(box(s, 0.5, 4.42, 0.11, 2.5, fill=RED, line=None, shape=MSO_SHAPE.RECTANGLE))
    tf = card.text_frame
    tf.margin_left = Inches(0.32)
    tf.margin_right = Inches(0.28)
    tf.margin_top = Inches(0.16)
    para(tf, "THE SPECIFIC PROBLEM CONTAINERIZATION SOLVED FOR OUR TEAM",
         size=10, bold=True, color=RED, space_after=8, first=True)
    para(tf, [("Our laptops and the VM had silently drifted apart.", {"bold": True, "color": NAVY}),
              (" The VM resolved a different transitive dependency set than our laptops did, so a "
               "feature that worked locally failed on the VM and we burned hours diffing ", {"color": INK}),
              code("pip freeze", color=INK),
              (" output over SSH. Nobody could say what was actually deployed, because the VM's "
               "state was the sum of every command anyone had ever typed into it.", {"color": INK})],
         size=11.5, space_after=8, line=1.18)
    para(tf, [("The image removes the guesswork.", {"bold": True, "color": NAVY}),
              (" The dependency set is resolved ", {"color": INK}),
              ("once", {"bold": True, "color": INK}),
              (", at build time, and frozen into a layer identified by a digest. The VM installs "
               "nothing — it pulls a finished artifact. ", {"color": INK}),
              ("\u201cWhat's running in production?\u201d went from an investigation to reading one "
               "sha256 string.", {"color": INK, "italic": True})],
         size=11.5, space_after=0, line=1.18)

    label(s, 0.5, 7.02, 8.3,
          "Easier than Milestone 2: a teammate joins the project with one  docker compose up  "
          "instead of a 12-step runbook — and gets the same thing the VM runs.",
          size=9.5)

    return s


# ---------------------------------------------------------------------------
# Slide 3 — team contribution
# ---------------------------------------------------------------------------
def slide_team(prs):
    s = slide_base(prs)
    header(s, "Team Contribution", "Slide 3 · Who owned each part of the milestone")

    members = [
        ("Adithi Damera and Riya Dhanduke",
         "Presentation — PowerPoint slides, the demo walkthrough, and the recorded video"),
        ("Amulya Kanuparthi, Yash Padhye, and Md Ansar Ur Rahman",
         "Containerization — Dockerfile and .dockerignore, docker-compose wiring, the v1 push to "
         "Artifact Registry, the pull-and-run on the Azure VM, and the budget alerts"),
    ]

    y = 1.6
    for name, duty in members:
        card = box(s, 0.5, y, 12.33, 1.7, fill=WHITE, line=LINE, radius=0.05)
        flat(box(s, 0.5, y, 0.14, 1.7, fill=TEAL, line=None, shape=MSO_SHAPE.RECTANGLE))
        tf = card.text_frame
        tf.margin_left = Inches(0.42)
        tf.margin_right = Inches(0.4)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        para(tf, name, size=20, bold=True, color=NAVY, space_after=8, first=True)
        para(tf, duty, size=13.5, color=MUTED, space_after=0, line=1.15)
        y += 2.0

    card = box(s, 0.5, y + 0.1, 12.33, 0.62, fill=WASH, line=None, radius=0.1)
    tf = card.text_frame
    tf.margin_left = Inches(0.42)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para(tf, [("Reviewed by all five of us: ", {"bold": True, "color": TEAL_DARK}),
              ("the written analysis, the image-size measurements, and the "
               "no-secrets-in-any-layer verification.", {"color": MUTED})],
         size=11.5, space_after=0, first=True)

    return s


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide_architecture(prs)
    slide_before_after(prs)
    slide_team(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
