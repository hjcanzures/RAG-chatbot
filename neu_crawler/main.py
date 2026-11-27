"""Entry point:  python main.py [--limit N] [--dry-run] [--start-url URL]"""
import argparse
import json
import logging
import shutil
from collections import Counter
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

import config
from categorizer import categorize
from chunker import chunk_document
from crawler import Crawler, Fetcher
from document_generator import (content_hash, document_id, ingest_filename, ingest_text,
                                relative_path, render_document, with_related)
from extractor import SkipPage, extract_html, extract_pdf
from storage import Storage

log = logging.getLogger("neu.main")


def setup_logging(out_dir, dry_run):
    handlers = [logging.StreamHandler()]
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(out_dir / "crawl.log", encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)


def get_body(storage, run_bodies, url, entry):
    if url in run_bodies:
        return run_bodies[url]
    if storage.exists(entry.get("path")):
        return storage.read_body(entry["path"])
    return None


def export_ingest(storage, manifest, run_bodies):
    """Front-matter-free copies, named after the page title, for the admin-panel upload."""
    folder = storage.root / config.INGEST_DIR_NAME
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    used = Counter()
    for url, entry in sorted(manifest.items()):
        if entry.get("extraction_status") != "ok":
            continue
        body = get_body(storage, run_bodies, url, entry)
        if body is None:
            continue
        name = ingest_filename(entry["title"])
        used[name] += 1
        if used[name] > 1:
            name = ingest_filename(f"{entry['title']} {used[name]}")
        (folder / name).write_text(ingest_text(entry, body), encoding="utf-8", newline="\n")


