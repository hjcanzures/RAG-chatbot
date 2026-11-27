"""
Cache threshold test for the NEU RAG query Lambda.

Question it answers: how far apart (cosine distance) are two student questions
that SHOULD share a cached answer, versus two that must NOT? And does the
retrieved-chunk fingerprint separate the near-misses that distance alone cannot?

It uses your deployed Lambda's own embedding + retrieval functions, so results
reflect its real FETCH_K / MAX_DISTANCE / RELATIVE_MARGIN / MAX_PER_TABLE.
No LLM or guardrail calls are made, and nothing is written to AWS.

Usage (repo root, .env set up with AWS creds + VECTOR_BUCKET_NAME/INDEX_NAME):
    python evaluation/cache_threshold_test.py evaluation/cache_pairs.csv \
        lambdas/query/lambda_function.py --threshold 0.15 --fp-top-n 2 --label v2

CSV columns: id, should_hit (yes/no), question_a, question_b, note
Needs: pip install boto3 python-dotenv

Exit code is 1 if the chosen settings wrongly serve any must-NOT pair, so the
script doubles as a regression check after you change chunking or documents.
"""
import argparse
import csv
import hashlib
import importlib.util
import math
import os
import sys

from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

# The Lambda module reads env vars and builds boto3 clients at import time.
os.environ.setdefault("AWS_DEFAULT_REGION", os.getenv("AWS_REGION", "us-east-1"))
os.environ.setdefault("GUARDRAIL_ID", "unused-in-this-test")
os.environ.setdefault("GUARDRAIL_VERSION", "1")
for _name in ("VECTOR_BUCKET_NAME", "VECTOR_INDEX_NAME"):
    if not os.getenv(_name):
        sys.exit(f"Missing {_name} in your .env file.")

FP_SIZES = (1, 2, 3, 5)
THRESHOLDS = [round(0.02 * i, 2) for i in range(1, 16)]  # 0.02 .. 0.30
SAFE_MARGIN = 0.03  # warn if the threshold sits closer than this to a same-chunk must-NOT pair


