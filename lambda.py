import json
import os
import uuid
import boto3
from botocore.config import Config

# signature_version s3v4 is required for presigned URLs to work correctly
# in most regions, including us-east-1.
s3_client = boto3.client("s3", config=Config(signature_version="s3v4"))

# Read from a Lambda environment variable rather than hardcoding, so this
# can point at the mock bucket now and a production bucket later without
# touching code.
BUCKET_NAME = os.environ["RAW_BUCKET_NAME"]
URL_EXPIRATION_SECONDS = 300  # presigned URL is valid for 5 minutes


def lambda_handler(event, context):
    query_params = event.get("queryStringParameters") or {}
    filename = query_params.get("filename")
    content_type = query_params.get("contentType", "application/octet-stream")

    if not filename:
        return _response(400, {"error": "Missing required 'filename' query parameter"})

    # Prefix with a UUID so two admins uploading files with the same name
    # don't silently overwrite each other's object in S3.
    safe_key = f"{uuid.uuid4()}-{os.path.basename(filename)}"

    try:
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": safe_key,
                "ContentType": content_type,
            },
            ExpiresIn=URL_EXPIRATION_SECONDS,
        )
    except Exception as e:
        # Don't leak internal exception details to the client in a real
        # production system -- fine to see while you're debugging locally.
        return _response(500, {"error": "Failed to generate upload URL", "details": str(e)})

    return _response(200, {"uploadUrl": presigned_url, "key": safe_key})


def _response(status_code, body_dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            # Wide open for development. Tighten this to your actual
            # frontend origin before this ever goes near production.
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body_dict),
    }
