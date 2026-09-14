import json
import os
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO

import boto3

# Word's XML namespace, needed to find text nodes inside a .docx's internal XML.
_DOCX_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
s3vectors = boto3.client("s3vectors")

# All configurable via Lambda environment variables -- never hardcoded,
# so mock -> production is a config change, not a code change.
VECTOR_BUCKET_NAME = os.environ["VECTOR_BUCKET_NAME"]
VECTOR_INDEX_NAME = os.environ["VECTOR_INDEX_NAME"]
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "cohere.embed-multilingual-v3")

CHUNK_SIZE = 500      # characters per chunk, as decided
CHUNK_OVERLAP = 50    # see note below on why this isn't 0
BATCH_SIZE = 96       # Cohere's max texts per single InvokeModel call


def lambda_handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        # S3 event keys are URL-encoded (e.g. spaces become '+'); decode
        # before using the key to fetch the object.
        key = record["s3"]["object"]["key"].replace("+", " ")
        print(f"Processing s3://{bucket}/{key}")

        raw_bytes = _download_object(bucket, key)
        text = _extract_text(key, raw_bytes)

        if not text.strip():
            print(f"No extractable text found in {key}, skipping.")
            continue

        chunks = _chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        print(f"Split '{key}' into {len(chunks)} chunks.")

        _embed_and_store(chunks, source_key=key)

    return {"statusCode": 200, "body": json.dumps({"message": "Processing complete"})}


def _download_object(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _extract_text(key, raw_bytes):
    ext = key.rsplit(".", 1)[-1].lower()

    if ext == "txt":
        return raw_bytes.decode("utf-8", errors="ignore")

    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(raw_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if ext == "docx":
        return _extract_docx_text(raw_bytes)

    raise ValueError(f"Unsupported file type: .{ext}")


def _extract_docx_text(raw_bytes):
    # A .docx file is a zip archive; the actual document text lives in
    # word/document.xml as XML. No external library needed to read it.
    with zipfile.ZipFile(BytesIO(raw_bytes)) as docx_zip:
        xml_content = docx_zip.read("word/document.xml")

    tree = ET.fromstring(xml_content)
    paragraphs = []
    for para in tree.iter(_DOCX_WORD_NS + "p"):
        # Each paragraph can be split across multiple <w:t> "run" elements
        # (e.g. if part of it is bold) -- join them back into one line.
        run_texts = [node.text for node in para.iter(_DOCX_WORD_NS + "t") if node.text]
        paragraphs.append("".join(run_texts))

    return "\n".join(paragraphs)


def _chunk_text(text, size, overlap):
    # Collapse whitespace/newlines so chunk boundaries aren't skewed by
    # formatting artifacts from PDF/DOCX extraction.
    text = re.sub(r"\s+", " ", text).strip()

    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap  # step forward less than `size` so chunks overlap
    return chunks


def _embed_and_store(chunks, source_key):
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        embeddings = _get_embeddings(batch)

        vectors = []
        for offset, (chunk_text, embedding) in enumerate(zip(batch, embeddings)):
            chunk_index = i + offset
            vectors.append({
                # Unique per chunk, and traceable back to its source document.
                "key": f"{source_key}#chunk-{chunk_index}-{uuid.uuid4().hex[:8]}",
                "data": {"float32": embedding},
                "metadata": {
                    "source_text": chunk_text,       # non-filterable, set at index creation
                    "source_document": source_key,   # filterable by default
                    "chunk_index": chunk_index,       # filterable by default
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
        # search_document tells Cohere these are corpus entries, not a
        # live user query -- the query Lambda will use "search_query" instead.
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
