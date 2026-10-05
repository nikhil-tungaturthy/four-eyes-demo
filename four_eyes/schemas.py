"""The shapes the agents must submit. Pydantic validates every submission; invalid output is rejected."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Tier = Literal[1, 2, 3]  # 1 is high risk


class Claim(BaseModel):
    id: str = Field(pattern=r"^C\d+$")
    statement: str
    evidence: list[str] = Field(min_length=1, description='Pointers like "facts.tier_floor" or "diff:path/to/file.sql"')


class Dossier(BaseModel):
    summary: str = Field(description="What the logic did before and what it does now, in plain language")
    intent_alignment: Literal["aligned", "partially_aligned", "misaligned", "unclear"]
    intent_notes: str
    financial_impact: str
    closed_period_impact: bool = Field(description="True if any period on or before facts.closed_through changes")
    affected_reporting: list[str] = Field(description="Names of affected exposures and SOX-scoped models")
    related_logic_not_changed: list[str] = Field(description="Sibling logic the PR may have missed")
    testing_assessment: str
    test_gaps: list[str]
    assessed_tier: Tier
    tier_rationale: str
    backout_plan: str
    approver_questions: list[str]
    claims: list[Claim] = Field(min_length=3)


class IndependentAssessment(BaseModel):
    what_changed: str
    affected_models: list[str]
    affected_exposures: list[str]
    sox_scope_reached: bool
    past_periods_change: bool
    covering_tests: list[str]
    recommended_tier: Tier
    notes: str


class Finding(BaseModel):
    claim_id: Optional[str] = Field(default=None, description="Dossier claim id, or null for an omission")
    assessment: Literal["verified", "contradicted", "unverifiable", "omission"]
    severity: Literal["blocking", "advisory", "none"] = Field(description="none for verified claims")
    detail: str


class Verdict(BaseModel):
    verdict: Literal["concur", "dispute"]
    recommended_tier: Tier
    findings: list[Finding]
    summary: str
