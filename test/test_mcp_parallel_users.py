import threading
import time
import unittest
from unittest.mock import patch

import capabilities
from bob_core.model_queue import FairModelQueue
from bob_core import model_service


class McpParallelUserTests(unittest.TestCase):
    def test_direct_coder_always_passes_output_to_reviewer(self):
        with (
            patch.object(model_service, "create_run", return_value={"run_id": "run-direct"}),
            patch.object(model_service, "update_run", return_value={}),
            patch.object(model_service, "create_plan", return_value={"plan_id": "plan-direct"}),
            patch.object(model_service, "code_stage", return_value={"code": "print('ok')", "files": {"app.py": "print('ok')"}}) as coder,
            patch.object(model_service, "review_stage", return_value={"run": {"run_id": "run-direct", "status": "completed"}, "review": "PASS", "final_status": "PASS"}) as reviewer,
        ):
            result = model_service.direct_code_review_stage("workspace-a", "implement it", actor_user_id="user-a")

        coder.assert_called_once()
        reviewer.assert_called_once_with(
            "workspace-a",
            "plan-direct",
            "print('ok')",
            {"app.py": "print('ok')"},
            request_id=None,
            actor_user_id="user-a",
        )
        self.assertEqual("direct_coder_then_mandatory_reviewer", result["flow"])

    def test_model_capability_serializes_parallel_users_and_preserves_actor(self):
        queue = FairModelQueue()
        gate = threading.Event()
        started = []
        seen_actors = []
        results = {}
        lock = threading.Lock()
        old_queue = capabilities.MODEL_QUEUE
        capabilities.MODEL_QUEUE = queue

        def fake_plan(project, prompt, *_args, **kwargs):
            with lock:
                started.append(prompt)
                seen_actors.append(kwargs.get("actor_user_id"))
            if prompt == "a1":
                gate.wait(5)
            return {"plan_record": {"plan_id": prompt}, "run": {"run_id": prompt}}

        def invoke(user_id, prompt):
            results[prompt] = capabilities.model_plan(
                project=f"workspace-{user_id}",
                prompt=prompt,
                request_id=f"request-{prompt}",
                actor_user_id=user_id,
            )

        try:
            with patch.object(capabilities, "plan_stage", side_effect=fake_plan):
                first = threading.Thread(target=invoke, args=("user-a", "a1"))
                first.start()
                while started != ["a1"]:
                    time.sleep(0.005)
                second_a = threading.Thread(target=invoke, args=("user-a", "a2"))
                first_b = threading.Thread(target=invoke, args=("user-b", "b1"))
                second_a.start()
                time.sleep(0.01)
                first_b.start()
                time.sleep(0.01)

                other_status = capabilities.model_queue_status("user-b")
                self.assertTrue(other_status["model_busy"])
                self.assertIsNone(other_status["active"])
                self.assertEqual("queued", other_status["status"])

                gate.set()
                for thread in (first, second_a, first_b):
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
        finally:
            capabilities.MODEL_QUEUE = old_queue

        self.assertEqual(["a1", "b1", "a2"], started)
        self.assertEqual(["user-a", "user-b", "user-a"], seen_actors)
        self.assertTrue(all(result["queue"]["lane_count"] == 1 for result in results.values()))


if __name__ == "__main__":
    unittest.main()
