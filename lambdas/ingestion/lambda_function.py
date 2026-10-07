import json
import os
import re
import traceback
import uuid
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from urllib.parse import unquote_plus

import boto3
from pypdf import PdfReader  # top-level: a missing package fails loudly at cold start

_DOCX_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
s3vectors = boto3.client("s3vectors")

VECTOR_BUCKET_NAME = os.environ["VECTOR_BUCKET_NAME"]
VECTOR_INDEX_NAME = os.environ["VECTOR_INDEX_NAME"]
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "cohere.embed-multilingual-v3")

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
BATCH_SIZE = 96


def lambda_handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        # FIX 2: proper URL-decoding (handles spaces, +, parentheses, unicode)
        key = unquote_plus(record["s3"]["object"]["key"])
        print(f"Processing s3://{bucket}/{key}")

        # FIX 4: one bad file no longer stops the other records
        try:
            raw_bytes = _download_object(bucket, key)
            text = _extract_text(key, raw_bytes)

            if not text.strip():
                print(f"NO TEXT EXTRACTED from {key} (scanned/image-only PDF?), skipping.")
                continue

            chunks = _chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
            print(f"Split '{key}' into {len(chunks)} chunks.")
            _embed_and_store(chunks, source_key=key)
        except Exception:
            print(f"FAILED processing {key}")
            traceback.print_exc()
            continue

    return {"statusCode": 200, "body": json.dumps({"message": "Processing complete"})}


def _download_object(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


# FIX 3: detect format from the file's bytes first, extension second
def _detect_format(key, raw_bytes):
    if raw_bytes.startswith(b"%PDF-"):
        return "pdf"
    if raw_bytes.startswith(b"PK"):
        try:
            with zipfile.ZipFile(BytesIO(raw_bytes)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
    ext = os.path.splitext(key)[1].lower().lstrip(".")
    if ext in ("txt", "md", "csv") or (not ext and b"\x00" not in raw_bytes[:1024]):
        return "txt"
    return ext or "unknown"


def _extract_text(key, raw_bytes):
    fmt = _detect_format(key, raw_bytes)

    if fmt == "txt":
        return raw_bytes.decode("utf-8", errors="ignore")
    if fmt == "pdf":
        reader = PdfReader(BytesIO(raw_bytes))
        if reader.is_encrypted:
            reader.decrypt("")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if fmt == "docx":
        return _extract_docx_text(raw_bytes)

    raise ValueError(f"Unsupported file type: {fmt}")


def _extract_docx_text(raw_bytes):
    with zipfile.ZipFile(BytesIO(raw_bytes)) as docx_zip:
        xml_content = docx_zip.read("word/document.xml")

    tree = ET.fromstring(xml_content)
    paragraphs = []
    for para in tree.iter(_DOCX_WORD_NS + "p"):
        run_texts = [node.text for node in para.iter(_DOCX_WORD_NS + "t") if node.text]
        paragraphs.append("".join(run_texts))

    return "\n".join(paragraphs)


def _chunk_text(text, size, overlap):
    text = re.sub(r"\s+", " ", text).strip()

    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


def _embed_and_store(chunks, source_key):
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        embeddings = _get_embeddings(batch)

        vectors = []
        for offset, (chunk_text, embedding) in enumerate(zip(batch, embeddings)):
            chunk_index = i + offset
            vectors.append({
                "key": f"{source_key}#chunk-{chunk_index}-{uuid.uuid4().hex[:8]}",
                "data": {"float32": embedding},
                "metadata": {
                    "source_text": chunk_text,
                    "source_document": source_key,
                    "chunk_index": chunk_index,
                },
            })

        s3vectors.put_vectors(
            vectorBucketName=VECTOR_BUCKET_NAME,
            indexName=VECTOR_INDEX_NAME,
            vectors=vectors,
        )
        print(f"Stored {len(vectors)} vectors (chunks {i} to {i + len(vectors) - 1}).")


def _get_embeddings(texts):
    body = json.dumps({
        "texts": texts,
        "input_type": "search_document",
    })
    response = bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=body,
        accept="*/*",
        contentType="application/json",
    )
    response_body = json.loads(response["body"].read())
    return response_body["embeddings"]