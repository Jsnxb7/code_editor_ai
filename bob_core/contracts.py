"""Validated external model contracts used at the Colab boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtensibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Usage(ExtensibleModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class PlanContract(ExtensibleModel):
    task_type: str = ""
    summary: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    output_mode: str = "ready_for_coder"
    need_workspace_scan: bool = False
    need_file_contents: bool = False
    need_documentation: bool = False
    investigation_points: list[Any] = Field(default_factory=list)
    possible_causes: list[Any] = Field(default_factory=list)
    required_context: list[Any] = Field(default_factory=list)
    files_needed: list[Any] = Field(default_factory=list)
    documentation_needed: list[Any] = Field(default_factory=list)
    tool_calls: list[Any] = Field(default_factory=list)
    reasoning_steps: list[Any] = Field(default_factory=list)
    coder_prompt: str = ""


class CodeContract(ExtensibleModel):
    code: str = ""
    files: dict[str, str | None] = Field(default_factory=dict)
    plan: PlanContract = Field(default_factory=PlanContract)
    usage: Usage = Field(default_factory=Usage)


class ReviewContract(ExtensibleModel):
    review: str = ""
    final_status: Literal["PASS", "FAIL"] = "FAIL"
    usage: Usage = Field(default_factory=Usage)

    @field_validator("final_status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> str:
        return str(value or "FAIL").upper()


class ErrorContract(ExtensibleModel):
    type: str
    component: str
    message: str
    retriable: bool = False
    attempts: list[dict[str, Any]] = Field(default_factory=list)


class DlqContract(ExtensibleModel):
    id: str
    status: Literal["open", "in_review", "corrected", "resolved_evaluation_created", "dismissed"] = "open"
    owner_user_id: str | None = None
    workspace_id: str | None = None
    run_id: str | None = None
    request_id: str | None = None
    prompt: str = ""
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorContract | None = None


class CorrectionContract(ExtensibleModel):
    id: str
    original_prompt: str
    corrected_prompt: str
    expected_behavior: str
    root_cause: str
    severity: str
    tags: list[str] = Field(default_factory=list)
    author_user_id: str


class EvaluationScoresContract(ExtensibleModel):
    correctness: int = Field(ge=1, le=5)
    helpfulness: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    groundedness: int = Field(ge=1, le=5)


class EvaluationRevisionContract(ExtensibleModel):
    scores: EvaluationScoresContract
    verdict: Literal["acceptable", "needs_correction", "invalid_failure"]
    failure_category: str
    severity: str
    notes: str
    expected_behavior: str


class EvaluationContract(ExtensibleModel):
    id: str
    source_type: str
    source_id: str | None = None
    status: Literal["pending", "completed"]
    revisions: list[EvaluationRevisionContract] = Field(default_factory=list)
