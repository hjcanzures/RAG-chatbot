"""Turns raw HTML / PDF bytes into clean Markdown (headings, paragraphs, lists, tables)."""
import json
import posixpath
import re
from io import BytesIO
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString
from pypdf import PdfReader

import config
from crawler import in_scope, normalize_url


class SkipPage(Exception):
    """Raised when a page is deliberately not turned into a document."""


_NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe", "nav", "footer", "aside",
               "button", "select", "template", "input", "textarea"]
_NOISE_ATTR = re.compile(
    r"(^|[\s_-])(nav|navbar|menu|footer|sidebar|breadcrumbs?|cookie|social|share|sharing|"
    r"popup|modal|advert|skip-link|search)([\s_-]|$)", re.I)
_HEADINGS = {f"h{i}": i for i in range(1, 7)}
_PARAGRAPHS = {"p", "blockquote", "pre", "dd", "dt", "figcaption", "address", "caption"}
_CONTAINERS = {"div", "section", "article", "main", "header", "figure", "details", "summary",
               "body", "li", "center", "font", "tbody", "thead"}
_BLOCK_NAMES = list(_HEADINGS) + ["p", "ul", "ol", "table", "div", "li", "section"]
_BULLET = re.compile(r"^(?:[●•▪■◦‣∙]|[-–—*]\s|\d{1,2}[.)]\s)")


def _clean(text):
    text = (text or "").replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


# ---------------------------------------------------------------- HTML

def extract_html(content, url):
    soup = BeautifulSoup(content, "lxml")
    if soup.find("input", attrs={"type": "password"}):
        raise SkipPage("Login form detected (not crawled)")

    published, modified, canonical = _metadata(soup, url)   # before noise removal (JSON-LD is a <script>)
    _strip_noise(soup)
    root = _main_root(soup)
    for br in root.find_all("br"):
        br.replace_with(" ")
    title = _title(soup, root, url)
    related = _related_links(root, url)
    body = _render(root, title)
    return {"title": title, "body": body, "related": related, "date_published": published,
            "date_modified": modified, "canonical": canonical, "document_type": "webpage"}


