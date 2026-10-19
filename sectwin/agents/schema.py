"""Structured output contract between the Assessor, the verifier and the critic."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ..conf.security import SECURITY_PARAMS

Verdict = Literal["violation", "compliant", "needs_profile"]
Level = Literal["shall", "shall_not", "should", "may", "optional", "none"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameter: str
    line: Optional[int] = None
    value: Union[str, list[str], None] = None
    verdict: Verdict
    clause_id: str
    quote: str
    normative_level: Level
    reason: str = ""
    fix_value: Union[str, list[str], None] = Field(
        default=None, description="New value for the parameter that resolves the violation")
    # filled by the pipeline, never by the model
    status: Literal["confirmed", "unverified", "unchecked"] = "unchecked"


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessed_parameters: list[str]
    findings: list[Finding]
    overall: Literal["compliant", "non_compliant"]


class CriticIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["MissedViolation", "ScopeError", "WrongVerdict", "BadFix"]
    parameter: str
    clause_id: str = ""
    quote: str = ""
    explanation: str


class CriticOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issues: list[CriticIssue]


class Queries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[str]


def _strip(schema: dict) -> dict:
    """Ollama structured-output schema: drop pipeline-only fields."""
    s = Assessment.model_json_schema()
    f = s["$defs"]["Finding"]
    f["properties"].pop("status", None)
    f["required"] = [r for r in f.get("required", []) if r != "status"] + ["reason", "fix_value", "line", "value"]
    return s


ASSESSMENT_SCHEMA = _strip({})
CRITIC_SCHEMA = CriticOutput.model_json_schema()
QUERIES_SCHEMA = Queries.model_json_schema()
PARAM_SET = set(SECURITY_PARAMS)
