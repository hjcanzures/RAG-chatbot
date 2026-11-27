# Local evaluation logging for the widget query API

Scope: root `query_lambda.py`, the `/query` contract used by the widget. The separate SAM `backend/query_lambda.py` `/chat` handler is not instrumented by this change. Confirm which source and Lambda version are deployed before adopting it. No AWS deployment or environment was changed.

## Review and run offline

From the repository root:

```powershell
python tests/test_query_evaluation_logging.py -v
python tests/test_query_evaluation_logging.py --sample
```

These tests replace the AWS clients and model calls with fixed fixtures. They require no AWS credentials, network, or boto3 installation. The sample prints JSON lines showing K=5, two synthetic retrieved passages, and a synthetic answer. It proves the instrumentation works locally, not retrieval accuracy or live AWS connectivity.

## Enable on a test Lambda after review

Set these Lambda environment variables and deploy the reviewed root handler using the team's existing deployment process:

```text
TOP_K=5
NEUBIE_TEST_LOGGING=true
```

Logging is disabled when the second variable is absent or not `true` (case-insensitive). Request payloads cannot enable it or override K. TOP_K is loaded at module initialization. The code uses the same TOP_K value in the search and logs.

Send a test question through the existing `/query` API. In that Lambda's CloudWatch log stream, find JSON messages whose schema is `neubie.evaluation.v1`. Group all events by the Lambda invocation `request_id`. Local calls without a Lambda context receive a generated UUID. The question in `query_started` can be matched to the fixed 15-question test set.

| Event | Evidence |
| --- | --- |
| query_started | Question, configured K, bucket/index, model IDs, system prompt hash, Lambda version |
| retrieval_completed | Actual returned count and configured K |
| retrieved_chunk | One record per result: 1-based rank, vector key, exact source_text, document, chunk index, distance, context inclusion |
| answer_completed | Exact returned answer and generated/no_matches outcome |
| query_failed | Failed stage and exception type; no successful answer event |

Ranks follow the vector service's returned order. Distance is not a confidence percentage. `included_in_context` mirrors the existing handler's metadata-presence rule; an included result can still have empty text. Missing IDs, sources, or distances remain null; they are never invented. Only the source_text field is used by this handler, so the logs preserve that same text, not other metadata aliases. History is not added to logs or to the existing prompt by this change.

The API response stays unchanged. Question and document text appear only in the opt-in evaluation logs. Use restricted-access test logs and disable the flag after collecting the evaluation run. Large passages/answers remain subject to the logging platform's event-size limits; the code emits chunks separately and does not intentionally truncate them. Check completeness of exported records before scoring.

## Scoring

Save the correlated records for each question. Count relevant retrieved chunks using human-approved relevance labels. Recall additionally needs the complete set of relevant corpus chunks. Faithfulness requires reviewing the answer's factual claims against the logged text. Keep the corpus and generation configuration fixed across runs. These logs do not prove an immutable corpus snapshot or automatically calculate correctness.

Do not mark the existing public-API rerun as verified K=5 until a deployed test actually records K=5 and the corresponding retrieval evidence. The offline fixtures must not be entered as real university evaluation results.
