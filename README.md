# AI-Powered RAG Chatbot

An AI-powered chatbot ("Neubie") for New Era University, built with Retrieval-Augmented Generation (RAG) on AWS. The chatbot retrieves relevant information from a document knowledge base and provides that information to a foundation model as context before generating a response, rather than relying solely on the model's pre-trained knowledge.

The project is currently under active development.

## Project Overview

Instead of relying solely on the language model's pre-trained knowledge, the system retrieves relevant information from a designated knowledge base and provides that information to the AI model as context before generating a response.

**AI infrastructure:** Amazon Bedrock, using:
- **Cohere Embed Multilingual V3** for generating vector embeddings (1024 dimensions)
- **Claude Sonnet 4.6** as the response-generation model, invoked via its cross-region inference profile (`us.anthropic.claude-sonnet-4-6`) rather than a plain foundation-model ID

**Vector storage:** Amazon S3 Vectors, a native S3 vector index that avoids a separate vector database.

**Feedback storage:** Amazon DynamoDB, holding student thumbs-up/thumbs-down ratings with a configurable retention period (default 180 days).

## Architecture

The system is split into independent flows, all implemented end-to-end.

**Admin document ingestion**
```text
Admin (web UI, token sign-in)
  ↓ drag-and-drop upload
Presigned-URL Lambda + API Gateway (admin authorizer)
  ↓ browser uploads directly to S3
S3 (raw document bucket)
  ↓ S3 event trigger
Ingestion Lambda
  ↓ extract text (PDF/DOCX/TXT) → structure-aware chunking → embed (Cohere) → store
Amazon S3 Vectors (vector index)
```

**User query**
```text
User (chat widget)
  ↓ question + recent conversation history
Query Lambda
  ↓ embed query (Cohere, input_type=search_query) → similarity search
Amazon S3 Vectors
  ↓ retrieved chunks (source_text + source_document metadata)
Prompt augmentation (persona + guardrails + retrieved chunks + history + question)
  ↓ (N-shot examples: planned)
Claude Sonnet 4.6 (Amazon Bedrock, inference profile)
  ↓ generated answer, or a grounded fallback if nothing relevant is retrieved
Chat widget
  ↓ 👍/👎 rating → POST /feedback
Feedback Lambda → DynamoDB

Lambdas → Amazon CloudWatch Logs (query/answer logging and errors)
```

**Quality and human-in-the-loop**
```text
Students rate answers in the widget (👍/👎)
  ↓
Admin panel → Feedback tab (search, filter, CSV export; admin token required)
  ↓ review unhelpful / flagged answers
Fix documents, prompt, or guardrails
  ↓
Re-run the evaluation set → compare results against earlier runs
```

### AWS resources in use

| Component | Service |
|---|---|
| Embeddings | Bedrock: Cohere Embed Multilingual V3 |
| Response generation | Bedrock: Claude Sonnet 4.6 (cross-region inference profile) |
| Guardrails | Bedrock Guardrails |
| Vector storage | Amazon S3 Vectors |
| Raw document storage | Amazon S3 |
| Feedback storage | Amazon DynamoDB |
| Backend compute | AWS Lambda (Python) |
| API layer | Amazon API Gateway (HTTP API) |
| Admin authentication | API Gateway Lambda authorizer, token in SSM Parameter Store |
| Logging | Amazon CloudWatch Logs |

## Neubie defense demo API

The defense website in `front-end/main/index.htm` uses a separate deployable
`POST /chat` API. Its AWS deployment is pending; the existing root widget and query
Lambda remain available for the current workflow.

