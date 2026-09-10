import boto3
import json
from dotenv import load_dotenv
import os

load_dotenv()  # reads your .env file

client = boto3.client(
    "bedrock-runtime",
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

response = client.invoke_model(
    modelId="anthropic.claude-sonnet-4-6-v1:0",  # confirm exact ID in Bedrock console
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 50,
        "messages": [
            {"role": "user", "content": "Say hello in one short sentence."}
        ]
    }),
    contentType="application/json",
    accept="application/json",
)

result = json.loads(response["body"].read())
print(result["content"][0]["text"])