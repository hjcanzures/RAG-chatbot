"""Builds the Markdown documents (with front matter) and the front-matter-free ingest copies."""
import hashlib
import json
import re


def slugify(text, sep="-", max_len=70):
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", sep, text).strip(sep)
    return text[:max_len].strip(sep) or "untitled"


def _sha1(text, n):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def document_id(url):
    return _sha1(url, 16)


def content_hash(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def relative_path(category, title, url):
    return f"{category}/{slugify(title)}-{_sha1(url, 6)}.md"


def with_related(body, related):
    if not related:
        return body
    links = "\n".join(f"- [{text}]({url})" for text, url in related)
    return f"{body}\n\n## Related Information\n\n{links}"


def _yaml(value):
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


def render_document(meta, full_body):
    front = [
        "---",
        f"title: {_yaml(meta['title'])}",
        f"category: {_yaml(meta['category'])}",
        f"tags: {json.dumps(meta['tags'], ensure_ascii=False)}",
        f"source_url: {_yaml(meta['source_url'])}",
        f"source_domain: {_yaml(meta['source_domain'])}",
        f"document_type: {_yaml(meta['document_type'])}",
        f"date_published: {_yaml(meta['date_published'])}",
        f"date_modified: {_yaml(meta['date_modified'])}",
        f"date_scraped: {_yaml(meta['date_scraped'])}",
        f"content_hash: {_yaml(meta['content_hash'])}",
        "---",
    ]
    return "\n".join(front) + f"\n\n# {meta['title']}\n\n{full_body}\n"


def ingest_filename(title):
    """Your ingestion Lambda uses the filename as the document title (underscores become spaces)."""
    name = re.sub(r"[^\w\s-]", "", title).strip()
    name = re.sub(r"\s+", "_", name)[:80].strip("_") or "Untitled"
    return name + ".md"


def ingest_text(entry, full_body):
    lines = [f"# {entry['title']}", "", f"Source: {entry['url']}"]
    if entry.get("date_published"):
        lines.append(f"Published: {entry['date_published']}")
    return "\n".join(lines) + f"\n\n{full_body}\n"