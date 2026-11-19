"""
Retrieval test for the NEU RAG index.

Question it answers: for each test question, does the RIGHT chunk come back
from S3 Vectors, and how high does it rank? No LLM answer is generated here,
so a failure points at ingestion/chunking/embedding, not at the prompt.

Usage (from the repo folder, with .env set up):
    python retrieval_test.py test_questions.csv --k 5 --label chunk1200

CSV columns (UTF-8, header row required):
    id, category, question, answerable, expected_doc, must_contain

    answerable    yes / no   ("no" = the documents do NOT contain the answer)
    expected_doc  part of the document's filename (case-insensitive), e.g. "handbook"
    must_contain  a short, distinctive phrase that must appear inside the
                  retrieved chunk, e.g. "8:00 AM" or "Registrar". Optional but
                  strongly recommended: it makes the test chunk-level, not just doc-level.

.env needs:
    AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    VECTOR_BUCKET_NAME, VECTOR_INDEX_NAME   (same values as the ingestion Lambda)
Optional: EMBED_MODEL_ID (default cohere.embed-multilingual-v3)
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys
from collections import defaultdict

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("AWS_REGION", "us-east-1")
EMBED_MODEL_ID = os.getenv("EMBED_MODEL_ID", "cohere.embed-multilingual-v3")
BATCH_SIZE = 96  # Cohere max texts per call

UUID_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-"
)


def clean_name(key):
    return UUID_PREFIX.sub("", os.path.basename(key or ""))


def norm(text):
    return " ".join((text or "").split()).lower()


def require_env(name):
    value = os.getenv(name)
    if not value:
        sys.exit(f"Missing {name} in your .env file.")
    return value


def embed_queries(bedrock, questions):
    """Embed as search_query (NOT search_document: that is for indexing)."""
    vectors = []
    for i in range(0, len(questions), BATCH_SIZE):
        body = json.dumps({
            "texts": questions[i:i + BATCH_SIZE],
            "input_type": "search_query",
            "truncate": "END",
        })
        response = bedrock.invoke_model(
            modelId=EMBED_MODEL_ID, body=body,
            accept="*/*", contentType="application/json",
        )
        vectors.extend(json.loads(response["body"].read())["embeddings"])
    return vectors


def search(s3vectors, bucket, index, vector, k):
    response = s3vectors.query_vectors(
        vectorBucketName=bucket,
        indexName=index,
        queryVector={"float32": vector},
        topK=k,
        returnMetadata=True,
        returnDistance=True,
    )
    return response.get("vectors", [])


def is_hit(row, metadata):
    doc = clean_name(metadata.get("source_document", "")).lower()
    expected_doc = row["expected_doc"].strip().lower()
    must = norm(row["must_contain"])
    if expected_doc and expected_doc not in doc:
        return False
    if must and must not in norm(metadata.get("source_text", "")):
        return False
    return True


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--k", type=int, default=5, help="how many results to retrieve")
    parser.add_argument("--label", default="run", help="name for this configuration, e.g. chunk1200")
    args = parser.parse_args()

    bucket = require_env("VECTOR_BUCKET_NAME")
    index = require_env("VECTOR_INDEX_NAME")
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    s3vectors = boto3.client("s3vectors", region_name=REGION)

    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    if not rows:
        sys.exit("The CSV has no rows.")

    for r in rows:
        r["answerable"] = r.get("answerable", "yes").lower() != "no"
        if r["answerable"] and not (r["expected_doc"] or r["must_contain"]):
            print(f"WARNING {r['id']}: answerable but no expected_doc or must_contain, skipping.")
            r["skip"] = True

    print(f"Embedding {len(rows)} questions with {EMBED_MODEL_ID} ...")
    vectors = embed_queries(bedrock, [r["question"] for r in rows])

    results = []
    for row, vec in zip(rows, vectors):
        if row.get("skip"):
            continue
        hits = search(s3vectors, bucket, index, vec, args.k)
        rank = None
        for position, hit in enumerate(hits, start=1):
            if is_hit(row, hit.get("metadata", {})):
                rank = position
                break
        top = hits[0] if hits else {}
        top_meta = top.get("metadata", {})
        results.append({
            "row": row,
            "rank": rank,
            "hits": hits,
            "top_distance": top.get("distance"),
            "top_doc": clean_name(top_meta.get("source_document", "")),
            "top_section": top_meta.get("section", ""),
        })

    answerable = [r for r in results if r["row"]["answerable"]]
    unanswerable = [r for r in results if not r["row"]["answerable"]]

    # ---- summary
    print(f"\n=== {args.label}: {len(answerable)} answerable, {len(unanswerable)} unanswerable questions (k={args.k}) ===")
    if answerable:
        for cutoff in (1, 3, 5):
            if cutoff <= args.k:
                found = sum(1 for r in answerable if r["rank"] and r["rank"] <= cutoff)
                print(f"hit@{cutoff}: {found}/{len(answerable)} = {found / len(answerable):.0%}")
        mrr = statistics.mean(1 / r["rank"] if r["rank"] else 0 for r in answerable)
        print(f"MRR: {mrr:.3f}  (1.0 means the right chunk is always first)")

        by_category = defaultdict(list)
        for r in answerable:
            by_category[r["row"]["category"] or "uncategorised"].append(r)
        print("\nBy category (hit within top-k):")
        for category, items in sorted(by_category.items()):
            found = sum(1 for r in items if r["rank"])
            print(f"  {category:<22} {found}/{len(items)}")

    # ---- misses
    misses = [r for r in answerable if not r["rank"]]
    if misses:
        print(f"\n=== Misses ({len(misses)}): read these, they tell you what to fix ===")
    for r in misses:
        row = r["row"]
        print(f"\n[{row['id']}] {row['question']}")
        print(f"  expected: doc~'{row['expected_doc']}'  must_contain='{row['must_contain']}'")
        for position, hit in enumerate(r["hits"][:3], start=1):
            meta = hit.get("metadata", {})
            snippet = " ".join(meta.get("source_text", "").split())[:110]
            print(f"  {position}. d={hit.get('distance', 0):.3f} {clean_name(meta.get('source_document', ''))}"
                  f" > {meta.get('section', '') or '(no section)'}\n     {snippet}")

    # ---- distance stats (for choosing MAX_VECTOR_DISTANCE)
    good = [r["top_distance"] for r in answerable if r["rank"] == 1 and r["top_distance"] is not None]
    bad = [r["top_distance"] for r in unanswerable if r["top_distance"] is not None]
    if good or bad:
        print("\n=== Top-1 distance (lower = more similar) ===")
        if good:
            print(f"answerable, correct at rank 1: median {statistics.median(good):.3f}, "
                  f"90th pct {percentile(good, 0.9):.3f}, max {max(good):.3f}")
        if bad:
            print(f"unanswerable questions:        min {min(bad):.3f}, "
                  f"median {statistics.median(bad):.3f}, max {max(bad):.3f}")
        if good and bad:
            print("A MAX_VECTOR_DISTANCE between the two ranges rejects off-topic questions "
                  "without rejecting real ones. If the ranges overlap, no single cutoff is clean.")

    # ---- save per-question results so runs can be compared later
    out_path = f"results_{args.label}.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "category", "question", "answerable", "rank_of_first_hit",
                         "top1_distance", "top1_doc", "top1_section"])
        for r in results:
            row = r["row"]
            writer.writerow([row["id"], row["category"], row["question"],
                             "yes" if row["answerable"] else "no", r["rank"] or "",
                             f"{r['top_distance']:.4f}" if r["top_distance"] is not None else "",
                             r["top_doc"], r["top_section"]])
    print(f"\nSaved per-question results to {out_path}")


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        code = error.response["Error"]["Code"]
        print(f"\nAWS error: {code}: {error.response['Error']['Message']}")
        if code in ("AccessDeniedException", "AccessDenied"):
            print("Your local credentials need bedrock:InvokeModel (Cohere embed) and "
                  "s3vectors:QueryVectors + s3vectors:GetVectors on the vector index.")
        sys.exit(1)