How the assistant behaves:
- **Persona:** the system prompt defines Neubie as New Era University's friendly, concise virtual assistant.
- **Guardrails:** it answers only from the retrieved NEU documents, treats documents and conversation history as data (never as instructions that override its rules), and says it doesn't have the information, pointing to the relevant NEU office, when the documents don't contain the answer.
- **Fallback responses:** if retrieval returns nothing, a grounded fallback is returned without asking the model to guess.
- **Error handling:** invalid input returns `400`, oversized or malformed bodies are rejected, and upstream failures return `502` with a generic message. Internal details are logged to CloudWatch, never sent to the client. The widget also offers a link to NEU's contact directory on errors, fallbacks, and unhelpful ratings.
- **Conversation history:** the widget keeps the last three exchanges in memory and sends them with each question; the API accepts up to 20 history messages.

Files:
- `backend/query_lambda.py`: validated chat API with bounded conversation history
- `backend/requirements.txt`: packaged AWS SDK dependency
- `template.yaml`: AWS SAM chat API, Lambda, IAM, CORS, and throttling
- `front-end/main/assets/scripts/chatbot-config.js`: set the deployed API endpoint here
- `front-end/main/assets/scripts/chatbot-widget.js`: defense demo widget API client
- `tests/test_chat_api.py`: mocked AWS API tests

See [Neubie API deployment and connection instructions](docs/neubie-api.md).

## Human-in-the-loop feedback

- Each answer in the widget has copy, read-aloud, helpful/unhelpful, and expand controls. Ratings can be changed, and failed saves roll back so the student can retry.
- Ratings are sent to `POST /feedback`, validated server-side (session ID, response ID, rating, query, answer, sources, size limits), and stored in DynamoDB with server-side timestamps and an expiry (`RETENTION_DAYS`, default 180). Re-rating the same answer updates the existing record.
- Unhelpful ratings, failed requests, and fallback answers surface a support link to NEU's contact directory.
- The admin panel's **Feedback** tab reads `GET /feedback` (protected by the admin authorizer) and shows totals, helpful percentage, a searchable and filterable table, and CSV export.
- Negative feedback is a signal for manual review, not proof that an answer was wrong.

### Admin panel

`admin_panel_navy.html` has a token sign-in screen (the token is kept in memory only) and these sections: Overview, Knowledge Base (upload, list, delete documents and their vectors), Feedback, Chatbot Testing, and System & Logs. `/upload-url`, `/documents`, and `GET /feedback` require the `X-Admin-Token` header, enforced by an API Gateway Lambda authorizer; the token itself lives in SSM Parameter Store, not in the page.

## Repository structure

- `index.html`: the original embeddable chatbot widget (launcher avatar "Neubie" that expands into a chat window wired to `POST /query`)
- `admin_panel_navy.html`: admin console for uploading, listing, and deleting indexed documents, reviewing feedback, and testing the chatbot
- `query_lambda.py`: query Lambda for the original widget (`POST /query`)
- `lambda.py`: presigned-URL upload Lambda
- `lambdas/ingestion/`: ingestion Lambda source and `requirements.txt`
- `lambdas/documents/`: documents API Lambda (list and delete, including vector cleanup)
- `backend/`: independently deployable `POST /chat` API for the defense demo
- `template.yaml`: AWS SAM template for the `backend/` API
- `widget/`: embeddable widget (`neu-widget.js`, `neu-widget.css`), mascot assets, local demo page, and demo server
- `front-end/`: mock university website used for the defense demonstration
- `evaluation/`: test questions, retrieval test script, and saved results
- `tools/`: local helpers, including `dump_chunks.py` for inspecting ingestion chunks without AWS
- `tests/`: unit tests for the chat API and widget behavior
- `docs/`: API and deployment documentation

## Quality Assurance and Evaluation

Answer quality is tracked with a documented test log and a repeatable retrieval test.

**Test set:** `evaluation/test_questions.csv` holds 67 questions built from the six mock NEU documents: 52 answerable and 15 unanswerable (out-of-scope, unknown personal information, and hard negatives). Each row records:

