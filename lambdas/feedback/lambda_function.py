import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = TABLE_NAME = os.environ["FEEDBACK_TABLE_NAME"]
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "180"))
table = boto3.resource("dynamodb").Table(TABLE_NAME)

# Keep in sync with the widget / query Lambda limits.
MAX_QUERY_CHARS = 500
MAX_ANSWER_CHARS = 4000
MAX_SOURCES = 10
MAX_SOURCE_NAME_CHARS = 80
MAX_BODY_BYTES = 32 * 1024

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
RESPONSE_ID_RE = re.compile(r"^\d{10,16}-\d{1,6}$")
VALID_RATINGS = {"up", "down"}


def lambda_handler(event, context):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", errors="replace")

    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        return _response(413, {"error": "Request too large"})

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _response(400, {"error": "Body must be valid JSON"})

    error = _validate(payload)
    if error:
        return _response(400, {"error": error})

    # Server-side timestamps only; never trust the client's clock.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    expires_at = int(time.time()) + RETENTION_DAYS * 86400

    try:
        table.update_item(
            Key={"sessionId": payload["sessionId"], "responseId": payload["responseId"]},
            UpdateExpression=(
                "SET #rating = :rating, #query = :query, #answer = :answer, "
                "#sources = :sources, #updatedAt = :now, #expiresAt = :expires, "
                "#createdAt = if_not_exists(#createdAt, :now)"
            ),
            ExpressionAttributeNames={
                "#rating": "rating", "#query": "query", "#answer": "answer",
                "#sources": "sources", "#updatedAt": "updatedAt",
                "#expiresAt": "expiresAt", "#createdAt": "createdAt",
            },
            ExpressionAttributeValues={
                ":rating": payload["rating"],
                ":query": payload["query"].strip(),
                ":answer": payload["answer"].strip(),
                ":sources": payload.get("sources", []),
                ":now": now,
                ":expires": expires_at,
            },
        )
    except Exception:
        logger.exception("Failed to write feedback")
        return _response(500, {"error": "Could not save feedback"})

    return _response(200, {"ok": True})


def _validate(p):
    if not isinstance(p, dict):
        return "Body must be a JSON object"
    if not isinstance(p.get("sessionId"), str) or not UUID_RE.match(p["sessionId"]):
        return "Invalid sessionId"
    if not isinstance(p.get("responseId"), str) or not RESPONSE_ID_RE.match(p["responseId"]):
        return "Invalid responseId"
    if p.get("rating") not in VALID_RATINGS:
        return "rating must be 'up' or 'down'"
    q, a = p.get("query"), p.get("answer")
    if not isinstance(q, str) or not q.strip() or len(q) > MAX_QUERY_CHARS:
        return "Invalid query"
    if not isinstance(a, str) or not a.strip() or len(a) > MAX_ANSWER_CHARS:
        return "Invalid answer"
    s = p.get("sources", [])
    if (not isinstance(s, list) or len(s) > MAX_SOURCES
            or not all(isinstance(x, str) and len(x) <= MAX_SOURCE_NAME_CHARS for x in s)):
        return "Invalid sources"
    return None


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",  # tighten to your site before deployment
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }