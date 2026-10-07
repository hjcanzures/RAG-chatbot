import json
import os
import boto3

bedrock = boto3.client("bedrock-runtime")
s3vectors = boto3.client("s3vectors")

# Same vector bucket/index the admin panel writes into during ingestion.
VECTOR_BUCKET_NAME = os.environ["VECTOR_BUCKET_NAME"]      # e.g. askneu-vectors
VECTOR_INDEX_NAME = os.environ["VECTOR_INDEX_NAME"]        # e.g. mock-documents

EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "cohere.embed-multilingual-v3")
CHAT_MODEL_ID = os.environ.get("CHAT_MODEL_ID", "anthropic.claude-sonnet-4-6-v1:0")

# How many chunks to retrieve per question. Kept small since each chunk is
# only ~500 chars -- 5 chunks is plenty of context without bloating the
# prompt or drowning the model in irrelevant text.
TOP_K = int(os.environ.get("TOP_K", "5"))

SYSTEM_PROMPT = (
    "You are Ask Neu, an assistant for New Era University. Answer the "
    "user's question using ONLY the context chunks provided below. "
    "If the context doesn't contain the answer, say you don't have that "
    "information yet rather than guessing. Keep answers concise and "
    "friendly. Do not mention 'chunks', 'context', or that you were given "
    "search results -- just answer naturally."
)


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Request body must be valid JSON"})

    question = (body.get("query") or "").strip()
    if not question:
        return _response(400, {"error": "Missing required 'query' field in request body"})

    # Step 1: embed the question. input_type=search_query (not
    # search_document) -- this is what makes the query embedding line up
    # correctly with the document embeddings Cohere generated at ingest time.
    try:
        query_vector = _embed_query(question)
    except Exception as e:
        return _response(500, {"error": "Failed to embed query", "details": str(e)})

    # Step 2: similarity search against S3 Vectors.
    try:
        matches = s3vectors.query_vectors(
            vectorBucketName=VECTOR_BUCKET_NAME,
            indexName=VECTOR_INDEX_NAME,
            topK=TOP_K,
            queryVector={"float32": query_vector},
            returnMetadata=True,
            returnDistance=True,
        )["vectors"]
    except Exception as e:
        return _response(500, {"error": "Vector search failed", "details": str(e)})

    if not matches:
        # No vectors in the index at all yet (e.g. nothing ingested).
        return _response(200, {
            "answer": "I don't have any documents indexed yet, so I can't answer that.",
            "sources": [],
        })

    # Step 3: build context from retrieved chunks. source_text is the
    # non-filterable metadata key the ingestion Lambda stores the raw
    # chunk text under.
    chunks = [m["metadata"].get("source_text", "") for m in matches if m.get("metadata")]
    context_block = "\n\n---\n\n".join(chunks)

    # Step 4: prompt augmentation + generation.
    try:
        answer = _generate_answer(question, context_block)
    except Exception as e:
        return _response(500, {"error": "Failed to generate answer", "details": str(e)})

    sources = [
        {"filename": m["metadata"].get("filename"), "distance": m.get("distance")}
        for m in matches if m.get("metadata")
    ]

    return _response(200, {"answer": answer, "sources": sources})


def _embed_query(text):
    resp = bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({
            "texts": [text],
            "input_type": "search_query",
        }),
        accept="*/*",
        contentType="application/json",
    )
    result = json.loads(resp["body"].read())
    return result["embeddings"][0]


def _generate_answer(question, context_block):
    user_message = (
        f"Context:\n{context_block}\n\n"
        f"Question: {question}"
    )
    resp = bedrock.invoke_model(
        modelId=CHAT_MODEL_ID,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_message}
            ],
        }),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(resp["body"].read())
    return result["content"][0]["text"]


def _response(status_code, body_dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            # Wide open for development, same as the other Lambdas in this
            # project -- tighten before this goes near production.
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body_dict),
    }
