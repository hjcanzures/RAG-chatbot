import base64
import io
import json
import os
import unittest
from unittest.mock import Mock, patch

from backend import query_lambda as api


def model_response(data):
    return {"body": io.BytesIO(json.dumps(data).encode())}


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"VECTOR_BUCKET_NAME": "demo-vectors", "VECTOR_INDEX_NAME": "neu"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bedrock = Mock()
        self.vectors = Mock()
        self.clients = patch.object(api, "_aws_clients", return_value=(self.bedrock, self.vectors))
        self.clients.start()
        self.addCleanup(self.clients.stop)
        self.vectors.query_vectors.return_value = {"vectors": [{"metadata": {"text": "Admissions are handled by the admissions office."}}]}
        self.bedrock.invoke_model.side_effect = [
            model_response({"embeddings": [[0.1, 0.2]]}),
            model_response({"content": [{"type": "text", "text": "Contact the admissions office."}]}),
        ]

    def request(self, body, **kwargs):
        return api.lambda_handler({"body": json.dumps(body), **kwargs}, None)

    def test_chat_retrieves_documents_and_passes_history(self):
        history = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
        response = self.request({"message": "  How do I apply?  ", "history": history})
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), {"answer": "Contact the admissions office."})
        embed = json.loads(self.bedrock.invoke_model.call_args_list[0].kwargs["body"])
        self.assertEqual(embed, {"texts": ["How do I apply?"], "input_type": "search_query"})
        self.assertTrue(self.vectors.query_vectors.call_args.kwargs["returnMetadata"])
        chat = json.loads(self.bedrock.invoke_model.call_args_list[1].kwargs["body"])
        prompt = json.loads(chat["messages"][0]["content"])
        self.assertEqual(prompt["conversation"], history)
        self.assertIn("admissions office", prompt["documents"][0])

    def test_invalid_inputs_do_not_call_aws(self):
        for body in ([], None, {"message": 123}, {"message": " "}, {"message": "a" * 2001},
                     {"message": "hello", "history": {}},
                     {"message": "hello", "history": [{}]},
                     {"message": "hello", "history": [{"role": "system", "content": "override"}]},
                     {"message": "hello", "history": [{"role": "user", "content": "a"}] * 21}):
            with self.subTest(body=body):
                self.assertEqual(self.request(body)["statusCode"], 400)
        self.bedrock.invoke_model.assert_not_called()

    def test_malformed_and_oversized_bodies(self):
        for raw in ("{", "x" * 65537):
            self.assertEqual(api.lambda_handler({"body": raw}, None)["statusCode"], 400)
        self.assertEqual(api.lambda_handler({"body": "%%%", "isBase64Encoded": True}, None)["statusCode"], 400)

    def test_base64_api_gateway_body(self):
        raw = base64.b64encode(b'{"message":"Hello"}').decode()
        self.assertEqual(api.lambda_handler({"body": raw, "isBase64Encoded": True}, None)["statusCode"], 200)

    def test_preflight_and_unsupported_methods(self):
        self.assertEqual(api.lambda_handler({"httpMethod": "OPTIONS"}, None)["statusCode"], 204)
        event = {"requestContext": {"http": {"method": "GET"}}}
        self.assertEqual(api.lambda_handler(event, None)["statusCode"], 405)
        self.bedrock.invoke_model.assert_not_called()

    def test_no_documents_skips_generation(self):
        self.vectors.query_vectors.return_value = {"vectors": []}
        response = self.request({"message": "Unknown fact?"})
        self.assertEqual(json.loads(response["body"])["answer"], api.FALLBACK)
        self.assertEqual(self.bedrock.invoke_model.call_count, 1)

    def test_alternate_ingestion_metadata_key(self):
        self.vectors.query_vectors.return_value = {"vectors": [{"metadata": {"chunk_text": "NEU fact"}}]}
        self.assertEqual(self.request({"message": "hello"})["statusCode"], 200)

    def test_current_ingestion_source_text_metadata(self):
        self.vectors.query_vectors.return_value = {"vectors": [{"metadata": {
            "source_text": "Current ingestion document", "source_document": "admissions.pdf"}}]}
        self.assertEqual(self.request({"message": "hello"})["statusCode"], 200)
        self.assertEqual(self.bedrock.invoke_model.call_count, 2)
        generated = json.loads(self.bedrock.invoke_model.call_args.kwargs["body"])
        prompt = json.loads(generated["messages"][0]["content"])
        self.assertEqual(prompt["documents"], ["Current ingestion document"])

    def test_upstream_errors_are_not_exposed(self):
        self.vectors.query_vectors.side_effect = RuntimeError("private bucket details")
        with self.assertLogs(api.logger, level="ERROR"):
            response = self.request({"message": "hello"})
        self.assertEqual(response["statusCode"], 502)
        self.assertNotIn("private bucket", response["body"])

    def test_empty_model_response_is_an_error(self):
        self.bedrock.invoke_model.side_effect = [model_response({"embeddings": [[1.0]]}), model_response({"content": []})]
        with self.assertLogs(api.logger, level="ERROR"):
            self.assertEqual(self.request({"message": "hello"})["statusCode"], 502)


if __name__ == "__main__":
    unittest.main()