| Column | Meaning |
|---|---|
| `id`, `category` | Question ID and type (paraphrase, informal, Taglish, table lookup, keywords only, typo, multi-part, out of scope, hard negative) |
| `question` | The prompt sent to the chatbot |
| `answerable` | Whether the documents contain the answer |
| `expected_doc`, `must_contain` | Document and distinctive phrase the retrieved chunk should contain |
| `expected_answer` | The expected output from the source document |

**Retrieval test:** `evaluation/retrieval_test.py` embeds each question, queries S3 Vectors, and reports hit@k, MRR, per-category results, the misses, and top-1 distance statistics (useful for choosing a distance cutoff for unanswerable questions). No LLM answer is generated, so a failure points at ingestion, chunking, or embedding rather than the prompt.

```text
python evaluation/retrieval_test.py evaluation/test_questions.csv --k 5 --label v2
```

**Saved runs** are in `evaluation/results/` (`results_baseline.csv`, `results_v2.csv`, `results_v2_k20.csv`) so changes can be compared over time. The same set is re-run after every change to the prompt, chunking, or documents. Results feed Chapter 4.

| Run | Chunking | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| baseline | 1200-char chunks | 67% | 90% | 96% | 0.803 |
| v2 | row-level table chunks, PDF table stitching | 73% | 94% | 94% | 0.833 |

Remaining retrieval misses are "where do I pay my tuition" style questions (the tuition fee rows outrank the Finance office row) and the "is the list of deans official" question.

**Answer-level check:** the same questions were also run through the live chatbot in a chat session, with about 91% answered correctly. Some valid questions returned the fallback within a long session but worked in a fresh one, which is being investigated.

Planned quality measures:
- **N-shot prompting:** include N example question/answer pairs in the prompt and compare N = 0, 1, 3, 5 against the test set
- **Answer-level test log:** store each chatbot answer next to the expected output with Pass/Fail

## Current Progress

### Completed

- [x] Designed the initial RAG workflow and overall chatbot architecture
- [x] Created the initial chatbot widget/icon, designed to be reusable and embeddable
- [x] Enabled Amazon Bedrock model access (Cohere Embed Multilingual V3, Claude Sonnet 4.6)
- [x] Created and configured the Amazon S3 Vectors bucket and index
- [x] Built the presigned-URL upload Lambda + API Gateway route, enabling direct browser-to-S3 uploads
- [x] Built the document ingestion Lambda: PDF/DOCX/TXT extraction, structure-aware chunking, embedding via Cohere, and storage in S3 Vectors, verified working end-to-end
- [x] Improved ingestion: row-level table chunks, PDF table extraction and stitching, cleaned document titles, and a local chunk inspector (`tools/dump_chunks.py`)
- [x] Built the admin panel UI: drag-and-drop upload, live document list with real chunk counts, and delete (removes both the source file and its associated vectors)
- [x] Added admin authentication: token sign-in and an API Gateway Lambda authorizer on admin routes
- [x] Scoped least-privilege IAM roles per Lambda function
- [x] Built the query Lambda: embed user query, run similarity search against S3 Vectors, verified working end-to-end
- [x] Implemented prompt augmentation (system prompt + retrieved chunks + user query) and wired Claude Sonnet 4.6 response generation
- [x] Built the actual chat interface (expandable widget replacing the static icon) and connected it to the query backend
- [x] Persona in the system prompt
- [x] Guardrails (answer only from retrieved NEU context, decline when the context has no answer)
- [x] Query/answer logging via Amazon CloudWatch Logs
- [x] Test log documentation (`evaluation/` test set, retrieval test, and saved results)
- [x] Human-in-the-loop feedback (widget ratings, DynamoDB storage, admin Feedback review)
- [x] Conversation history
- [x] Error handling and fallback responses

### In Progress

- [ ] Cache check for repeated/similar queries

### Planned

- [ ] N-shot prompting, compared across N values
- [ ] Extraction for scanned PDFs and other formats (Amazon Textract)
- [ ] Deployment
- [ ] Performance and response accuracy evaluation
- [ ] Point the pipeline at real New Era University documents (currently using mock/test data throughout)
