import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from pydantic import ValidationError

from bob_core.colab_adapter import ColabAdapter, ColabRetryError
from bob_core.contracts import CorrectionContract, DlqContract, EvaluationContract, PlanContract, ReviewContract


CONFIG = {
    "base_url": "https://example.invalid",
    "timeout": 30,
    "max_iterations": 5,
    "context_mode": "workspace",
    "context_budget": 160000,
    "keep_model_loaded": True,
    "prefer_streaming": False,
    "headers_json": "{}",
    "token": "",
    "model_id": "test-model",
    "model_revision": "r1",
    "prompt_set_version": "p1",
    "input_token_price_per_million": 1.0,
    "output_token_price_per_million": 2.0,
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()


class LlmOpsControlTests(unittest.TestCase):
    def adapter(self):
        with patch("bob_core.colab_adapter.read_model_config", return_value=CONFIG):
            return ColabAdapter()

    @patch("bob_core.colab_adapter.time.sleep", return_value=None)
    def test_transient_failure_enters_dlq_after_three_attempts(self, _sleep):
        adapter = self.adapter()
        with patch("bob_core.colab_adapter.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")) as call:
            with self.assertRaises(ColabRetryError) as raised:
                adapter.chat({"message": "hello"})
        self.assertEqual(3, call.call_count)
        self.assertEqual(3, len(raised.exception.attempts))
        self.assertTrue(raised.exception.dlq)

    @patch("bob_core.colab_adapter.time.sleep", return_value=None)
    def test_transport_retry_count_does_not_hide_runtime_attempt_count(self, _sleep):
        adapter = self.adapter()
        with patch("bob_core.colab_adapter.urllib.request.urlopen", side_effect=[urllib.error.URLError("brief outage"), FakeResponse({"reply": "ok", "attempt_count": 1})]):
            result = adapter.chat({"message": "hello"})
        self.assertEqual(2, result["attempt_count"])
        self.assertEqual(1, result["runtime_attempt_count"])

    def test_non_retryable_http_error_is_not_retried(self):
        adapter = self.adapter()
        error = urllib.error.HTTPError("url", 400, "bad", {}, io.BytesIO(b"invalid request"))
        with patch("bob_core.colab_adapter.urllib.request.urlopen", side_effect=error) as call:
            with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
                adapter.chat({"message": "hello"})
        self.assertEqual(1, call.call_count)

    def test_usage_and_cost_are_normalized(self):
        adapter = self.adapter()
        with patch("bob_core.colab_adapter.urllib.request.urlopen", return_value=FakeResponse({"reply": "ok", "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})):
            result = adapter.chat({"message": "hello"})
        self.assertEqual(1500, result["usage"]["total_tokens"])
        self.assertEqual(0.002, result["estimated_cost_usd"])
        self.assertEqual("test-model", result["model"])

    def test_transport_writes_redacted_request_and_response_events(self):
        adapter = self.adapter()
        with patch("bob_core.colab_adapter.log_tunnel") as logger, patch(
            "bob_core.colab_adapter.urllib.request.urlopen",
            return_value=FakeResponse({"reply": "ok"}),
        ):
            adapter.chat({"run_id": "run-1", "trace_id": "trace-1", "request_id": "request-1", "evaluation_run_id": "eval-1", "test_id": "case-1", "test_name": "Natural login request", "prompt_category": "new_user_natural", "pair_id": None, "approach": "direct_coder_model_reviewer", "pipeline_id": "eval-1:case-1:direct", "model_lane": 2, "message": "private"})
        self.assertEqual(["tunnel.request", "tunnel.response"], [call.args[0] for call in logger.call_args_list])
        self.assertEqual("request-1", logger.call_args_list[0].kwargs["request_id"])
        self.assertEqual("eval-1", logger.call_args_list[0].kwargs["evaluation_run_id"])
        self.assertEqual("case-1", logger.call_args_list[1].kwargs["test_id"])
        self.assertEqual("direct_coder_model_reviewer", logger.call_args_list[1].kwargs["approach"])
        self.assertEqual("eval-1:case-1:direct", logger.call_args_list[1].kwargs["pipeline_id"])
        self.assertEqual(2, logger.call_args_list[1].kwargs["model_lane"])
        self.assertNotIn("private", json.dumps(logger.call_args_list[0].kwargs))

    def test_contracts_validate_status_and_confidence(self):
        self.assertEqual("PASS", ReviewContract(review="ok", final_status="pass").final_status)
        with self.assertRaises(ValidationError):
            PlanContract(confidence=2)

    def test_governance_contracts_validate_persisted_boundaries(self):
        DlqContract(id="dlq_1", error={"type": "Timeout", "component": "colab", "message": "offline", "retriable": True})
        CorrectionContract(id="correction_1", original_prompt="before", corrected_prompt="after", expected_behavior="works", root_cause="prompt", severity="medium", author_user_id="admin")
        EvaluationContract(id="evaluation_1", source_type="correction", status="completed", revisions=[{"scores": {"correctness": 5, "helpfulness": 4, "completeness": 4, "safety": 5, "groundedness": 4}, "verdict": "acceptable", "failure_category": "prompt", "severity": "medium", "notes": "verified", "expected_behavior": "works"}])


if __name__ == "__main__":
    unittest.main()