def _metadata(soup, url):
    def meta(*names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    published = meta("article:published_time", "datePublished", "og:published_time")
    modified = meta("article:modified_time", "dateModified", "og:updated_time")
    if not published or not modified:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
            except ValueError:
                continue
            for item in (data if isinstance(data, list) else [data]):
                if isinstance(item, dict):
                    if not published and isinstance(item.get("datePublished"), str):
                        published = item["datePublished"]
                    if not modified and isinstance(item.get("dateModified"), str):
                        modified = item["dateModified"]
    canonical = None
    link = soup.find("link", attrs={"rel": "canonical"})
    if link and link.get("href"):
        try:
            canonical = normalize_url(urljoin(url, link["href"]))
        except ValueError:
            canonical = None
    return published, modified, canonical


def _strip_noise(soup):
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    body = soup.body or soup
    total = len(body.get_text()) or 1
    for el in list(soup.find_all(True)):
        if el.decomposed or el.name in ("html", "head", "body", "main", "article"):
            continue
        ident = " ".join(el.get("class", [])) + " " + (el.get("id") or "")
        # Never remove something that holds most of the page's text (guards against
        # themes that put "menu-open" or similar on a wrapper).
        if _NOISE_ATTR.search(ident) and len(el.get_text()) < total * 0.5:
            el.decompose()
    for header in soup.find_all("header"):
        if not header.decomposed and not header.find("h1"):
            header.decompose()


def _main_root(soup):
    for selector in ("main", "article", "[role=main]", "#content", "#main-content",
                     ".entry-content", ".post-content", ".page-content", ".content"):
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 200:
            return el
    return soup.body or soup


def _title(soup, root, url):
    h1 = root.find("h1")
    text = _clean(h1.get_text()) if h1 else ""
    if text and len(text) <= 150:
        return text
    if soup.title and soup.title.get_text(strip=True):
        first = re.split(r"\s+[|–—-]\s+", _clean(soup.title.get_text()))[0]
        if first:
            return first
    slug = posixpath.basename(urlsplit(url).path.rstrip("/"))
    return slug.replace("-", " ").replace("_", " ").title() or "Untitled"


def _related_links(root, base):
    out, seen = [], set()
    for a in root.find_all("a", href=True):
        text = _clean(a.get_text())
        href = a["href"].strip()
        if not text or len(text) > 120 or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            key = normalize_url(urljoin(base, href))
        except ValueError:
            continue
        if key in seen or not in_scope(key):
            continue
        seen.add(key)
        out.append((text, key))
        if len(out) >= 15:
            break
    return out


def _list_md(lst, depth=0):
    lines, ordered = [], lst.name == "ol"
    for n, li in enumerate(lst.find_all("li", recursive=False), 1):
        parts, nested = [], []
        for ch in li.children:
            if isinstance(ch, Comment):
                continue
            if isinstance(ch, NavigableString):
                parts.append(str(ch))
            elif ch.name in ("ul", "ol"):
                nested.append(ch)
            else:
                parts.append(ch.get_text())
        text = _clean(" ".join(parts))
        if text:
            lines.append("  " * depth + (f"{n}. " if ordered else "- ") + text)
        for sub in nested:
            nested_md = _list_md(sub, depth + 1)
            if nested_md:
                lines.append(nested_md)
    return "\n".join(lines)


def _table_md(table):
    rows = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:        # belongs to a nested table
            continue
        cells = []
        for cell in tr.find_all(["th", "td"], recursive=False):
            cells.append(_clean(cell.get_text(" ")).replace("|", "/"))
            span = str(cell.get("colspan", "1"))
            cells.extend([""] * (min(int(span), 10) - 1 if span.isdigit() and int(span) > 1 else 0))
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    if width == 1:
        return "\n\n".join(r[0] for r in rows)
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _render(root, title):
    out, buf, state = [], [], {"title_used": False}

    def add(block):
        if block and (not out or out[-1] != block):
            out.append(block)

    def flush():
        text = _clean(" ".join(buf))
        buf.clear()
        if text:
            add(text)

    def walk(el):
        for ch in el.children:
            if isinstance(ch, Comment):
                continue
            if isinstance(ch, NavigableString):
                buf.append(str(ch))
                continue
            name = ch.name
            if name in _HEADINGS:
                flush()
                text = _clean(ch.get_text())
                if not text:
                    continue
                if text == title and not state["title_used"]:
                    state["title_used"] = True      # the document title is added separately
                    continue
                add("#" * min(6, max(2, _HEADINGS[name])) + " " + text)
            elif name in ("ul", "ol"):
                flush()
                add(_list_md(ch))
            elif name == "table":
                flush()
                add(_table_md(ch))
            elif name in _PARAGRAPHS:
                flush()
                add(_clean(ch.get_text()))
            elif name in _CONTAINERS or ch.find(_BLOCK_NAMES):
                flush()
                walk(ch)
                flush()
            else:
                buf.append(ch.get_text())

    walk(root)
    flush()
    return "\n\n".join(out)


# ---------------------------------------------------------------- PDF

def extract_pdf(content, url):
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise SkipPage("Encrypted PDF")
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        lines = [" ".join(line.split()) for line in block.splitlines() if line.strip()]
        merged = []
        for line in lines:
            if merged and not _BULLET.match(line):
                merged[-1] += " " + line
            else:
                merged.append(line)
        if merged:
            paragraphs.append("\n".join(merged))
    body = "\n\n".join(paragraphs)
    if len(body) < config.MIN_CONTENT_CHARS:
        raise SkipPage("No extractable text (scanned PDF? it would need OCR)")

    title = ""
    try:
        if reader.metadata and reader.metadata.title:
            title = _clean(str(reader.metadata.title))
    except Exception:
        title = ""
    if len(title) < 5 or title.lower().startswith("untitled"):
        stem = posixpath.splitext(unquote(posixpath.basename(urlsplit(url).path)))[0]
        title = _clean(stem.replace("_", " ").replace("-", " ")) or "PDF document"
    return {"title": title, "body": body, "related": [], "date_published": None,
            "date_modified": None, "canonical": None, "document_type": "pdf"}