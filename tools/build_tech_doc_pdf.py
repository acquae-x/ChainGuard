"""把 ChainGuard/docs/技术方案说明书.md 渲染成印刷级 PDF。

流程：Markdown → 带排版样式的 HTML → 无头 Chrome/Edge 打印为 A4 PDF。
正文内容与 .md 原文逐字一致，只增加封面标题块、目录与页码。

用法：
    python tools/build_tech_doc_pdf.py
    python tools/build_tech_doc_pdf.py --src <md 路径> --out <pdf 路径>
"""

from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "ChainGuard" / "docs" / "技术方案说明书.md"
PRINTER = Path(__file__).resolve().parent / "print_html_to_pdf.mjs"

CSS = """
@page {
  size: A4;
  margin: 20mm 18mm 18mm 18mm;
}
:root {
  --ink: #1a1a1a;
  --muted: #5a5a5a;
  --rule: #d8dde3;
  --accent: #1f4e79;
  --accent-soft: #f2f6fa;
  --code-bg: #f6f7f9;
}
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  margin: 0;
  color: var(--ink);
  font-family: "Microsoft YaHei", "Source Han Sans SC", "Noto Sans CJK SC",
               "PingFang SC", "Segoe UI", sans-serif;
  font-size: 10.5pt;
  line-height: 1.75;
  text-align: justify;
}
p { margin: 0 0 0.7em; }
strong { color: #10365a; }

/* ---- 封面页 ---- */
.title-page {
  min-height: 88vh; display: flex; flex-direction: column; justify-content: center;
  break-after: page; page-break-after: always;
}
.title-page .eyebrow {
  font-size: 10pt; letter-spacing: 2pt; color: var(--muted);
  text-transform: uppercase; margin-bottom: 10pt;
}
.title-page .doc-title {
  font-size: 28pt; font-weight: 700; color: var(--accent);
  line-height: 1.35; letter-spacing: 1pt; margin: 0;
}
.title-page .rule {
  width: 60pt; height: 3pt; background: var(--accent); margin: 14pt 0 18pt;
}
.title-page blockquote { margin: 0 0 22pt; font-size: 10.5pt; }
.title-page .doc-meta {
  font-size: 9pt; color: var(--muted); border-top: 0.6pt solid var(--rule);
  padding-top: 8pt;
}

/* ---- 目录 ---- */
.toc {
  background: var(--accent-soft); border: 0.6pt solid var(--rule);
  border-radius: 3pt; padding: 10pt 14pt; margin: 0 0 18pt;
  break-inside: avoid; page-break-inside: avoid;
}
.toc h2 { font-size: 12pt; margin: 0 0 6pt; color: var(--accent); border: 0; padding: 0; }
.toc ol { margin: 0; padding-left: 1.2em; }
.toc > ol { list-style: none; padding-left: 0; }
.toc > ol > li { margin-top: 3pt; font-weight: 600; }
.toc ol ol { list-style: none; padding-left: 1em; }
.toc ol ol li { font-weight: 400; font-size: 9.5pt; color: var(--muted); margin-top: 1pt; }
.toc a { color: inherit; text-decoration: none; }

/* ---- 标题 ---- */
h1, h2, h3, h4 { break-after: avoid; page-break-after: avoid; text-align: left; }
h2 {
  font-size: 14pt; color: var(--accent); margin: 15pt 0 8pt;
  padding-bottom: 3pt; border-bottom: 1pt solid var(--rule);
}
h3 { font-size: 11.5pt; margin: 14pt 0 5pt; color: #10365a; }
h4 { font-size: 10.5pt; margin: 10pt 0 4pt; }

/* ---- 表格 ---- */
table {
  width: 100%; border-collapse: collapse; margin: 8pt 0 12pt;
  font-size: 9.5pt; line-height: 1.5;
}
thead { background: var(--accent); color: #fff; }
th, td {
  border: 0.6pt solid var(--rule); padding: 4pt 6pt;
  text-align: left; vertical-align: top; word-break: break-word;
}
th { font-weight: 600; }
/* 首列多为短标签，不要被挤成「后端测 试」这种断行 */
th:first-child, td:first-child { word-break: keep-all; }
tbody tr:nth-child(even) { background: #fafbfc; }
tr { break-inside: avoid; page-break-inside: avoid; }
thead { display: table-header-group; }

/* ---- 代码 ---- */
pre {
  background: var(--code-bg); border: 0.6pt solid var(--rule);
  border-left: 2.5pt solid var(--accent);
  padding: 6pt 9pt; margin: 8pt 0 10pt;
  font-size: 8.8pt; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  break-inside: avoid; page-break-inside: avoid;
}
pre, code {
  font-family: Consolas, "Cascadia Mono", "Microsoft YaHei", monospace;
}
code {
  background: var(--code-bg); border: 0.5pt solid var(--rule);
  border-radius: 2pt; padding: 0.5pt 3pt; font-size: 9pt;
}
pre code { background: none; border: 0; padding: 0; font-size: inherit; }

/* ---- 引用块 ---- */
blockquote {
  margin: 8pt 0 12pt; padding: 6pt 10pt;
  background: #fffbf0; border-left: 2.5pt solid #e0a020;
  color: #3d3222; font-size: 10pt;
}
blockquote p:last-child { margin-bottom: 0; }

/* ---- 列表与分隔线 ---- */
ul, ol { margin: 0 0 0.7em; padding-left: 1.5em; }
li { margin-bottom: 2pt; }
hr { border: 0; border-top: 0.6pt solid var(--rule); margin: 11pt 0; }
/* 末段不要单独孤立成一页 */
pre:last-of-type { break-after: avoid; page-break-after: avoid; }
"""

