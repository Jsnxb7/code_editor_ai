import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bob_core.structured_logging import append_jsonl, prompt_metadata


class StructuredLoggingTests(unittest.TestCase):
    def test_jsonl_log_redacts_secrets_and_drops_contents(self):
        with tempfile.TemporaryDirectory(prefix="bob-logs-") as temporary, patch.dict(
            "os.environ", {"BOB_COLAB_TOKEN": "tiny"}, clear=False
        ):
            path = Path(temporary) / "events.jsonl"
            append_jsonl(path, "model.test", {
                "request_id": "request-1",
                "message": "token=tiny Authorization Bearer abc.def.ghi",
                "authorization": "Bearer should-not-store",
                "code": "print('secret')",
            })
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("model.test", record["event"])
            self.assertNotIn("tiny", json.dumps(record))
            self.assertNotIn("abc.def.ghi", json.dumps(record))
            self.assertNotIn("authorization", record)
            self.assertNotIn("code", record)

    def test_prompt_metadata_uses_hash_and_size_only(self):
        metadata = prompt_metadata("private prompt")
        self.assertEqual(len("private prompt"), metadata["prompt_size_bytes"])
        self.assertEqual(64, len(metadata["prompt_sha256"]))
        self.assertNotIn("private prompt", json.dumps(metadata))


if __name__ == "__main__":
    unittest.main()
