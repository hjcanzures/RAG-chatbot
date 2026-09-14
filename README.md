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

**User query** *(in progress — see below)*
```text
User (chat widget)
  ↓ query
Query Lambda
  ↓ embed query (Cohere) → similarity search
Amazon S3 Vectors
  ↓ retrieved chunks
Prompt augmentation + cache check
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

- `index.html` — the embeddable chatbot widget icon (chat interface not yet implemented)
- `admin-panel.html` — admin interface for uploading, listing, and deleting indexed documents
- Backend Lambda functions are developed and deployed separately (not yet committed to this repo as source)

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

- [ ] Build the query Lambda: embed user query, run similarity search against S3 Vectors
- [ ] Implement prompt augmentation (system prompt + retrieved chunks + user query)
- [ ] Implement a cache check for repeated/similar queries
- [ ] Wire Claude Sonnet 4.6 response generation
- [ ] Build the actual chat interface (currently only the widget icon exists)
- [ ] Connect the chat widget to the query backend

### Planned

- [ ] Conversation history
- [ ] Error handling and fallback responses
- [ ] Deployment
- [ ] Performance and response accuracy evaluation
- [ ] Point the pipeline at real New Era University documents (currently using mock/test data throughout)