HTML_SHELL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<section class="title-page">
  <div class="eyebrow">ChainGuard</div>
  <div class="doc-title">{heading}</div>
  <div class="rule"></div>
  {lead}
  <div class="doc-meta">{meta}</div>
</section>
{toc}
{body}
</body>
</html>
"""

# 判断"软换行两侧能否直接接合"用到的字符集
CJK_IDEO = r"㐀-䶿一-鿿豈-﫿"
CJK_PUNCT = r"—‘-”　-〿＀-￯"
RE_JOIN_BOTH_CJK = re.compile(rf"[{CJK_IDEO}{CJK_PUNCT}]$")
RE_JOIN_PUNCT_LEFT = re.compile(rf"[{CJK_PUNCT}]$")
RE_STARTS_CJK = re.compile(rf"^[{CJK_IDEO}{CJK_PUNCT}]")
RE_STARTS_INLINE = re.compile(r"^[0-9A-Za-z`*\[(]")
# 新块的起头绝不能被接到上一行：有序/无序列表项、标题、表格行、围栏、分隔线
RE_BLOCK_START = re.compile(r"^(?:\d+[.)]\s|[-+]\s|\*\s|>|\||#|```|---|===)")


def join_cjk_soft_breaks(md_text: str) -> str:
    """合并中文段落内的软换行。

    .md 原文为了 80 列可读性在句子中间断行，Markdown 会把换行渲染成一个空格，
    在中文里就成了「不知道 出事了」这种多余空隙。这里按中文排版惯例接合：
    两侧都是中日韩字符时直接相连；左侧是全角标点时也直接相连（标点自带间距）；
    中英之间保留空格。代码块内一律不动。
    """
    out: list[str] = []
    in_fence = False
    for raw in md_text.splitlines():
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(raw)
            continue
        if in_fence or not out:
            out.append(raw)
            continue

        prev = out[-1]
        cont = raw.lstrip()
        prev_is_quote = prev.lstrip().startswith(">")
        if prev_is_quote and cont.startswith(">"):
            cont = cont[1:].lstrip()
        if not prev.strip() or not cont:
            out.append(raw)
            continue
        if prev.lstrip().startswith(("|", "#")) or prev.rstrip().endswith(("  ", "\\")):
            out.append(raw)
            continue
        if RE_BLOCK_START.match(cont):
            out.append(raw)
            continue

        joinable = (RE_JOIN_BOTH_CJK.search(prev) and RE_STARTS_CJK.match(cont)) or (
            RE_JOIN_PUNCT_LEFT.search(prev) and RE_STARTS_INLINE.match(cont)
        )
        if joinable:
            out[-1] = prev + cont
        else:
            out.append(raw)
    return "\n".join(out)


def slugify(text: str, seen: dict[str, int]) -> str:
    base = re.sub(r"[^\w一-鿿]+", "-", text).strip("-") or "sec"
    seen[base] = seen.get(base, 0) + 1
    return base if seen[base] == 1 else f"{base}-{seen[base]}"


def split_front_matter(md_text: str) -> tuple[str, str, str]:
    """拆出 H1 标题、紧跟的引言块、以及剩余正文。"""
    lines = md_text.splitlines()
    title = "文档"
    idx = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        idx = 1
    # 跳过标题后的空行，把紧随的引用块当作副标题/纪律声明
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    lead: list[str] = []
    while idx < len(lines) and lines[idx].startswith(">"):
        lead.append(lines[idx])
        idx += 1
    while idx < len(lines) and (not lines[idx].strip() or lines[idx].strip() == "---"):
        idx += 1
    return title, "\n".join(lead), "\n".join(lines[idx:])


def build_toc(body_html: str) -> tuple[str, str]:
    """给 h2/h3 加锚点，并生成两级目录。"""
    seen: dict[str, int] = {}
    entries: list[tuple[int, str, str]] = []

    def add_anchor(match: re.Match[str]) -> str:
        level = int(match.group(1))
        inner = match.group(2)
        text = html.unescape(re.sub(r"<[^>]+>", "", inner))
        anchor = slugify(text, seen)
        entries.append((level, anchor, text))
        return f'<h{level} id="{anchor}">{inner}</h{level}>'

    body_html = re.sub(r"<h([23])>(.*?)</h\1>", add_anchor, body_html, flags=re.S)

    parts = ['<nav class="toc"><h2>目录</h2><ol>']
    open_sub = False
    for level, anchor, text in entries:
        if level == 2:
            if open_sub:
                parts.append("</ol></li>")
                open_sub = False
            parts.append(f'<li><a href="#{anchor}">{html.escape(text)}</a>')
            parts.append("</li>")
        else:
            if parts[-1] == "</li>":
                parts.pop()
                parts.append("<ol>")
                open_sub = True
            elif not open_sub:
                parts.append("<li><ol>")
                open_sub = True
            parts.append(f'<li><a href="#{anchor}">{html.escape(text)}</a></li>')
    if open_sub:
        parts.append("</ol></li>")
    parts.append("</ol></nav>")
    return body_html, "".join(parts)


def source_date(md_path: Path) -> date:
    """Return stable build metadata: SOURCE_DATE_EPOCH or the source commit date."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).date()
    try:
        relative = md_path.resolve().relative_to(ROOT).as_posix()
        value = subprocess.check_output(
            ["git", "-C", str(ROOT), "log", "-1", "--format=%cs", "--", relative],
            text=True,
        ).strip()
        if value:
            return date.fromisoformat(value)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return date(1970, 1, 1)


