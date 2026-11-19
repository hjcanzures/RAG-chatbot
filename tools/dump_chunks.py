"""
Local chunk inspector for the NEU RAG ingestion Lambda.

Runs your REAL extraction + chunking code on files from your computer (no AWS
calls, nothing is embedded or stored) and writes out exactly what would be
indexed, so you can read the chunks and fix garbling in seconds instead of
re-uploading through the admin panel and digging through CloudWatch.

Usage (from the repo folder):
    python dump_chunks.py path/to/ingestion_lambda.py file1.pdf file2.docx ...
    python dump_chunks.py path/to/ingestion_lambda.py docs/*.pdf --outdir chunk_dumps

For every input file it writes, into --outdir (default: chunk_dumps):
    <name>.extracted.md   what the extractor produced (check tables here first)
    <name>.chunks.txt     every chunk, with kind/section/size and any warning flags
and prints a summary of the chunks that look suspicious.

Needs the same libraries as the Lambda: pip install pymupdf pypdf boto3
"""
import argparse
import glob
import importlib.util
import os
import re
import sys

# The Lambda module reads env vars and creates boto3 clients at import time.
# Dummy values are enough because nothing here talks to AWS.
os.environ.setdefault("VECTOR_BUCKET_NAME", "local-test")
os.environ.setdefault("VECTOR_INDEX_NAME", "local-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


def load_module(path):
    spec = importlib.util.spec_from_file_location("ingestion_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def body_of(chunk):
    """Chunk text without the 'Title > Section' first line."""
    text = chunk["text"]
    return text.split("\n", 1)[1] if "\n" in text else text


def flags_for(chunk):
    body = body_of(chunk)
    flags = []

    words = re.findall(r"[A-Za-z]+", body)
    if len(words) >= 8:
        singles = [w for w in words if len(w) == 1 and w.lower() not in ("a", "i")]
        if len(singles) / len(words) > 0.12:
            flags.append("fragmented words (many 1-letter tokens)")

    if re.search(r"\b[a-z]{4,} [b-hj-z]\b", body):
        flags.append("possible split word (e.g. 'classroom s')")

    if "\ufffd" in body:
        flags.append("replacement characters (encoding problem)")

    for token in body.split():
        if len(token) > 28 and not any(ch in token for ch in "@/.:_-"):
            flags.append("glued words (very long token)")
            break

    letters = sum(ch.isalpha() for ch in body)
    if len(body) > 30 and letters / len(body) < 0.45:
        flags.append("mostly symbols/digits")

    if chunk["kind"] == "table" and ": " not in body:
        flags.append("table row without column labels")

    if len(body.strip()) < 40:
        flags.append("very short chunk")

    return flags


def process(module, path, outdir):
    key = os.path.basename(path)
    with open(path, "rb") as f:
        raw = f.read()

    markdown = module._extract_markdown(key, raw)
    # Use the Lambda's own title logic so the dump matches what gets indexed.
    if hasattr(module, "_doc_title"):
        title = module._doc_title(key)
    else:
        title = os.path.splitext(module._clean_name(key))[0]
    chunks = module._chunk_markdown(markdown, title)

    stem = os.path.splitext(key)[0]
    with open(os.path.join(outdir, f"{stem}.extracted.md"), "w", encoding="utf-8") as f:
        f.write(markdown)

    flagged = []
    with open(os.path.join(outdir, f"{stem}.chunks.txt"), "w", encoding="utf-8") as f:
        for chunk in chunks:
            flags = flags_for(chunk)
            if flags:
                flagged.append((chunk, flags))
            header = (f"===== CHUNK {chunk['chunk_index']} | {chunk['kind']} | "
                      f"section: {chunk['section'] or '-'} | {len(chunk['text'])} chars")
            if flags:
                header += " | FLAGS: " + "; ".join(flags)
            f.write(header + " =====\n" + chunk["text"] + "\n\n")

    kinds = {}
    for chunk in chunks:
        kinds[chunk["kind"]] = kinds.get(chunk["kind"], 0) + 1
    print(f"\n### {key}: {len(markdown)} chars extracted -> {len(chunks)} chunks "
          f"({', '.join(f'{n} {k}' for k, n in kinds.items())}), {len(flagged)} flagged")
    for chunk, flags in flagged:
        preview = " ".join(body_of(chunk).split())[:140]
        print(f"  chunk {chunk['chunk_index']:>3} [{'; '.join(flags)}]\n      {preview}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("module", help="path to your ingestion Lambda .py file")
    parser.add_argument("files", nargs="+", help="PDF / DOCX / TXT files to inspect")
    parser.add_argument("--outdir", default="chunk_dumps")
    args = parser.parse_args()

    # PowerShell and Command Prompt pass "*.pdf" through unexpanded (Git Bash
    # expands it first), so expand wildcards here to work in any terminal.
    paths = []
    for pattern in args.files:
        matches = sorted(glob.glob(pattern))
        paths.extend(matches if matches else [pattern])

    os.makedirs(args.outdir, exist_ok=True)
    module = load_module(args.module)
    for path in paths:
        try:
            process(module, path, args.outdir)
        except Exception as error:  # keep going so one bad file doesn't hide the rest
            print(f"\n### {os.path.basename(path)}: FAILED ({type(error).__name__}: {error})")
    print(f"\nDumps written to ./{args.outdir}/  (open the .chunks.txt files and read them)")


if __name__ == "__main__":
    sys.exit(main())
