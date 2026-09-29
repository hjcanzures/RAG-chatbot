# AI-Powered RAG Chatbot

An AI-powered chatbot for New Era University, built with Retrieval-Augmented Generation (RAG) on AWS. The chatbot retrieves relevant information from a document knowledge base and provides that information to a foundation model as context before generating a response, rather than relying solely on the model's pre-trained knowledge.

The project is currently under active development.

## Project Overview

Instead of relying solely on the language model's pre-trained knowledge, the system retrieves relevant information from a designated knowledge base and provides that information to the AI model as context before generating a response.

**AI infrastructure:** Amazon Bedrock, using:
- **Cohere Embed Multilingual V3** for generating vector embeddings (1024 dimensions)
- **Claude Sonnet 4.6** as the response-generation model, invoked via its cross-region inference profile (`us.anthropic.claude-sonnet-4-6`) rather than a plain foundation-model ID

**Vector storage:** Amazon S3 Vectors, a native S3 vector index that avoids a separate vector database.

## Architecture

The system is split into two independent flows, both implemented end-to-end, with a quality and feedback loop being added on top.

**Admin document ingestion**
```text
Admin (web UI)
  ↓ drag-and-drop upload
Presigned-URL Lambda + API Gateway
  ↓ browser uploads directly to S3
S3 (raw document bucket)
  ↓ S3 event trigger
Ingestion Lambda
  ↓ extract text (PDF/DOCX/TXT) → chunk (500 chars, 50 overlap) → embed (Cohere) → store
Amazon S3 Vectors (vector index)
```

**User query**
```text
User (chat widget)
  ↓ query
Query Lambda
  ↓ embed query (Cohere, input_type=search_query) → similarity search
Amazon S3 Vectors
  ↓ retrieved chunks (source_text + source_document metadata)
Prompt augmentation (persona + guardrails + N-shot examples + chunks + query)
  ↓
Claude Sonnet 4.6 (Amazon Bedrock, inference profile)
  ↓ generated response + source attribution
Chat widget
  ↓ 👍/👎 feedback
Log store (query, retrieved chunks, answer, latency, feedback)
```

**Quality and human-in-the-loop** *(planned)*
```text
Log store
  ↓ flagged / low-rated answers
Admin review (human checking)
  ↓ fix documents, prompt, or examples
Re-run test log → compare results
```

### AWS resources in use

| Component | Service |
|---|---|
| Embeddings | Bedrock: Cohere Embed Multilingual V3 |
| Response generation | Bedrock: Claude Sonnet 4.6 (cross-region inference profile) |
| Vector storage | Amazon S3 Vectors |
| Raw document storage | Amazon S3 |
| Backend compute | AWS Lambda (Python) |
| API layer | Amazon API Gateway (HTTP API) |
| Logging *(planned)* | CloudWatch Logs and/or DynamoDB |

### Repository structure

- `index.html`: the embeddable chatbot widget, a launcher avatar ("Neubie") that expands into a full chat window wired to the query backend
- `admin_panel.html`: admin interface for uploading, listing, and deleting indexed documents
- `lambda.py`: presigned-URL upload Lambda
- `lambdas/ingestion/`: ingestion Lambda source and `requirements.txt`
- `lambdas/documents/`: documents API Lambda (list and delete, including vector cleanup)

## Quality Assurance and Evaluation

Answer quality is tracked with a documented test log. Each test case records:

| # | Prompt | Expected Output | Chatbot Answer | Pass/Fail |
|---|---|---|---|---|
| 1 | *(example question)* | *(expected answer from the source document)* | *(actual chatbot response)* | *(Pass/Fail)* |

The same test set is re-run after every change to the prompt, examples, chunking, or documents, so quality can be compared over time. Results feed Chapter 4.

Planned quality measures:
- **Persona:** a defined role and tone for the assistant in the system prompt
- **Guardrails:** answer only from retrieved NEU context, stay on topic, and decline or say "I don't know" when the context has no answer
- **N-shot prompting:** include N example question/answer pairs in the prompt and compare N = 0, 1, 3, 5 against the test log
- **Logging:** record every query, the retrieved chunks, the answer, latency, and user feedback
- **Human-in-the-loop:** 👍/👎 feedback in the chat widget, with an admin reviewing flagged answers

## Current Progress

### Completed

- [x] Designed the initial RAG workflow and overall chatbot architecture
- [x] Created the initial chatbot widget/icon, designed to be reusable and embeddable
- [x] Enabled Amazon Bedrock model access (Cohere Embed Multilingual V3, Claude Sonnet 4.6)
- [x] Created and configured the Amazon S3 Vectors bucket and index
- [x] Built the presigned-URL upload Lambda + API Gateway route, enabling direct browser-to-S3 uploads
- [x] Built the document ingestion Lambda: PDF/DOCX/TXT extraction, chunking, embedding via Cohere, and storage in S3 Vectors, verified working end-to-end
- [x] Fixed PDF ingestion: `pypdf` packaged for Lambda, S3 event keys decoded with `unquote_plus`, file format detected from file contents, and one bad file no longer blocks the rest
- [x] Built the admin panel UI: drag-and-drop upload, live document list with real chunk counts, and delete (removes both the source file and its associated vectors)
- [x] Scoped least-privilege IAM roles per Lambda function
- [x] Built the query Lambda: embed user query, run similarity search against S3 Vectors, verified working end-to-end
- [x] Implemented prompt augmentation (system prompt + retrieved chunks + user query) and wired Claude Sonnet 4.6 response generation
- [x] Built the actual chat interface (expandable widget replacing the static icon) and connected it to the query backend

### In Progress

- [ ] Cache check for repeated/similar queries

### Planned

- [ ] Persona in the system prompt
- [ ] Guardrails
- [ ] N-shot prompting, compared across N values
- [ ] Query/answer logging, included in the architecture
- [ ] Test log documentation (Prompt > Expected Output > Chatbot Answer > Pass/Fail)
- [ ] Human-in-the-loop feedback (chat widget ratings + admin review)
- [ ] Conversation history
- [ ] Error handling and fallback responses
- [ ] Extraction for scanned PDFs and other formats (Amazon Textract)
- [ ] Deployment
- [ ] Performance and response accuracy evaluation
- [ ] Point the pipeline at real New Era University documents (currently using mock/test data throughout)