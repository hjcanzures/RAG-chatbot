# AI-Powered RAG Chatbot

An AI-powered chatbot for New Era University, built with Retrieval-Augmented Generation (RAG) on AWS. The chatbot retrieves relevant information from a document knowledge base and provides that information to a foundation model as context before generating a response, rather than relying solely on the model's pre-trained knowledge.

The project is currently under active development.

## Project Overview

Instead of relying solely on the language model's pre-trained knowledge, the system retrieves relevant information from a designated knowledge base and provides that information to the AI model as context before generating a response.

**AI infrastructure:** Amazon Bedrock, using:
- **Cohere Embed Multilingual V3** for generating vector embeddings (1024 dimensions)
- **Claude Sonnet 4.6** as the response-generation model

**Vector storage:** Amazon S3 Vectors — a native S3 vector index, avoiding the need for a separate vector database.

## Architecture

The system is split into two independent flows:

**Admin document ingestion**
```text
Admin (web UI)
  ↓ drag-and-drop upload
Presigned-URL Lambda + API Gateway
  ↓ browser uploads directly to S3
S3 (raw document bucket)
  ↓ S3 event trigger
Ingestion Lambda
  ↓ chunk (500 chars) → embed (Cohere) → store
Amazon S3 Vectors (vector index)
```

**User query** *(API implemented; live deployment verification pending)*
```text
User (chat widget)
  ↓ query
API Gateway POST /chat
  ↓
Query Lambda
  ↓ embed query (Cohere) → similarity search
Amazon S3 Vectors
  ↓ retrieved chunks
Prompt augmentation + bounded conversation history
  ↓
Claude Sonnet 4.6 (Amazon Bedrock)
  ↓ generated response
Chat widget
```

### AWS resources in use

| Component | Service |
|---|---|
| Embeddings | Bedrock — Cohere Embed Multilingual V3 |
| Response generation | Bedrock — Claude Sonnet 4.6 |
| Vector storage | Amazon S3 Vectors |
| Raw document storage | Amazon S3 |
| Backend compute | AWS Lambda (Python) |
| API layer | Amazon API Gateway (HTTP API) |

### Repository structure

- `front-end/` — mock university website for the defense demonstration, with the Neubie chat widget on `main/index.htm`
- `front-end/main/assets/scripts/chatbot-config.js` — the AWS chat endpoint setting
- `front-end/main/assets/scripts/chatbot-widget.js` — demo chat UI and API client
- `backend/query_lambda.py` — independently deployable `POST /chat` API using Bedrock and S3 Vectors
- `backend/requirements.txt` — SDK dependency packaged with the API
- `template.yaml` — AWS SAM deployment for the chat Lambda, HTTP API, CORS, throttling, and IAM role
- `docs/neubie-api.md` — API contract, AWS deployment steps, and frontend connection instructions
- `tests/test_chat_api.py` — API tests with mocked AWS services
- `query_lambda.py` — compatibility entry point for the backend handler
- `index.html` — original standalone widget icon design
- `admin_panel.html` — admin document-upload interface
- `lambda.py` — presigned-URL upload Lambda

Start with [Neubie API deployment and connection instructions](docs/neubie-api.md).

## Current Progress

### Completed

- [x] Designed the initial RAG workflow and overall chatbot architecture
- [x] Created the initial chatbot widget/icon, designed to be reusable and embeddable
- [x] Enabled Amazon Bedrock model access (Cohere Embed Multilingual V3, Claude Sonnet 4.6)
- [x] Created and configured the Amazon S3 Vectors bucket and index
- [x] Built the presigned-URL upload Lambda + API Gateway route, enabling direct browser-to-S3 uploads
- [x] Built the document ingestion Lambda: text extraction (PDF/DOCX/TXT), chunking, embedding via Cohere, and storage in S3 Vectors — verified working end-to-end
- [x] Built the admin panel UI: drag-and-drop upload, live document list with real chunk counts, and delete (removes both the source file and its associated vectors)
- [x] Scoped least-privilege IAM roles per Lambda function

### In Progress

- [x] Build the query Lambda: embed user query, run similarity search against S3 Vectors
- [x] Implement prompt augmentation (system prompt + retrieved chunks + user query)
- [ ] Implement a cache check for repeated/similar queries
- [x] Wire Claude Sonnet 4.6 response generation in the API
- [x] Build the chat interface on the defense demo website
- [x] Connect the chat widget to a configurable API endpoint
- [ ] Deploy the API to AWS and paste its endpoint into the widget config
- [ ] Verify live Bedrock, S3 Vectors, and browser CORS end-to-end

### Planned

- [x] Bounded conversation history in the widget and query API
- [x] Error handling and fallback responses
- [x] AWS deployment template and connection guide
- [ ] Live AWS deployment
- [ ] Performance and response accuracy evaluation
- [ ] Point the pipeline at real New Era University documents (currently using mock/test data throughout)
