"""Configurable HTTP adapter for the notebook's Colab pipeline contract."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from bob_core.model_config import read_model_config

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
    return plan


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
        try:
            self.extra_headers = json.loads(config.get("headers_json", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("Model headers JSON must be valid JSON") from exc

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Colab returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Could not reach Colab: {exc}") from exc
        if not isinstance(body, dict):
            raise ValueError("Colab response must be a JSON object")
        return body

    def _get(self, path: str) -> dict:
        if not self.configured:
            raise RuntimeError("Colab model endpoint is not configured")
        headers = {**self.extra_headers}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(f"{self.base_url}{path}", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 20)) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Could not reach Colab: {exc}") from exc
        if not isinstance(body, dict):
            raise ValueError("Colab response must be a JSON object")
        return body

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
        return normalize_plan(body.get("plan", body))

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
        return {**body, "plan": plan, "code": code, "files": files}

    def review(self, payload: dict) -> dict:
        if not self.configured:
            raise RuntimeError("Colab model endpoint is not configured")
        body = self._post(self.review_path, payload)
        review = str(body.get("review") or "")
        final_status = str(body.get("final_status") or "").upper()
        if final_status not in {"PASS", "FAIL"}:
            final_status = "PASS" if review.lstrip().upper().startswith("PASS") else "FAIL"
        return {**body, "review": review, "final_status": final_status}

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
        return {**body, "plan": plan, "code": code, "files": files, "review": review, "final_status": final_status}

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
