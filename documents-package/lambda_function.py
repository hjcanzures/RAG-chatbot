import json
import os

import boto3

s3 = boto3.client("s3")
s3vectors = boto3.client("s3vectors")

RAW_BUCKET_NAME = os.environ["RAW_BUCKET_NAME"]
VECTOR_BUCKET_NAME = os.environ["VECTOR_BUCKET_NAME"]
VECTOR_INDEX_NAME = os.environ["VECTOR_INDEX_NAME"]

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def lambda_handler(event, context):
    # HTTP APIs (payload format 2.0) put the method here; REST APIs would
    # use event["httpMethod"] instead -- covering both just in case.
    method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")

    if method == "GET":
        return _list_documents()
    if method == "DELETE":
        return _delete_document(event)
    return _response(405, {"error": f"Unsupported method: {method}"})


def _list_documents():
    raw_objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=RAW_BUCKET_NAME):
        raw_objects.extend(page.get("Contents", []))

    chunk_counts = _count_chunks_per_document()

    documents = []
    for obj in raw_objects:
        key = obj["Key"]
        documents.append({
            "key": key,
            "filename": _display_name(key),
            "size": obj["Size"],
            "lastModified": obj["LastModified"].isoformat(),
            "chunkCount": chunk_counts.get(key, 0),
        })

    # Most recently uploaded first.
    documents.sort(key=lambda d: d["lastModified"], reverse=True)

    return _response(200, {"documents": documents})


def _delete_document(event):
    params = event.get("queryStringParameters") or {}
    key = params.get("key")
    if not key:
        return _response(400, {"error": "Missing required 'key' query parameter"})

    vector_keys = _find_vector_keys_for_document(key)

    BATCH = 500  # S3 Vectors caps how many keys can be deleted per call.
    for i in range(0, len(vector_keys), BATCH):
        batch = vector_keys[i:i + BATCH]
        s3vectors.delete_vectors(
            vectorBucketName=VECTOR_BUCKET_NAME,
            indexName=VECTOR_INDEX_NAME,
            keys=batch,
        )

    s3.delete_object(Bucket=RAW_BUCKET_NAME, Key=key)

    return _response(200, {
        "message": "Deleted",
        "key": key,
        "vectorsDeleted": len(vector_keys),
    })


def _count_chunks_per_document():
    counts = {}
    for v in _iterate_all_vectors():
        source = (v.get("metadata") or {}).get("source_document")
        if source:
            counts[source] = counts.get(source, 0) + 1
    return counts


def _find_vector_keys_for_document(source_document_key):
    return [
        v["key"] for v in _iterate_all_vectors()
        if (v.get("metadata") or {}).get("source_document") == source_document_key
    ]


def _iterate_all_vectors():
    # S3 Vectors' ListVectors has no metadata filter -- we page through
    # everything and filter client-side. Fine at capstone scale (low
    # hundreds of chunks); would need a different approach at real scale.
    next_token = None
    while True:
        kwargs = {
            "vectorBucketName": VECTOR_BUCKET_NAME,
            "indexName": VECTOR_INDEX_NAME,
            "returnMetadata": True,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        page = s3vectors.list_vectors(**kwargs)
        for v in page.get("vectors", []):
            yield v
        next_token = page.get("nextToken")
        if not next_token:
            break


def _display_name(key):
    # Ingestion Lambda writes keys as "<uuid>-<original filename>"
    # (36-char UUID + hyphen = 37 chars before the real name starts).
    if len(key) > 37 and key[36] == "-":
        return key[37:]
    return key


def _response(status_code, body_dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body_dict, default=str),
    }