def render_html(md_path: Path) -> tuple[str, str, date]:
    md_text = join_cjk_soft_breaks(md_path.read_text(encoding="utf-8"))
    title, lead_md, body_md = split_front_matter(md_text)
    converter = markdown.Markdown(
        extensions=["tables", "fenced_code", "sane_lists", "attr_list", "md_in_html"]
    )
    lead_html = converter.convert(lead_md) if lead_md else ""
    converter.reset()
    body_html = converter.convert(body_md)
    body_html, toc_html = build_toc(body_html)
    build_date = source_date(md_path)
    meta = (
        f"由 {md_path.parent.name}/{md_path.name} 自动生成 · "
        f"{build_date.isoformat()} · 内容与仓库同版本"
    )
    heading = title
    if heading.startswith("ChainGuard "):
        heading = heading[len("ChainGuard ") :]
    return title, HTML_SHELL.format(
        title=html.escape(title),
        heading=html.escape(heading),
        css=CSS,
        meta=html.escape(meta),
        lead=lead_html,
        toc=toc_html,
        body=body_html,
    ), build_date


def normalize_pdf_metadata(pdf_path: Path, title: str, build_date: date) -> None:
    """Rewrite volatile browser metadata so the same commit builds deterministically."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    pdf_date = f"D:{build_date.strftime('%Y%m%d')}000000+00'00'"
    writer.add_metadata({
        "/Title": title,
        "/Author": "ChainGuard contributors",
        "/Creator": "tools/build_tech_doc_pdf.py",
        "/Producer": "pypdf",
        "/CreationDate": pdf_date,
        "/ModDate": pdf_date,
    })
    temporary = pdf_path.with_suffix(".normalized.pdf")
    with temporary.open("wb") as stream:
        writer.write(stream)
    temporary.replace(pdf_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--keep-html", action="store_true", help="保留中间 HTML")
    args = parser.parse_args()

    src: Path = args.src
    if not src.exists():
        print(f"找不到源文件：{src}", file=sys.stderr)
        return 1
    out: Path = args.out or src.with_suffix(".pdf")
    html_path = out.with_suffix(".html")

    title, page, build_date = render_html(src)
    html_path.write_text(page, encoding="utf-8")

    result = subprocess.run(
        ["node", str(PRINTER), str(html_path), str(out), title],
        cwd=str(ROOT),
        shell=sys.platform == "win32",
    )
    if result.returncode != 0:
        print("PDF 渲染失败（HTML 已保留在 %s）" % html_path, file=sys.stderr)
        return result.returncode
    normalize_pdf_metadata(out, title, build_date)
    if not args.keep_html:
        html_path.unlink(missing_ok=True)
    print(f"已生成：{out}  ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
