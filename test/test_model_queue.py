import threading
import time
import unittest

from bob_core.model_queue import FairModelQueue


class ModelQueueTests(unittest.TestCase):
    def test_single_lane_alternates_users_without_overlap(self):
        queue = FairModelQueue()
        gate = threading.Event()
        started = []
        results = {}
        running = 0
        peak = 0
        lock = threading.Lock()

        def launch(user_id, label, blocked=False):
            def operation():
                nonlocal running, peak
                with lock:
                    started.append(label)
                    running += 1
                    peak = max(peak, running)
                if blocked:
                    gate.wait(5)
                with lock:
                    running -= 1
                return {"label": label}

            result = queue.run(actor_user_id=user_id, workspace_id=label, request_id=label, tool="model.chat", operation=operation)
            results[label] = result

        first = threading.Thread(target=launch, args=("user-a", "a1", True))
        first.start()
        while started != ["a1"]:
            time.sleep(0.005)
        threads = [
            threading.Thread(target=launch, args=("user-a", "a2")),
            threading.Thread(target=launch, args=("user-b", "b1")),
            threading.Thread(target=launch, args=("user-a", "a3")),
        ]
        for thread in threads:
            thread.start()
            time.sleep(0.01)
        gate.set()
        for thread in [first, *threads]:
            thread.join(5)
            self.assertFalse(thread.is_alive())

        self.assertEqual(["a1", "b1", "a2", "a3"], started)
        self.assertEqual(1, peak)
        self.assertTrue(all(result["queue"]["lane_count"] == 1 for result in results.values()))

    def test_status_filters_other_users_job_details(self):
        queue = FairModelQueue()
        gate = threading.Event()
        thread = threading.Thread(target=lambda: queue.run(actor_user_id="user-a", workspace_id="private-a", request_id="req-a", tool="model.plan", operation=lambda: gate.wait(5)))
        thread.start()
        for _ in range(100):
            if queue.snapshot("user-b")["model_busy"]:
                break
            time.sleep(0.005)
        status = queue.snapshot("user-b")
        self.assertTrue(status["model_busy"])
        self.assertIsNone(status["active"])
        self.assertEqual([], status["waiting"])
        gate.set()
        thread.join(5)


if __name__ == "__main__":
    unittest.main()
