import hashlib
import json
import math
import os
import re
import traceback
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from urllib.parse import unquote_plus

import boto3
from pypdf import PdfReader

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

UUID_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-"
)


def _clean_name(key):
    return UUID_PREFIX.sub("", os.path.basename(key))


def _doc_title(key):
    # "Mock_Proposed_Enrollment_and_Tuition_Fees.docx" -> "Mock Proposed Enrollment and Tuition Fees"
    # Underscores carry no meaning for the embedding model; spaces do.
    return os.path.splitext(_clean_name(key))[0].replace("_", " ").strip()


s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
s3vectors = boto3.client("s3vectors")

VECTOR_BUCKET_NAME = os.environ["VECTOR_BUCKET_NAME"]
VECTOR_INDEX_NAME = os.environ["VECTOR_INDEX_NAME"]
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "cohere.embed-multilingual-v3")

# Cohere embed v3 truncates at 512 tokens (~1.5-2k chars), so stay under that.
MAX_CHARS = int(os.environ.get("MAX_CHARS", "1200"))
OVERLAP_CHARS = int(os.environ.get("OVERLAP_CHARS", "150"))
BATCH_SIZE = 96  # Cohere max texts per call
LOG_CHUNKS = os.environ.get("LOG_CHUNKS", "0") == "1"  # debug only

# Characters PDFs sprinkle in after bullets etc. that break matching.
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
# A line that starts a list item (bullet glyph, "- ", "1." / "1)").
_BULLET = re.compile(r"^(?:[●•▪■◦‣∙]|[-–—*]\s|\d{1,2}[.)]\s)")
# Short words that can legitimately follow an e-mail/URL on the next line.
_SHORT_WORDS = {"and", "or", "for", "to", "the", "of", "in", "on", "at", "by",
                "is", "if", "no", "an", "as", "we", "us", "so", "be", "it"}
# First-column labels that mark a two-column key/value table (not a lookup table).
_KEY_VALUE_HEADERS = {"field", "item", "property", "attribute", "key",
                      "parameter", "detail", "element"}


def lambda_handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        print(f"Processing s3://{bucket}/{key}")

        try:
            raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            markdown = _extract_markdown(key, raw)
            print(f"Extracted {len(markdown)} chars from {key}")

            if not markdown.strip():
                print(f"No text extracted from {key}, skipping.")
                continue

            title = _doc_title(key)
            chunks = _chunk_markdown(markdown, title)
            print(f"Split '{key}' into {len(chunks)} chunks.")

            if LOG_CHUNKS:
                for i, c in enumerate(chunks):
                    print(f"===== CHUNK {i} ({len(c['text'])} chars) =====\n{c['text']}")

            _embed_and_store(chunks, source_key=key)
        except Exception:
            print(f"FAILED processing {key}")
            traceback.print_exc()

    return {"statusCode": 200, "body": json.dumps({"message": "Processing complete"})}


# ---------------------------------------------------------------- extraction
# Everything is normalised to lightweight markdown (#headings, paragraphs,
# pipe tables) so ONE chunker handles every file type.

