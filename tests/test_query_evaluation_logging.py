"""Offline tests for the widget's /query handler. No credentials or AWS calls."""
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_handler():
    spec = importlib.util.spec_from_file_location('query_evaluation_under_test',
                                                Path(__file__).resolve().parents[1] / 'query_lambda.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'boto3': SimpleNamespace(client=Mock(return_value=Mock()))}), \
         patch.dict(os.environ, {'VECTOR_BUCKET_NAME': 'offline-test', 'VECTOR_INDEX_NAME': 'fixture', 'TOP_K': '5'}):
        spec.loader.exec_module(module)
    return module


class EvaluationLoggingTests(unittest.TestCase):
    def test_full_handler_emits_five_chunks_to_real_log_stream(self):
        # Exercise the real embedding/generation functions and logging handler.
        # Only the AWS SDK clients are replaced; no credentials/network are used.
        api = load_handler()
        passages = [f'Passage {i}: NEU requirements.\nQuoted: "dokumento" — résumé.' for i in range(5)]
        vectors = [{'key': f'fixture-{i}', 'distance': i / 10,
                    'metadata': {'source_text': text, 'source_document': 'fixture.txt', 'chunk_index': i}}
                   for i, text in enumerate(passages)]
        api.s3vectors = Mock()
        api.s3vectors.query_vectors.return_value = {'vectors': vectors}
        api.bedrock = Mock()
        answer = 'Synthetic answer.\nPlease confirm requirements.'
        api.bedrock.invoke_model.side_effect = [
            {'body': io.BytesIO(json.dumps({'embeddings': [[0.1, 0.2]]}).encode())},
            {'body': io.BytesIO(json.dumps({'content': [{'text': answer}]}).encode())},
        ]
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        old_handlers, old_propagate = api.logger.handlers[:], api.logger.propagate
        api.logger.handlers = [handler]
        api.logger.propagate = False
        try:
            response = api.lambda_handler({'body': json.dumps({'query': 'What are the requirements?'})}, self.context)
            handler.flush()
        finally:
            api.logger.handlers = old_handlers
            api.logger.propagate = old_propagate
            handler.close()
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(records), 8)  # start, retrieval, five chunks, answer
        self.assertEqual(records[1]['top_k'], 5)
        self.assertEqual(records[1]['returned_count'], 5)
        self.assertEqual([r['text'] for r in records if r['event'] == 'retrieved_chunk'], passages)
        self.assertEqual({r['request_id'] for r in records}, {self.context.aws_request_id})
        self.assertEqual(records[-1]['answer'], answer)
        self.assertEqual(json.loads(response['body'])['answer'], answer)
        calls = api.bedrock.invoke_model.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(calls[0].kwargs['body'])['input_type'], 'search_query')
        model_prompt = json.loads(calls[1].kwargs['body'])['messages'][0]['content']
        self.assertIn('\n\n---\n\n'.join(passages), model_prompt)
        self.assertEqual(api.s3vectors.query_vectors.call_args.kwargs['topK'], 5)

    def setUp(self):
        self.api = load_handler()
        self.api._embed_query = Mock(return_value=[0.1, 0.2])
        self.api._generate_answer = Mock(return_value='Contact the admissions office.')
        self.matches = [
            {'key': 'chunk-1', 'distance': 0.12, 'metadata': {
                'source_text': 'Contact the admissions office.',
                'source_document': 'fixture.txt', 'chunk_index': 0}},
            {'key': 'chunk-2', 'distance': 0.3, 'metadata': {'filename': 'legacy.txt', 'source_text': 'Second passage.'}},
        ]
        self.api.s3vectors.query_vectors.return_value = {'vectors': self.matches}
        env = patch.dict(os.environ, {'NEUBIE_TEST_LOGGING': 'true'})
        env.start()
        self.addCleanup(env.stop)
        self.context = SimpleNamespace(aws_request_id='offline-request-1', function_version='$LATEST')

    def call(self, **extra):
        return self.api.lambda_handler({'body': json.dumps({'query': 'How do I apply?', **extra})}, self.context)

    def capture(self):
        with self.assertLogs(self.api.logger, level='INFO') as logs:
            response = self.call()
        return response, [json.loads(r.getMessage()) for r in logs.records]

    def test_k_rank_text_and_answer_are_correlated(self):
        response, events = self.capture()
        self.assertEqual(response['statusCode'], 200)
        self.assertEqual({e['request_id'] for e in events}, {'offline-request-1'})
        self.assertEqual(events[0]['top_k'], 5)
        self.assertEqual(events[0]['lambda_version'], '$LATEST')
        self.assertEqual(events[1]['returned_count'], 2)
        chunks = [e for e in events if e['event'] == 'retrieved_chunk']
        self.assertEqual([e['rank'] for e in chunks], [1, 2])
        self.assertEqual([e['chunk_id'] for e in chunks], ['chunk-1', 'chunk-2'])
        self.assertEqual(chunks[0]['text'], self.matches[0]['metadata']['source_text'])
        self.assertEqual(chunks[1]['source_document'], 'legacy.txt')
        self.assertEqual(chunks[0]['distance'], .12)
        self.assertEqual(events[-1]['answer'], json.loads(response['body'])['answer'])
        self.api._generate_answer.assert_called_once_with('How do I apply?', 'Contact the admissions office.\n\n---\n\nSecond passage.')
        self.assertEqual(self.api.s3vectors.query_vectors.call_args.kwargs['topK'], 5)
        self.assertNotIn('chunks', json.loads(response['body']))

    def test_disabled_and_client_cannot_enable(self):
        with patch.dict(os.environ, {'NEUBIE_TEST_LOGGING': 'false'}), self.assertNoLogs(self.api.logger):
            off = self.call(test_logging=True, top_k=10)
        on, _ = self.capture()
        self.assertEqual(off, on)
        self.assertEqual(self.api.s3vectors.query_vectors.call_args.kwargs['topK'], 5)

    def test_unset_switch_is_disabled(self):
        with patch.dict(os.environ):
            os.environ.pop('NEUBIE_TEST_LOGGING', None)
            with self.assertNoLogs(self.api.logger):
                self.call()

    def test_empty_results_have_fallback_evidence(self):
        self.api.s3vectors.query_vectors.return_value = {'vectors': []}
        response, events = self.capture()
        self.assertEqual(events[1]['returned_count'], 0)
        self.assertEqual(events[-1]['outcome'], 'no_matches')
        self.assertEqual(events[-1]['answer'], json.loads(response['body'])['answer'])
        self.api._generate_answer.assert_not_called()

    def test_missing_metadata_does_not_invent_text(self):
        self.api.s3vectors.query_vectors.return_value = {'vectors': [{'key': 'no-text'}]}
        _, events = self.capture()
        chunk = events[2]
        self.assertEqual(chunk['text'], '')
        self.assertFalse(chunk['included_in_context'])
        self.assertIsNone(chunk['source_document'])

    def test_failures_identify_stage_without_false_completion(self):
        for stage, target in [('embedding', self.api._embed_query),
                              ('retrieval', self.api.s3vectors.query_vectors),
                              ('generation', self.api._generate_answer)]:
            with self.subTest(stage=stage):
                target.side_effect = RuntimeError('fixture failure')
                response, events = self.capture()
                self.assertEqual(response['statusCode'], 500)
                self.assertEqual(events[-1]['event'], 'query_failed')
                self.assertEqual(events[-1]['stage'], stage)
                self.assertFalse(any(e['event'] == 'answer_completed' for e in events))
                target.side_effect = None

    def test_configured_k_matches_search_and_log(self):
        for k in [3, 5, 10]:
            with self.subTest(k=k), patch.object(self.api, 'TOP_K', k):
                _, events = self.capture()
                self.assertEqual(events[0]['top_k'], k)
                self.assertEqual(events[1]['top_k'], k)
                self.assertEqual(self.api.s3vectors.query_vectors.call_args.kwargs['topK'], k)

    def test_local_request_ids_are_unique(self):
        self.context = None
        _, first = self.capture()
        _, second = self.capture()
        self.assertNotEqual(first[0]['request_id'], second[0]['request_id'])
        self.assertEqual(len({e['request_id'] for e in first}), 1)


if __name__ == '__main__':
    if '--sample' in sys.argv:
        case = EvaluationLoggingTests()
        case.setUp()
        try:
            _, events = case.capture()
            for event in events:
                print(json.dumps(event, ensure_ascii=False))
        finally:
            case.doCleanups()
    else:
        unittest.main()
