"""Render the detection-timing backtest working paper to HTML and a print PDF.

Reads:  docs/working_paper/detection_timing_backtest_2026-07.md
Writes: docs/working_paper/detection_timing_backtest_2026-07.html
        docs/working_paper/detection_timing_backtest_2026-07.pdf   (with --pdf)

The PDF is typeset for submission (SSRN): Letter, 1-inch margins, Times-style
serif, centred title block, abstract on page 1, running header, page numbers,
tables and headings kept together across page breaks. It needs WeasyPrint
(already in requirements.txt).

The HTML uses inline CSS and no external dependencies so it can be:
  * opened directly in a browser
  * printed to PDF via the browser (Ctrl+P -> Save as PDF)
  * emailed / attached to outreach
  * copy-pasted into Substack (which already renders the Markdown)

No WeasyPrint dependency required (WeasyPrint on Windows needs GTK bundles
that solo/non-US environments won't have pre-installed).
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
IN_PATH = REPO_ROOT / "docs" / "working_paper" / "detection_timing_backtest_2026-07.md"
OUT_PATH = REPO_ROOT / "docs" / "working_paper" / "detection_timing_backtest_2026-07.html"
PDF_PATH = OUT_PATH.with_suffix(".pdf")
TITLE = "Detection-Timing Backtest of a Deterministic Downside-Risk Screen Across Three Modern Financial Crises"
RUNNING_HEAD = "Latif \u00b7 Detection-Timing Backtest of a Deterministic Downside-Risk Screen"

PRINT_CSS = """
@page {
    size: Letter;
    margin: 1in 1in 0.9in 1in;
    @top-center { content: "__RUNNING_HEAD__"; font: italic 8.5pt 'Liberation Serif', serif; color: #555; }
    @bottom-center { content: counter(page); font: 9pt 'Liberation Serif', serif; color: #333; }
}
@page :first { @top-center { content: none; } }
html { font-family: 'Liberation Serif', 'Times New Roman', serif; font-size: 11pt; color: #111; }
body { margin: 0; line-height: 1.38; text-align: justify; hyphens: auto; }
h1 { font-size: 17pt; line-height: 1.22; text-align: center; margin: 0 0 14pt; font-weight: bold; }
.titleblock p { text-align: center; margin: 0 0 3pt; }
.titleblock .date { margin-top: 8pt; color: #333; }
section.abstract { margin: 18pt 0.45in 0; }
section.abstract h2 { text-align: center; font-size: 11pt; text-transform: uppercase; letter-spacing: 0.08em;
    border: 0; margin: 0 0 6pt; padding: 0; }
section.abstract p { font-size: 10pt; line-height: 1.32; margin: 0 0 6pt; }
h2 { font-size: 12.5pt; margin: 18pt 0 6pt; font-weight: bold; break-after: avoid; }
h2.first-section { break-before: page; }
h3 { font-size: 11pt; font-style: italic; font-weight: bold; margin: 12pt 0 4pt; break-after: avoid; }
p { margin: 0 0 7pt; orphans: 3; widows: 3; }
ul, ol { margin: 0 0 7pt; padding-left: 18pt; }
li { margin-bottom: 3pt; }
hr { display: none; }
a { color: #1a3d7c; text-decoration: none; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.6pt; hyphens: none; }
pre { font-family: 'DejaVu Sans Mono', monospace; font-size: 8pt; line-height: 1.35; background: #f4f4f2;
    border: 0.5pt solid #ccc; padding: 6pt 8pt; text-align: left; white-space: pre-wrap; break-inside: avoid; }
pre code { font-size: 8pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 8.6pt; line-height: 1.25;
    text-align: left; hyphens: none; break-inside: avoid; }
thead { display: table-header-group; }
th { border-top: 1pt solid #111; border-bottom: 0.6pt solid #111; padding: 3pt 4pt; font-weight: bold; vertical-align: bottom; }
td { border-bottom: 0.3pt solid #bbb; padding: 3pt 4pt; vertical-align: top; }
tr:last-child td { border-bottom: 1pt solid #111; }
.nowrap { white-space: nowrap; }
section.references { break-inside: avoid; }
section.references p { padding-left: 18pt; text-indent: -18pt; text-align: left; font-size: 10pt; }
blockquote { margin: 6pt 18pt; font-size: 10pt; }
"""

CSS = """
:root { color-scheme: light dark; }
body {
    font-family: 'Georgia', 'Times New Roman', serif;
    max-width: 780px;
    margin: 2.5rem auto;
    padding: 0 1.25rem;
    line-height: 1.6;
    color: #1a1a1a;
    background: #fdfdfb;
}
h1 { font-size: 2.05rem; margin-top: 0; line-height: 1.25; }
h2 { font-size: 1.5rem; margin-top: 2.25rem; border-bottom: 1px solid #d8d3c8; padding-bottom: 0.35rem; }
h3 { font-size: 1.15rem; margin-top: 1.5rem; }
p, li { font-size: 1.02rem; }
code { font-family: 'Consolas', 'Menlo', monospace; font-size: 0.92em; background: #eee7d6; padding: 0.1rem 0.3rem; border-radius: 3px; }
pre { background: #1c1c1c; color: #f3ecdc; padding: 1rem; border-radius: 5px; overflow-x: auto; font-size: 0.9rem; }
pre code { background: none; color: inherit; padding: 0; }
table { border-collapse: collapse; margin: 1rem 0; width: 100%; font-size: 0.95rem; }
th, td { border: 1px solid #ccc4b0; padding: 0.4rem 0.65rem; text-align: left; vertical-align: top; }
th { background: #efe7d0; font-weight: 600; }
blockquote { border-left: 3px solid #b8893a; padding: 0.2rem 1rem; margin: 1rem 0; color: #4a4030; background: #f5efdd; }
hr { border: 0; border-top: 1px solid #d8d3c8; margin: 2rem 0; }
em { color: #4a4030; }
strong { color: #14161e; }
a { color: #b8893a; text-decoration: none; border-bottom: 1px solid #d5b976; }
a:hover { color: #14161e; }
@media print {
    body { background: #fff; margin: 1rem; max-width: none; }
    pre { border: 1px solid #ccc; }
}
"""


def render() -> Path:
    md_text = IN_PATH.read_text(encoding="utf-8")
    body_html = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc"],
    )
    html = (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>{TITLE}</title>\n"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body_html}\n"
        "</body>\n</html>\n"
    )
    OUT_PATH.write_text(html, encoding="utf-8")
    return OUT_PATH


_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}Z)?)")


def _print_html(body_html: str) -> str:
    """Restructure the rendered Markdown for print: title block, abstract box,
    page break before Section 1, references with hanging indents, and dates in
    table cells kept on one line."""
    soup = BeautifulSoup(body_html, "html.parser")
    h1 = soup.find("h1")
    abstract = soup.find("h2", id="abstract")
    # Title block: everything between the title and the Abstract heading.
    block = soup.new_tag("div", attrs={"class": "titleblock"})
    node = h1.find_next_sibling()
    while node is not None and node is not abstract:
        nxt = node.find_next_sibling()
        block.append(node.extract())
        node = nxt
    paras = block.find_all("p")
    if paras:
        paras[-1]["class"] = "date"
    h1.insert_after(block)
    # Abstract section: from the Abstract heading to the next h2.
    section = soup.new_tag("section", attrs={"class": "abstract"})
    abstract.insert_before(section)
    node = abstract
    while node is not None and not (node.name == "h2" and node is not abstract):
        nxt = node.find_next_sibling()
        section.append(node.extract())
        node = nxt
    if node is not None:
        node["class"] = "first-section"
    # References: hanging indents.
    refs = soup.find("h2", id="references")
    if refs is not None:
        rsec = soup.new_tag("section", attrs={"class": "references"})
        refs.insert_before(rsec)
        node = refs
        while node is not None and not (node.name == "h2" and node is not refs):
            nxt = node.find_next_sibling()
            rsec.append(node.extract())
            node = nxt
    # Dates inside table cells must not break at their hyphens.
    for cell in soup.find_all(["td", "th"]):
        for text in list(cell.find_all(string=_DATE_RE)):
            parts = _DATE_RE.split(str(text))
            new = []
            for i, part in enumerate(parts):
                if i % 2:
                    span = soup.new_tag("span", attrs={"class": "nowrap"})
                    span.string = part
                    new.append(span)
                elif part:
                    new.append(part)
            text.replace_with(*new)
    return str(soup)


def render_pdf() -> Path:
    from weasyprint import HTML

    md_text = IN_PATH.read_text(encoding="utf-8")
    body_html = markdown.markdown(md_text, extensions=["tables", "fenced_code", "toc"])
    html = (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{TITLE}</title><meta name=\"author\" content=\"Md. Zarif Latif\">"
        f"<style>{PRINT_CSS.replace('__RUNNING_HEAD__', RUNNING_HEAD)}</style></head><body>"
        f"{_print_html(body_html)}</body></html>"
    )
    HTML(string=html, base_url=str(IN_PATH.parent)).write_pdf(PDF_PATH)
    return PDF_PATH


if __name__ == "__main__":
    import sys

    out = render()
    print(f"Rendered -> {out}")
    if "--pdf" in sys.argv:
        print(f"Rendered -> {render_pdf()}")
