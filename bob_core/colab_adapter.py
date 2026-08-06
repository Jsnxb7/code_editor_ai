"""Configurable HTTP adapter for the notebook's Colab pipeline contract."""

from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from typing import Any

from bob_core.model_config import read_model_config
from bob_core.contracts import CodeContract, PlanContract, ReviewContract, Usage


class ColabRetryError(RuntimeError):
    """Transient Colab failure after the configured retry budget is exhausted."""

    def __init__(self, message: str, attempts: list[dict[str, Any]]):
        super().__init__(message)
        self.attempts = attempts
        self.dlq = True

PLAN_DEFAULTS = {
    "task_type": "",
    "summary": "",
    "confidence": 0.0,
    "output_mode": "ready_for_coder",
    "need_workspace_scan": False,
    "need_file_contents": False,
    "need_documentation": False,
    "investigation_points": [],
    "possible_causes": [],
    "required_context": [],
    "files_needed": [],
    "documentation_needed": [],
    "tool_calls": [],
    "reasoning_steps": [],
    "coder_prompt": "",
}


def normalize_plan(raw: dict | None) -> dict:
    plan = {**PLAN_DEFAULTS, **(raw or {})}
    plan["confidence"] = float(plan.get("confidence") or 0)
    for key in (
        "investigation_points",
        "possible_causes",
        "required_context",
        "files_needed",
        "documentation_needed",
        "tool_calls",
        "reasoning_steps",
    ):
        plan[key] = list(plan.get(key) or [])
    return PlanContract.model_validate(plan).model_dump()


def parse_coder_output(output: str, expected_files: list[str] | None = None) -> dict[str, str]:
    pattern = r'(?:(?:\#+\s*`([^`]+)`)|(?:FILE:\s*`?([^`\n]+)`?))?\s*```(\w+)?\s*\n(.*?)```'
    matches = list(re.finditer(pattern, output or "", re.DOTALL))
    files: dict[str, str] = {}
    unnamed = []
    for match in matches:
        path = (match.group(1) or match.group(2) or "").strip()
        block = {"lang": match.group(3), "content": match.group(4).strip(), "start": match.start()}
        if path:
            files[path] = block["content"]
        else:
            unnamed.append(block)
    expected = [path for path in (expected_files or []) if path not in files]
    ext_map = {
        "python": ".py", "html": ".html", "css": ".css", "javascript": ".js",
        "json": ".json", "xml": ".xml", "yaml": ".yml", "markdown": ".md",
        "bash": ".sh", "shell": ".sh", "sql": ".sql",
    }
    for index, block in enumerate(unnamed):
        if index < len(expected):
            path = expected[index]
        else:
            lang = (block["lang"] or "txt").lower()
            ext = ext_map.get(lang, f".{lang}")
            path = "app" + ext if len(matches) == 1 else f"file_{index + 1}{ext}"
        files[path] = block["content"]
    return files