def build_report(stats, manifest, errors, unseen, chunk_count, limit):
    cats = Counter(e["category"] for e in manifest.values() if e.get("extraction_status") == "ok")
    lines = [
        "# NEU crawl report", "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}  ",
        f"Crawl limit: {limit} fetches", "",
        "## Summary", "",
        "| Metric | Count |", "| --- | --- |",
        f"| URLs discovered | {stats['discovered']} |",
        f"| Pages fetched successfully | {stats['crawled']} |",
        f"| New documents | {stats['new']} |",
        f"| Updated documents | {stats['updated']} |",
        f"| Unchanged documents | {stats['unchanged']} |",
        f"| Duplicate pages skipped | {stats['duplicates']} (+{stats['redirect_dupes']} redirect duplicates) |",
        f"| PDFs processed | {stats['pdfs']} |",
        f"| Skipped (login page, no text, too large, other type) | {stats['skipped']} |",
        f"| Blocked by robots.txt | {stats['blocked']} |",
        f"| Failed / inaccessible | {stats['failed']} |",
        f"| Chunks generated | {chunk_count} |", "",
        "## Documents per category", "",
        "| Category | Documents |", "| --- | --- |",
    ]
    lines += [f"| {c} | {n} |" for c, n in sorted(cats.items())]
    lines += ["", "## Errors and skipped URLs", ""]
    lines += [f"- `{u}` — {s}: {e}" for u, s, e in errors[:100]] or ["- None"]
    if len(errors) > 100:
        lines.append(f"- ... and {len(errors) - 100} more (see crawl.log)")
    lines += ["", "## Previously collected pages not reached in this run", "",
              "These may have been removed from the site, or simply not reached because of the crawl limit. "
              "Nothing was deleted; review them manually.", ""]
    lines += [f"- {u}" for u in unseen[:100]] or ["- None"]
    lines += ["", "## Limitations", "",
              "- Only pages reachable through internal links are found; JavaScript-rendered content is not executed.",
              "- Scanned (image-only) PDFs have no extractable text and are skipped.",
              "- Categories are keyword heuristics; review the `uncategorized` folder and tune `config.CATEGORIES`.",
              "- Publication dates are only recorded when the page exposes them in metadata; otherwise they are null.",
              "- Off-domain PDFs and links are not followed."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="NEU website crawler -> RAG knowledge base")
    parser.add_argument("--limit", type=int, default=config.MAX_PAGES, help="maximum number of URLs to fetch")
    parser.add_argument("--dry-run", action="store_true", help="crawl and report, but write no files")
    parser.add_argument("--start-url", action="append", help="override start URL(s); repeatable")
    args = parser.parse_args()

    out = config.OUTPUT_DIR
    setup_logging(out, args.dry_run)
    storage = Storage(out, args.dry_run)
    previous = storage.load_manifest()
    manifest = dict(previous)

    stats, errors = Counter(), []
    seen_hashes, run_bodies, attempted = {}, {}, set()
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    crawler = Crawler(Fetcher(), args.start_url or config.START_URLS)

    def record_problem(key, status, error):
        stats[status] += 1
        errors.append((key, status, error))
        attempted.add(key)
        prev = previous.get(key)
        if prev and prev.get("extraction_status") == "ok":
            manifest[key] = {**prev, "last_error": error, "last_attempt": now}   # keep the old good document
        else:
            manifest[key] = {"url": key, "extraction_status": status, "error": error, "crawled_at": now}

    for page in crawler.crawl(args.limit):
        if page.status != "ok":
            record_problem(page.requested, page.status, page.error)
            continue
        stats["crawled"] += 1
        attempted.add(page.url)
        try:
            doc = extract_pdf(page.content, page.url) if page.kind == "pdf" else extract_html(page.content, page.url)
        except SkipPage as exc:
            record_problem(page.url, "skipped", str(exc))
            continue
        except Exception as exc:
            log.exception("Extraction failed for %s", page.url)
            record_problem(page.url, "failed", f"Extraction error: {type(exc).__name__}: {exc}")
            continue
        if len(doc["body"]) < config.MIN_CONTENT_CHARS:
            record_problem(page.url, "skipped", "Too little text after cleaning")
            continue
        if page.kind == "pdf":
            stats["pdfs"] += 1

        digest = content_hash(doc["body"])
        canonical = doc.get("canonical")
        duplicate_of = seen_hashes.get(digest) or (
            canonical if canonical and canonical != page.url and canonical in run_bodies else None)
        if duplicate_of:
            stats["duplicates"] += 1
            manifest[page.url] = {"url": page.url, "extraction_status": "duplicate",
                                  "duplicate_of": duplicate_of, "crawled_at": now}
            continue
        seen_hashes[digest] = page.url

        category, tags = categorize(page.url, doc["title"], doc["body"])
        rel = relative_path(category, doc["title"], page.url)
        full_body = with_related(doc["body"], doc["related"])
        old = previous.get(page.url)
        was_ok = bool(old and old.get("extraction_status") == "ok")
        unchanged = (was_ok and old.get("content_hash") == digest and old.get("path") == rel
                     and storage.exists(rel))
        date_scraped = old.get("date_scraped", today) if unchanged else today
        meta = {
            "title": doc["title"], "category": category, "tags": tags, "source_url": page.url,
            "source_domain": urlsplit(page.url).hostname, "document_type": doc["document_type"],
            "date_published": doc["date_published"], "date_modified": doc["date_modified"],
            "date_scraped": date_scraped, "content_hash": digest,
        }
        if unchanged:
            stats["unchanged"] += 1
        else:
            if was_ok and old.get("path") and old["path"] != rel:
                storage.remove(old["path"])                  # category/title changed: move the file
            stats["updated" if was_ok else "new"] += 1
            storage.write(rel, render_document(meta, full_body))

        run_bodies[page.url] = full_body
        manifest[page.url] = {
            "url": page.url, "title": doc["title"], "path": rel, "category": category, "tags": tags,
            "document_type": doc["document_type"], "extraction_status": "ok", "content_hash": digest,
            "date_published": doc["date_published"], "date_modified": doc["date_modified"],
            "date_scraped": date_scraped, "crawled_at": now, "canonical": canonical,
        }

    stats["discovered"] = len(crawler.seen)
    stats["redirect_dupes"] = crawler.redirect_duplicates
    unseen = sorted(u for u, e in previous.items()
                    if e.get("extraction_status") == "ok" and u not in attempted)

    # Chunks for every good document (this run's pages + earlier ones read back from disk).
    chunks = []
    for url, entry in sorted(manifest.items()):
        if entry.get("extraction_status") != "ok":
            continue
        body = get_body(storage, run_bodies, url, entry)
        if body is None:
            log.warning("Missing file for %s (%s); skipped when chunking", url, entry.get("path"))
            continue
        chunks.extend(chunk_document(document_id(url), entry["title"], entry["category"], url, body,
                                     entry.get("date_published"), entry.get("date_scraped")))

    report = build_report(stats, manifest, errors, unseen, len(chunks), args.limit)
    if args.dry_run:
        log.info("DRY RUN: nothing was written.\n%s", report)
    else:
        storage.write("chunks.jsonl", "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks))
        storage.save_manifest(manifest)
        export_ingest(storage, manifest, run_bodies)
        storage.write("crawl_report.md", report)
        log.info("Done. Output in %s (report: crawl_report.md)", out)
        log.info("Summary: %s", dict(stats))


if __name__ == "__main__":
    main()