def _detect_format(key, raw):
    if raw.startswith(b"%PDF-"):
        return "pdf"
    if raw.startswith(b"PK"):
        try:
            with zipfile.ZipFile(BytesIO(raw)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
    ext = os.path.splitext(key)[1].lower().lstrip(".")
    if ext in ("txt", "md", "csv") or (not ext and b"\x00" not in raw[:1024]):
        return "txt"
    return ext or "unknown"


def _extract_markdown(key, raw):
    fmt = _detect_format(key, raw)
    if fmt == "txt":
        return raw.decode("utf-8", errors="ignore")
    if fmt == "pdf":
        return _pdf_to_markdown(raw)
    if fmt == "docx":
        return _docx_to_markdown(raw)
    raise ValueError(f"Unsupported file type: {fmt}")


def _norm_text(text):
    return " ".join((text or "").translate(_ZERO_WIDTH).split())


def _block_text(text):
    """PDF text block -> text with one line per list item, other lines joined."""
    out = []
    for line in (text or "").translate(_ZERO_WIDTH).splitlines():
        line = " ".join(line.split())
        if not line:
            continue
        if out and not _BULLET.match(line):
            out[-1] += " " + line
        else:
            out.append(line)
    return "\n".join(out)


def _running_text_keys(doc):
    """Header/footer text repeated on most pages (letterheads, 'Page 3 of 20').
    Returned as (normalised text, rounded y) keys so they can be skipped."""
    pages = len(doc)
    if pages < 2:
        return set()
    seen = {}
    for page in doc:
        height = page.rect.height
        keys = set()
        for x0, y0, x1, y1, text, _no, btype in page.get_text("blocks"):
            if btype != 0 or not text.strip():
                continue
            if y1 < height * 0.10 or y0 > height * 0.90:
                keys.add((re.sub(r"\d+", "#", _norm_text(text).lower()), round(y0 / 6)))
        for key in keys:
            seen[key] = seen.get(key, 0) + 1
    needed = max(2, math.ceil(pages / 2))
    return {key for key, count in seen.items() if count >= needed}


def _pdf_to_markdown(raw):
    # PyMuPDF: find_tables() detects tables; text outside tables is kept as
    # paragraphs; everything is emitted in page reading order.
    try:
        import pymupdf

        def clean(c):
            return _norm_text(c).replace("|", "/")

        def cell_text(page, bbox):
            # Re-read the words inside the cell instead of using t.extract():
            # on some PDFs extract() drops spaces and interleaves the lines of
            # a wrapped cell. Lines are then re-joined, repairing words that the
            # PDF broke across a line ("...@neu.exampl" / "e", "exchange-" /
            # "program") instead of leaving a stray space inside them.
            words = page.get_text("words", clip=pymupdf.Rect(bbox))
            words.sort(key=lambda w: (w[5], w[6], w[7]))  # block, line, word
            lines, order = {}, []
            for w in words:
                k = (w[5], w[6])
                if k not in lines:
                    lines[k] = []
                    order.append(k)
                lines[k].append(w[4])
            text, prev = "", None
            for k in order:
                tokens = lines[k]
                if prev is None:
                    text = " ".join(tokens)
                else:
                    last, first = prev[-1], tokens[0]
                    glue = " "
                    if (("@" in last or "://" in last) and len(first) <= 3
                            and first.islower() and first not in _SHORT_WORDS):
                        glue = ""  # e-mail / URL split mid-token
                    elif last.endswith("-") and len(last) > 1 and first[:1].islower():
                        glue = ""  # hyphenated line break
                    elif "/" in last and len(first) == 1 and first.islower() and first not in ("a", "i"):
                        glue = ""  # 'corridors/classroom' + 's'
                    text += glue + " ".join(tokens)
                prev = tokens
            return clean(text)

        def rows_to_md(rows):
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            return "\n".join(lines)

        def page_tables(page):
            try:
                # lines_strict trusts only real ruled lines, so the wrapped lines
                # inside one cell are not mistaken for extra rows. Fall back to
                # the default detector for tables without ruled lines.
                return (page.find_tables(strategy="lines_strict").tables
                        or page.find_tables().tables)
            except Exception as e:
                print(f"find_tables failed on a page: {type(e).__name__}: {e}")
                return []

        doc = pymupdf.open(stream=raw, filetype="pdf")
        running = _running_text_keys(doc)
        per_page_tables = [page_tables(page) for page in doc]

        page_items = []  # rendered only after ALL pages are read, because a table
        #                  started on one page can still grow on the next
        open_table = None  # table that may continue on the next page
        for pno, page in enumerate(doc):
            height = page.rect.height
            items = []  # (y_position, markdown text | table dict)
            bboxes = []
            tables = sorted(per_page_tables[pno], key=lambda t: t.bbox[1])

            for ti, t in enumerate(tables):
                rows = [[cell_text(page, bb) if bb else "" for bb in row.cells]
                        for row in t.rows]
                rows = [r for r in rows if any(r)]
                if not rows:
                    continue
                bboxes.append(pymupdf.Rect(t.bbox))
                header_key = tuple(c.lower() for c in rows[0])

                # Long tables repeat their header on every page and may cut a
                # row at the page break. Stitch them back into ONE table:
                #   1) drop the repeated header row
                #   2) a first row with an empty first cell is the rest of the
                #      row that was cut at the bottom of the previous page
                if (ti == 0 and open_table is not None
                        and open_table["page"] == pno - 1
                        and open_table["key"] == header_key
                        and t.bbox[1] < height * 0.25):
                    body = rows[1:]
                    if (body and not body[0][0] and open_table["rows"]
                            and len(body[0]) == len(open_table["rows"][-1])):
                        last = open_table["rows"][-1]
                        for ci, cell in enumerate(body[0]):
                            if cell:
                                last[ci] = (last[ci] + " " + cell).strip()
                        body = body[1:]
                    open_table["rows"].extend(body)
                    open_table["page"] = pno
                    continue

                table = {"rows": rows, "key": header_key, "page": pno}
                items.append((t.bbox[1], table))
                open_table = table

                # A table that reaches the bottom margin with nothing detected at
                # the top of the next page may have a row cut in half that we
                # cannot stitch back (no repeated header to anchor on).
                if (t.bbox[3] > height * 0.90 and pno + 1 < len(doc)
                        and not per_page_tables[pno + 1]):
                    print(f"WARNING: table on page {pno + 1} reaches the bottom of the page "
                          f"and may continue on page {pno + 2}; check its last row.")

            for x0, y0, x1, y1, text, _no, btype in page.get_text("blocks"):
                if btype != 0 or not text.strip():
                    continue
                key = (re.sub(r"\d+", "#", _norm_text(text).lower()), round(y0 / 6))
                if key in running and (y1 < height * 0.10 or y0 > height * 0.90):
                    continue  # repeated page header / footer
                center = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
                if any(center in bb for bb in bboxes):
                    continue  # already captured inside a table
                items.append((y0, _block_text(text)))

            items.sort(key=lambda it: it[0])
            page_items.append(items)

        pages = []
        for items in page_items:
            pages.append("\n\n".join(
                rows_to_md(v["rows"]) if isinstance(v, dict) else v
                for _, v in items if (v["rows"] if isinstance(v, dict) else v)
            ))
        print("PDF extraction: pymupdf (find_tables)")
        return "\n\n".join(pages)
    except Exception as e:
        print(f"PDF extraction: pypdf fallback ({type(e).__name__}: {e})")

    # Fallback: pypdf layout mode (weak on tables).
    reader = PdfReader(BytesIO(raw))
    if reader.is_encrypted:
        reader.decrypt("")
    return "\n\n".join(
        page.extract_text(extraction_mode="layout") or "" for page in reader.pages
    )


def _para_text(p):
    out = []
    for node in p.iter():
        if node.tag == _W + "t" and node.text:
            out.append(node.text)
        elif node.tag in (_W + "tab", _W + "br"):
            out.append(" ")
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def _heading_level(p):
    style = p.find(f"{_W}pPr/{_W}pStyle")
    if style is None:
        return 0
    val = style.get(_W + "val", "")
    if val == "Title":
        return 1
    m = re.match(r"Heading(\d)", val)
    return int(m.group(1)) if m else 0


def _table_to_markdown(tbl):
    rows = []
    for tr in tbl.findall(_W + "tr"):
        cells = []
        for tc in tr.findall(_W + "tc"):
            # direct-child paragraphs only; nested tables handled as plain text
            text = " ".join(t for t in (_para_text(p) for p in tc.iter(_W + "p")) if t)
            cells.append(text.replace("|", "/"))
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _docx_to_markdown(raw):
    with zipfile.ZipFile(BytesIO(raw)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(_W + "body")
    parts = []
    # Walk body children IN ORDER so tables stay where they belong
    for child in body:
        if child.tag == _W + "p":
            text = _para_text(child)
            if not text:
                continue
            level = _heading_level(child)
            parts.append(("#" * level + " " + text) if level else text)
        elif child.tag == _W + "tbl":
            md = _table_to_markdown(child)
            if md:
                parts.append(md)
    return "\n\n".join(parts)


# ------------------------------------------------------------------ chunking

def _parse_blocks(md):
    """Markdown -> [("heading", str) | ("para", str) | ("table", [rows])]."""
    blocks, para, table = [], [], []

    def flush_para():
        if para:
            # Keep list items on their own lines; join ordinary lines with spaces.
            sep = "\n" if any(_BULLET.match(p) for p in para) else " "
            blocks.append(("para", sep.join(para)))
            para.clear()

    def flush_table():
        if table:
            blocks.append(("table", list(table)))
            table.clear()

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and len(s) > 1:
            flush_para()
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # separator row
            table.append(cells)
            continue
        flush_table()
        if not s:
            flush_para()
        elif s.startswith("#"):
            flush_para()
            blocks.append(("heading", s.lstrip("#").strip()))
        else:
            para.append(s)
    flush_para()
    flush_table()
    return blocks


def _split_long(text, limit):
    """Split an oversized paragraph on sentence boundaries, then hard-split."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        while len(sent) > limit:  # no punctuation at all
            cut = sent.rfind(" ", 0, limit) or limit
            cut = cut if cut > 0 else limit
            out.append(sent[:cut])
            sent = sent[cut:].lstrip()
        if cur and len(cur) + len(sent) + 1 > limit:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


def _chunk_markdown(md, title):
    chunks, section = [], ""
    buf, buf_len = [], 0
    skip_section = False  # True while inside a table of contents

    def prefix():
        return title + (f" > {section}" if section else "")

    def emit(body, kind, **extra):
        # extra: optional chunk fields (e.g. table_start / table_rows)
        chunks.append({"text": f"{prefix()}\n{body}", "section": section,
                       "kind": kind, **extra})

    def flush(carry=False):
        nonlocal buf, buf_len
        if not buf:
            return
        emit("\n".join(buf), "text")
        last = buf[-1]
        buf = [last] if carry and len(last) <= OVERLAP_CHARS else []
        buf_len = sum(len(x) for x in buf)

    for kind, value in _parse_blocks(md):
        if kind == "heading":
            flush()
            section = value
            # A table of contents only lists headings; indexing it makes the
            # TOC compete with the real sections in search.
            skip_section = bool(re.fullmatch(r"(table of )?contents?", value.strip(), re.I))
        elif skip_section:
            continue
        elif kind == "para":
            for piece in _split_long(value, MAX_CHARS):
                if buf_len + len(piece) > MAX_CHARS:
                    flush(carry=True)
                buf.append(piece)
                buf_len += len(piece) + 1
        else:  # table
            flush()
            header, rows = value[0], value[1:]
            labels = [h for h in header if h]
            # drop empty cells (merged/spanned PDF cells) and empty rows
            data_rows = [v for v in ([c for c in r if c] for r in rows) if v]
            if not data_rows:
                emit(" | ".join(labels), "table",
                     table_start=len(chunks), table_rows=1)
                continue

            start = len(chunks)
            if (len(labels) == 2 and labels[0].lower() in _KEY_VALUE_HEADERS
                    and all(len(v) == 2 for v in data_rows)):
                # Key/value table (e.g. Document Control: Field | Information).
                # One row per chunk would give useless one-liners such as
                # "Version: 1.0", so rows are grouped by their own keys.
                groups, cur, cur_len = [], [], 0
                for key, val in data_rows:
                    line = f"{key}: {val}"
                    if cur and cur_len + len(line) > MAX_CHARS:
                        groups.append(cur)
                        cur, cur_len = [], 0
                    cur.append(line)
                    cur_len += len(line) + 1
                groups.append(cur)
                for group in groups:
                    emit("\n".join(group), "table",
                         table_start=start, table_rows=len(groups))
            else:
                # Lookup table: one self-describing chunk per row. Row chunks
                # are emitted back to back, so the table occupies chunk_index
                # table_start .. table_start + table_rows - 1.
                for vals in data_rows:
                    if len(vals) == len(labels):
                        body = "; ".join(f"{l}: {v}" for l, v in zip(labels, vals))
                    else:  # can't pair safely: keep the values, drop the labels
                        body = "; ".join(vals)
                    emit(body, "table", table_start=start, table_rows=len(data_rows))
    flush()

    for i, c in enumerate(chunks):
        c["chunk_index"] = i
    return chunks


# ------------------------------------------------------------ embed + store

def _embed_and_store(chunks, source_key):
    doc_id = hashlib.sha1(_clean_name(source_key).encode()).hexdigest()[:16]

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        embeddings = _get_embeddings([c["text"] for c in batch])

        vectors = [
            {
                # Deterministic key: re-uploading the same file overwrites
                # instead of piling up duplicates.
                "key": f"{doc_id}#{c['chunk_index']}",
                "data": {"float32": emb},
                "metadata": {
                    "source_text": c["text"],
                    "source_document": source_key,
                    "doc_id": doc_id,
                    "chunk_index": c["chunk_index"],
                    "section": c["section"][:200],
                    "kind": c["kind"],
                    # only table-row chunks carry these two
                    **{k: c[k] for k in ("table_start", "table_rows") if k in c},
                },
            }
            for c, emb in zip(batch, embeddings)
        ]
        s3vectors.put_vectors(
            vectorBucketName=VECTOR_BUCKET_NAME,
            indexName=VECTOR_INDEX_NAME,
            vectors=vectors,
        )
        print(f"Stored {len(vectors)} vectors (chunks {i}..{i + len(vectors) - 1}).")


def _get_embeddings(texts):
    body = json.dumps({
        "texts": texts,
        "input_type": "search_document",
        "truncate": "END",
    })
    response = bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=body,
        accept="*/*",
        contentType="application/json",
    )
    return json.loads(response["body"].read())["embeddings"]