class ColabAdapter:
    def __init__(self):
        config = read_model_config(include_secret=True)
        self.base_url = config.get("base_url", "").rstrip("/")
        self.health_path = config.get("health_path", "/health")
        self.capabilities_path = config.get("capabilities_path", "/capabilities")
        self.chat_path = config.get("chat_path", "/chat")
        self.plan_path = config.get("plan_path", "/plan")
        self.replan_path = config.get("replan_path", "/replan")
        self.code_path = config.get("code_path", "/code")
        self.review_path = config.get("review_path", "/review")
        self.run_path = config.get("run_path", "/run-agent")
        self.stream_path = config.get("stream_path", "/run-agent/stream")
        self.timeout = int(config.get("timeout", 600))
        self.max_iterations = int(config.get("max_iterations", 5))
        self.context_mode = config.get("context_mode", "workspace")
        self.context_budget = int(config.get("context_budget", 160000))
        self.keep_model_loaded = bool(config.get("keep_model_loaded", True))
        self.prefer_streaming = bool(config.get("prefer_streaming", True))
        self.token = config.get("token", "")
        self.prompt_set_version = config.get("prompt_set_version", "unversioned")
        self.model_id = config.get("model_id", "unknown")
        self.model_revision = config.get("model_revision", "unknown")
        self.input_price = float(config.get("input_token_price_per_million", 0) or 0)
        self.output_price = float(config.get("output_token_price_per_million", 0) or 0)
        try:
            self.extra_headers = json.loads(config.get("headers_json", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("Model headers JSON must be valid JSON") from exc

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _request(self, request: urllib.request.Request, timeout: int) -> dict:
        attempts: list[dict[str, Any]] = []
        deadline = time.monotonic() + max(1, timeout)
        for attempt in range(1, 4):
            started = time.monotonic()
            try:
                remaining = max(1, int(deadline - started))
                with urllib.request.urlopen(request, timeout=remaining) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("Colab response must be a JSON object")
                body["runtime_attempt_count"] = int(body.get("attempt_count") or 1)
                body["attempt_count"] = attempt
                return self._with_usage(body)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                attempts.append({"attempt": attempt, "status": exc.code, "duration_ms": round((time.monotonic() - started) * 1000), "error": detail})
                if not retryable:
                    raise RuntimeError(f"Colab returned HTTP {exc.code}: {detail}") from exc
                last_error: Exception = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                attempts.append({"attempt": attempt, "status": None, "duration_ms": round((time.monotonic() - started) * 1000), "error": str(exc)[:500]})
                last_error = exc
            if attempt < 3 and time.monotonic() < deadline:
                time.sleep(min(0.25 * (2 ** (attempt - 1)) + random.uniform(0, 0.15), max(0, deadline - time.monotonic())))
        raise ColabRetryError(f"Colab request failed after 3 attempts: {last_error}", attempts) from last_error

    def _with_usage(self, body: dict) -> dict:
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        normalized = Usage.model_validate({"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens)}).model_dump()
        cost = (input_tokens * self.input_price + output_tokens * self.output_price) / 1_000_000 if (self.input_price or self.output_price) else None
        return {**body, "provider": body.get("provider", "colab"), "model": body.get("model", self.model_id), "model_revision": body.get("model_revision", self.model_revision), "prompt_version": body.get("prompt_version", self.prompt_set_version), "usage": normalized, "estimated_cost_usd": cost}

    def _post(self, path: str, payload: dict) -> dict:
        if not self.configured:
            raise RuntimeError("Colab model endpoint is not configured")
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._request(request, self.timeout)

    def _get(self, path: str) -> dict:
        if not self.configured:
            raise RuntimeError("Colab model endpoint is not configured")
        headers = {**self.extra_headers}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(f"{self.base_url}{path}", headers=headers, method="GET")
        return self._request(request, min(self.timeout, 20))

    def health(self) -> dict:
        return self._get(self.health_path)

    def capabilities(self) -> dict:
        return self._get(self.capabilities_path)

    def chat(self, payload: dict) -> dict:
        return self._post(self.chat_path, payload)

    def plan(self, payload: dict) -> dict:
        if not self.configured:
            return normalize_plan({
                "task_type": "configuration required",
                "summary": "Connect the Colab planner endpoint to generate a model plan.",
                "confidence": 0,
                "output_mode": "request_docs",
                "documentation_needed": ["BOB_COLAB_BASE_URL"],
            })
        body = self._post(self.plan_path, payload)
        plan = normalize_plan(body.get("plan", body))
        for key in ("attempt_count", "provider", "model", "model_revision", "prompt_version", "usage", "estimated_cost_usd"):
            if key in body:
                plan[key] = body[key]
        return plan

    def replan(self, payload: dict) -> dict:
        if not self.configured:
            return self.plan(payload)
        body = self._post(self.replan_path, payload)
        return {**body, "plan": normalize_plan(body.get("plan", body))}

    def code(self, payload: dict) -> dict:
        if not self.configured:
            raise RuntimeError("Colab model endpoint is not configured")
        body = self._post(self.code_path, payload)
        plan = normalize_plan(body.get("plan") or payload.get("selected_plan") or payload.get("plan"))
        code = str(body.get("code") or "")
        files = body.get("files")
        if not isinstance(files, dict):
            files = parse_coder_output(code, plan.get("files_needed"))
        validated = CodeContract.model_validate({**body, "plan": plan, "code": code, "files": files}).model_dump()
        return {**body, **validated}

    def review(self, payload: dict) -> dict:
        if not self.configured:
            raise RuntimeError("Colab model endpoint is not configured")
        body = self._post(self.review_path, payload)
        review = str(body.get("review") or "")
        final_status = str(body.get("final_status") or "").upper()
        if final_status not in {"PASS", "FAIL"}:
            final_status = "PASS" if review.lstrip().upper().startswith("PASS") else "FAIL"
        validated = ReviewContract.model_validate({**body, "review": review, "final_status": final_status}).model_dump()
        return {**body, **validated}

    def run_agent(self, payload: dict) -> dict:
        if not self.configured:
            return {
                "provider": "local_contract_stub",
                "plan": normalize_plan({
                    "task_type": "configuration required",
                    "summary": "No Colab model endpoint is configured.",
                    "confidence": 0,
                    "output_mode": "request_docs",
                    "documentation_needed": ["BOB_COLAB_BASE_URL"],
                }),
                "code": "",
                "review": "FAIL\nColab model endpoint is not configured.",
                "final_status": "FAIL",
                "files": {},
            }
        body = self._post(self.run_path, {
            **payload,
            "max_iterations": payload.get("max_iterations", self.max_iterations),
            "context_mode": payload.get("context_mode", self.context_mode),
            "context_budget": payload.get("context_budget", self.context_budget),
            "keep_model_loaded": payload.get("keep_model_loaded", self.keep_model_loaded),
        })
        plan = normalize_plan(body.get("plan"))
        code = str(body.get("code") or "")
        files = body.get("files")
        if not isinstance(files, dict):
            files = parse_coder_output(code, plan.get("files_needed"))
        final_status = str(body.get("final_status") or "").upper()
        review = str(body.get("review") or "")
        if final_status not in {"PASS", "FAIL"}:
            final_status = "PASS" if review.lstrip().upper().startswith("PASS") else "FAIL"
        code_validated = CodeContract.model_validate({**body, "plan": plan, "code": code, "files": files}).model_dump()
        review_validated = ReviewContract.model_validate({**body, "review": review, "final_status": final_status}).model_dump()
        return {**body, **code_validated, **review_validated}

    def run_agent_stream(self, payload: dict, on_event) -> dict:
        if not self.prefer_streaming:
            return self.run_agent(payload)
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream", **self.extra_headers}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.base_url}{self.stream_path}",
            data=json.dumps({
                **payload,
                "max_iterations": payload.get("max_iterations", self.max_iterations),
                "context_mode": payload.get("context_mode", self.context_mode),
                "context_budget": payload.get("context_budget", self.context_budget),
                "keep_model_loaded": payload.get("keep_model_loaded", self.keep_model_loaded),
            }).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        final = None
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    on_event(event)
                    if event.get("result"):
                        final = event["result"]
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 405, 415}:
                return self.run_agent(payload)
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Colab stream returned HTTP {exc.code}: {detail}") from exc
        if not isinstance(final, dict):
            raise RuntimeError("Colab stream ended without a final result")
        plan = normalize_plan(final.get("plan"))
        code = str(final.get("code") or "")
        files = final.get("files")
        if not isinstance(files, dict):
            files = parse_coder_output(code, plan.get("files_needed"))
        review = str(final.get("review") or "")
        final_status = str(final.get("final_status") or "").upper()
        if final_status not in {"PASS", "FAIL"}:
            final_status = "PASS" if review.lstrip().upper().startswith("PASS") else "FAIL"
        return {**final, "plan": plan, "code": code, "files": files, "review": review, "final_status": final_status}
