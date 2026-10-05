"""The shapes the agents must submit. Pydantic validates every submission; invalid output is rejected."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Tier = Literal[1, 2, 3]  # 1 is high risk


class Claim(BaseModel):
    id: str = Field(pattern=r"^C\d+$")
    statement: str
    evidence: list[str] = Field(min_length=1, description='Pointers like "facts.tier_floor" or "diff:path/to/file.sql"')


class Dossier(BaseModel):
    summary: str = Field(description="Two or three plain sentences: what the logic did before, what it does now")
    intent_alignment: Literal["aligned", "partially_aligned", "misaligned", "unclear"]
    intent_notes: str = Field(description="One to three sentences. Lead with any mismatch")
    financial_impact: str = Field(description="One to three sentences, citing facts.impact_probe")
    closed_period_impact: bool = Field(description="True if any period on or before facts.closed_through changes")
    affected_reporting: list[str] = Field(description="Names of affected exposures and SOX-scoped models")
    related_logic_not_changed: list[str] = Field(max_length=3, description="Sibling logic the PR may have missed, one sentence each")
    testing_assessment: str = Field(description="One to three sentences")
    test_gaps: list[str] = Field(max_length=3, description="The most important gaps, one sentence each")
    assessed_tier: Tier
    tier_rationale: str = Field(description="One or two sentences")
    backout_plan: str = Field(description="Two to four sentences: what to revert and what to rebuild")
    approver_questions: list[str] = Field(max_length=4, description="One sentence each")
    claims: list[Claim] = Field(min_length=3, max_length=10)


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
    detail: str = Field(description="One or two sentences")


class Verdict(BaseModel):
    verdict: Literal["concur", "dispute"]
    recommended_tier: Tier
    findings: list[Finding]
    summary: str