def load_module(path):
    spec = importlib.util.spec_from_file_location("query_lambda_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cosine_distance(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 1 - dot / (na * nb) if na and nb else 1.0


def fingerprint(matches, n):
    """Same recipe as the planned cache: top-n chunk keys + hash of chunk text."""
    if not matches:
        return None
    parts = []
    for m in matches[:n]:
        text = (m.get("metadata") or {}).get("source_text", "")
        parts.append(f"{m['key']}:{hashlib.sha256(text.encode()).hexdigest()[:12]}")
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()


def analyse(module, question):
    """Embed once, retrieve exactly as the Lambda does for a no-history question."""
    vec = module._embed_query(question)
    results = module.s3vectors.query_vectors(
        vectorBucketName=module.VECTOR_BUCKET_NAME,
        indexName=module.VECTOR_INDEX_NAME,
        topK=module.FETCH_K,
        queryVector={"float32": vec},
        returnMetadata=True,
        returnDistance=True,
    )["vectors"]
    matches = module._select_matches(module._merge_results([results]))
    return {"vec": vec, "matches": matches}


def pct(n, total):
    return f"{n}/{total}" + (f" = {n / total:.0%}" if total else "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("lambda_path", help="path to the deployed query lambda_function.py")
    parser.add_argument("--fp-top-n", type=int, default=2, help="chunks in the fingerprint (default 2)")
    parser.add_argument("--threshold", type=float, default=0.15,
                        help="max cosine distance to serve from cache (default 0.15)")
    parser.add_argument("--label", default="run")
    args = parser.parse_args()

    n = args.fp_top_n
    thr = args.threshold
    if n not in FP_SIZES:
        sys.exit(f"--fp-top-n must be one of {FP_SIZES}")

    module = load_module(args.lambda_path)

    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    if not rows:
        sys.exit("The CSV has no rows.")

    questions = sorted({q for r in rows for q in (r["question_a"], r["question_b"])})
    print(f"Embedding + retrieving for {len(questions)} unique questions ...")
    cache = {}
    for i, q in enumerate(questions, 1):
        cache[q] = analyse(module, q)
        print(f"  {i}/{len(questions)}", end="\r", flush=True)
    print()

    pairs = []
    for r in rows:
        a, b = cache[r["question_a"]], cache[r["question_b"]]
        fp_match = {}
        for size in FP_SIZES:
            fa, fb = fingerprint(a["matches"], size), fingerprint(b["matches"], size)
            fp_match[size] = fa is not None and fa == fb
        pairs.append({
            "id": r["id"], "should": r["should_hit"].lower() == "yes",
            "a": r["question_a"], "b": r["question_b"], "note": r.get("note", ""),
            "dist": cosine_distance(a["vec"], b["vec"]),
            "fp": fp_match,
            "uncacheable": not a["matches"] or not b["matches"],
        })

    yes = [p for p in pairs if p["should"]]
    no = [p for p in pairs if not p["should"]]

    def served(p):
        """Would the cache serve question B's answer for question A?"""
        return p["dist"] <= thr and p["fp"][n]

    # ---- every pair, nearest first: read the boundary by eye
    print(f"\n=== Pairs by distance (fingerprint = top-{n} chunks) ===")
    print(f"{'id':<5}{'want':<6}{'dist':<8}{'top-1 same':<12}{f'top-{n} same':<12}question A  ||  question B")
    for p in sorted(pairs, key=lambda p: p["dist"]):
        print(f"{p['id']:<5}{'HIT' if p['should'] else 'MISS':<6}{p['dist']:<8.3f}"
              f"{'yes' if p['fp'][1] else 'no':<12}{'yes' if p['fp'][n] else 'no':<12}"
              f"{p['a'][:40]}  ||  {p['b'][:40]}"
              + ("   [no retrieval match]" if p["uncacheable"] else ""))

    # ---- distance ranges
    print("\n=== Distance ranges ===")
    yd = sorted(p["dist"] for p in yes)
    nd = sorted(p["dist"] for p in no)
    print(f"should-hit  pairs: min {yd[0]:.3f}  median {yd[len(yd) // 2]:.3f}  max {yd[-1]:.3f}")
    print(f"must-NOT    pairs: min {nd[0]:.3f}  median {nd[len(nd) // 2]:.3f}  max {nd[-1]:.3f}")
    closest = min(no, key=lambda p: p["dist"])
    print(f"closest must-NOT pair: {closest['id']} at {closest['dist']:.3f} "
          f"({closest['a'][:40]} || {closest['b'][:40]})")

    # ---- fingerprint effect
    print("\n=== Fingerprint (same retrieved chunks) by size ===")
    print(f"{'top-N':<7}{'should-hit pairs matching':<30}must-NOT pairs matching (want 0)")
    for size in FP_SIZES:
        ym = sum(p["fp"][size] for p in yes)
        nm = sum(p["fp"][size] for p in no)
        print(f"{size:<7}{pct(ym, len(yes)):<30}{pct(nm, len(no))}")

    # ---- threshold sweep
    print(f"\n=== Threshold sweep (fingerprint top-{n}) ===")
    print(f"{'thresh':<8}{'hits: dist only':<18}{'hits: dist+chunks':<20}"
          f"{'FALSE: dist only':<19}FALSE: dist+chunks")
    safe_dist = safe_both = None
    for t in THRESHOLDS:
        hd = sum(p["dist"] <= t for p in yes)
        hb = sum(p["dist"] <= t and p["fp"][n] for p in yes)
        fd = sum(p["dist"] <= t for p in no)
        fb = sum(p["dist"] <= t and p["fp"][n] for p in no)
        if fd == 0:
            safe_dist = t
        if fb == 0:
            safe_both = t
        print(f"{t:<8.2f}{pct(hd, len(yes)):<18}{pct(hb, len(yes)):<20}{fd:<19}{fb}")
    print(f"\nLargest swept threshold with zero false hits, distance only:   {safe_dist}")
    print(f"Largest swept threshold with zero false hits, distance+chunks: {safe_both}")

    # ---- the dangerous category: same top chunk, different question
    dangerous = sorted((p for p in no if p["fp"][1]), key=lambda p: p["dist"])
    print(f"\n=== Same-top-chunk must-NOT pairs: {len(dangerous)} "
          f"(the chunk check cannot tell these apart by itself) ===")
    if not dangerous:
        print("None found. Add pairs where the same entity gets a different question.")
    for p in dangerous:
        if p["dist"] > thr:
            verdict = "blocked by distance"
        elif not p["fp"][n]:
            verdict = f"blocked only because top-{n} chunks differ (weak protection)"
        else:
            verdict = "WRONGLY SERVED"
        print(f"  {p['id']:<5}{p['dist']:.3f}  {verdict}: {p['a'][:38]} || {p['b'][:38]}")
    if dangerous:
        nearest_danger = dangerous[0]["dist"]
        margin = nearest_danger - thr
        print(f"\nNearest same-chunk must-NOT pair is at {nearest_danger:.3f}; "
              f"threshold {thr:.2f} leaves a margin of {margin:+.3f}.")
        if margin < SAFE_MARGIN:
            print(f"WARNING: margin is under {SAFE_MARGIN}. Lower --threshold or add more same-chunk pairs.")

    # ---- verdict for the chosen settings
    hits = [p for p in yes if served(p)]
    wrong = [p for p in no if served(p)]
    print(f"\n=== Chosen settings: distance <= {thr}, same top-{n} chunks ===")
    print(f"should-hit pairs served from cache: {pct(len(hits), len(yes))}")
    print(f"must-NOT pairs wrongly served:      {len(wrong)}  (want 0)")
    for p in wrong:
        print(f"  FALSE HIT {p['id']} dist {p['dist']:.3f}: {p['a']} || {p['b']}")
    print("A false hit is a wrong answer shown to a student; a missed hit only costs one model call. "
          "Keep margin below the first false hit and grow the pair list before trusting a higher threshold.")

    out_path = f"results_cache_{args.label}.csv"
    for attempt in range(2):
        try:
            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["id", "should_hit", "distance"] + [f"same_chunks_top{s}" for s in FP_SIZES]
                           + [f"served_at_{thr}", "question_a", "question_b", "note"])
                for p in sorted(pairs, key=lambda p: p["dist"]):
                    w.writerow([p["id"], "yes" if p["should"] else "no", f"{p['dist']:.4f}"]
                               + ["yes" if p["fp"][s] else "no" for s in FP_SIZES]
                               + ["yes" if served(p) else "no", p["a"], p["b"], p["note"]])
            print(f"\nSaved per-pair results to {out_path}")
            break
        except PermissionError:
            # Usually the file is open in Excel. Don't lose the run: write a copy instead.
            out_path = f"results_cache_{args.label}_{int(__import__('time').time())}.csv"
            print(f"\nCould not overwrite the results file (is it open in Excel?). Trying {out_path} ...")

    if wrong:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        code = error.response["Error"]["Code"]
        print(f"\nAWS error: {code}: {error.response['Error']['Message']}")
        sys.exit(1)
