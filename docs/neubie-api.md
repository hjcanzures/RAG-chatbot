# Neubie API and AWS connection

The `front-end/` folder is the defense demonstration website. It contains the
Neubie interface, but no AWS credentials or model code. The independently
deployable API lives in `backend/`.

```text
Demo website / Neubie widget
  -> POST /chat (API Gateway)
  -> Lambda (backend/query_lambda.py)
  -> Bedrock Cohere query embedding
  -> existing S3 Vectors index (retrieve document chunks)
  -> Bedrock Claude answer
  -> {"answer": "..."} back to the widget
```

## API contract

`POST /chat` with `Content-Type: application/json`:

```json
{
  "message": "What are the admission requirements?",
  "history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hello! How can I help?"}
  ]
}
```

History is optional. Message and history content must be non-empty strings up to
2,000 characters; history accepts up to 20 entries with `user` or `assistant`
roles. The widget keeps the last ten successful exchanges in memory. Closing the
drawer keeps history; refreshing the page clears it. History is not persisted by
the API.

Success (`200`): `{"answer":"Contact the admissions office..."}`.
Invalid input (`400`) or upstream failure (`502`): `{"error":"..."}`.
An empty retrieval returns a grounded fallback without asking Claude to guess.

## Deploy with AWS SAM

Prerequisites: AWS CLI credentials for your account, AWS SAM CLI, Docker for
`--use-container`, enabled Bedrock models, and an existing S3 Vectors bucket/index
containing your ingested document chunks. Deploy in the region of that index.
The template creates a new chat API, Lambda, and IAM role; it does not create or
modify your document-ingestion pipeline or existing upload API.

From the repository root:

```powershell
sam build --use-container
sam deploy --guided
```

Use stack name `neubie-api`. Set these parameters in the guided prompts:

| Parameter | Value |
| --- | --- |
| `VectorBucketName` | Your existing S3 vector bucket name |
| `VectorIndexName` | Your existing vector index name |
| `AllowedOrigin` | `http://localhost:8000` for the local defense demo, or the exact hosted website origin |
| `EmbedModelId` | `cohere.embed-multilingual-v3` (must match ingestion embeddings) |
| `ChatModelId` | Enabled model ID, or inference profile ID such as `us.anthropic.claude-sonnet-4-6-v1:0` |
| `ChatFoundationModelId` | Underlying model ID without the inference profile prefix: `anthropic.claude-sonnet-4-6-v1:0` |
| `TopK` | `5` |

Allow SAM to create IAM resources and the public chat route. The role can query
and read metadata from the specified vector index and invoke the selected models.
The template includes `s3vectors:GetVectors` because returning metadata requires
it in addition to `s3vectors:QueryVectors`.

SAM packages the backend's boto3 dependency, so deployment does not depend on the
SDK version bundled in Lambda. The root `query_lambda.py` retains the existing
query-based API used by the original root widget. This deployment packages only
`backend/` and uses its message-based handler for the defense website.

## Connect the defense website

1. Copy the stack's `ChatEndpoint` output.
2. Paste it into `apiEndpoint` in
   `front-end/main/assets/scripts/chatbot-config.js`.
3. Serve the demo from the repository root:

   ```powershell
   python -m http.server 8000 --directory front-end/main
   ```

4. Open `http://localhost:8000/index.htm`, open Neubie, and ask about an indexed
   document. Serve over HTTP instead of opening the HTML as a `file://` URL.

You can test the deployed API independently of the website:

```powershell
$chatEndpoint = 'PASTE_CHAT_ENDPOINT_HERE'
$chatBody = @{ message = 'What are the admission requirements?'; history = @() } | ConvertTo-Json
Invoke-RestMethod -Uri $chatEndpoint -Method Post -ContentType 'application/json' -Body $chatBody
```

## If you prefer your existing AWS console setup

Package the **contents** of `backend/` plus its installed requirements at the zip
root. Set Python 3.12 and handler `query_lambda.lambda_handler`. Configure
`VECTOR_BUCKET_NAME`, `VECTOR_INDEX_NAME`, `EMBED_MODEL_ID`, `CHAT_MODEL_ID`, and
`TOP_K` as Lambda environment variables. Use the IAM actions and resource scopes
in `template.yaml` for the execution role, along with CloudWatch logging access.

Create or update an HTTP API `POST /chat` route with Lambda proxy integration
(payload version 2.0), grant API Gateway permission to invoke the Lambda, and
deploy the API stage. Configure CORS on **API Gateway** for the website origin,
`POST, OPTIONS` methods, and `Content-Type` header. Use a 29-second integration
timeout and a 28-second Lambda timeout. Then paste that endpoint into the same
config file.

## Validation and practical limits

```powershell
python -m pip install -r backend/requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
node --check front-end/main/assets/scripts/chatbot-widget.js
sam validate --lint
```

Unit tests mock AWS; a deployed request is still required to verify actual IAM,
model availability, vector metadata, and CORS. Retrieved text must be stored in
metadata under `source_text` (the current ingestion Lambda's key), `text`,
`chunkText`, `chunk_text`, or `content`. Embedding dimensions
and model must match your ingestion pipeline. If your index uses customer-managed
KMS encryption, add the corresponding KMS decrypt permission to the Lambda role.

The synchronous chat route has a 29-second gateway budget. The widget times out
after 32 seconds and restores its controls on failure. Slow model calls can still
hit the gateway limit; check CloudWatch logs for the underlying error.

This public demo API has a throttle of two requests per second and a burst of
five. CORS controls browser origins, but does not authenticate callers. A public
production deployment would need its chosen authentication and abuse controls.
There is no answer cache in this implementation.

AWS references: [SAM HTTP API integrations](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-httpapi.html),
[S3 Vectors query permissions](https://docs.aws.amazon.com/cli/latest/reference/s3vectors/query-vectors.html).
