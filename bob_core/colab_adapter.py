"""Configurable HTTP adapter for the notebook's Colab pipeline contract."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

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
        self.base_url = os.getenv("BOB_COLAB_BASE_URL", "").rstrip("/")
        self.plan_path = os.getenv("BOB_COLAB_PLAN_PATH", "/plan")
        self.run_path = os.getenv("BOB_COLAB_RUN_PATH", "/run-agent")
        self.timeout = int(os.getenv("BOB_COLAB_TIMEOUT", "600"))
        self.token = os.getenv("BOB_COLAB_TOKEN", "")
        try:
            self.extra_headers = json.loads(os.getenv("BOB_COLAB_HEADERS_JSON", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("BOB_COLAB_HEADERS_JSON must be valid JSON") from exc

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
        body = self._post(self.run_path, payload)
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

