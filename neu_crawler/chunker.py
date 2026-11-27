"""Heading-aware, paragraph-aware chunking. Tables and lists are kept whole where they fit."""
import re

import config

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def est_tokens(text):
    return max(1, round(len(text) / config.CHARS_PER_TOKEN))


def _pack(pieces, max_chars, sep):
    out, cur = [], ""
    for piece in pieces:
        while len(piece) > max_chars:                       # hard-cut pieces that can never fit
            cut = piece.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if cur:
                out.append(cur)
                cur = ""
            out.append(piece[:cut])
            piece = piece[cut:].lstrip()
        if not piece:
            continue
        if cur and len(cur) + len(sep) + len(piece) > max_chars:
            out.append(cur)
            cur = piece
        else:
            cur = f"{cur}{sep}{piece}" if cur else piece
    if cur:
        out.append(cur)
    return out


def _split_block(block, max_chars):
    if block.lstrip().startswith("|"):                      # table: repeat header on each part
        rows = block.split("\n")
        header, body = rows[:2], rows[2:]
        if not body:
            return [block]
        budget = max(max_chars - sum(len(r) + 1 for r in header), 200)
        return ["\n".join(header + [group]) for group in _pack(body, budget, "\n")]
    if "\n" in block:                                       # list
        return _pack(block.split("\n"), max_chars, "\n")
    return _pack(_SENTENCE.split(block), max_chars, " ")


def chunk_document(doc_id, title, category, source_url, body,
                   date_published=None, date_scraped=None):
    target_chars = int(config.CHUNK_TARGET_TOKENS * config.CHARS_PER_TOKEN)
    overlap_chars = int(config.CHUNK_OVERLAP_TOKENS * config.CHARS_PER_TOKEN)

    sections, path, pending = [], [], []

    def close():
        if pending:
            sections.append(([t for _, t in path], list(pending)))
            pending.clear()

    for block in re.split(r"\n{2,}", body.strip()):
        block = block.strip()
        if not block:
            continue
        m = _HEADING.match(block)
        if m and "\n" not in block:
            close()
            level = len(m.group(1))
            path[:] = [(lv, t) for lv, t in path if lv < level] + [(level, m.group(2).strip())]
        else:
            pending.append(block)
    close()

    chunks = []

    def make(header, heading_path, parts):
        chunks.append({
            "chunk_id": f"{doc_id}-{len(chunks):03d}",
            "document_id": doc_id,
            "title": title,
            "category": category,
            "content": header + "\n\n" + "\n\n".join(parts),
            "source_url": source_url,
            "heading_path": heading_path,
            "date_published": date_published,
            "date_scraped": date_scraped,
        })

    for heading_path, blocks in sections:
        header = " > ".join([title] + heading_path)
        limit = max(target_chars - len(header) - 2, 200)
        units = []
        for b in blocks:
            units.extend(_split_block(b, limit) if len(b) > limit else [b])

        cur, cur_len, fresh = [], 0, False
        for unit in units:
            if cur and cur_len + len(unit) + 2 > limit:
                if fresh:
                    make(header, heading_path, cur)
                carry, carry_len = [], 0                    # overlap: re-use trailing small units
                for prev in reversed(cur):
                    if carry_len + len(prev) + 2 > overlap_chars:
                        break
                    carry.insert(0, prev)
                    carry_len += len(prev) + 2
                cur, cur_len, fresh = carry, carry_len, False
                if cur_len + len(unit) + 2 > limit:
                    cur, cur_len = [], 0
            cur.append(unit)
            cur_len += len(unit) + 2
            fresh = True
        if cur and fresh:
            make(header, heading_path, cur)
    return chunks