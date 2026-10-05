# Four Eyes

AI-prepared, AI-challenged, human-approved change control for the dbt projects behind financial statements.

On every pull request:

1. **Code gathers the facts.** It builds the change, then computes lineage, SOX scope, test results, and dollar impact by period. These are computed, never generated.
2. **An agent writes the dossier.** A Cursor SDK agent explains the change for approvers and checks the PR's stated intent against what the code actually does.
3. **A second agent challenges it.** It runs on a different model family. It first assesses the change on its own, then tries to falsify the dossier claim by claim.
4. **A deterministic gate decides.** It enforces tiered approvals and separation of duties, and posts a `four-eyes/gate` status that branch protection requires.

Every run leaves a hashed evidence bundle, so an auditor sampling a change gets the full story from one folder.

All data is synthetic: a fictional exchange's transaction-revenue project.

## How it works

```
PR opened (template: ticket, justification, effective date, expected impact)
   │
   ▼
four-eyes evidence --pr N
   1. dbt CI        dbt build --select state:modified+ --defer   → schema pr_N in DuckDB      facts.py
   2. Facts         diff, changed nodes, lineage, SOX scope, prod-vs-PR deltas, tier floor  facts.py
   3. Dossier       Cursor SDK agent, model A, read-only tools, submit_dossier tool        agents.py
   4. Checker       model B, clean checkout: phase 1 alone, phase 2 sees dossier + facts   agents.py
   5. Cross-checks  code compares the dossier's key claims with the facts                  agents.py
   6. Bundle        every file hashed into BUNDLE.sha256                                    cli.py
   │
   ▼
four-eyes gate --pr N   (also runs at the end of evidence; use --watch during a demo)
   evidence for this head? CI passed? ticket? checker concurs? approvals meet the tier?
   approvers aren't makers? a different person for each requirement?                      gate.py
   → commit status four-eyes/gate + one PR comment                                          report.py
   │
   ▼
merge → four-eyes prod (builds main) → four-eyes reconcile
   every production commit maps to a merged PR with a green gate, evidence, and the same tree
```

## The rule that keeps the AI honest

The agents prepare and challenge evidence. The control itself is deterministic code plus human approval.

| Mechanism | Where |
|---|---|
| Code sets the tier floor. An agent can make the tier stricter but never looser. | `facts.tier_floor`, `min(...)` in `cli.build_evidence` |
| Invalid agent output is rejected, and no valid submission means the run fails closed. | `agents.submit_tool`, `agents.converse` |
| A checker dispute or any blocking finding blocks the merge. | `gate.evaluate` |
| Code cross-checks the dossier's key claims against the facts. | `agents.cross_checks` |
| Policy and prompts always come from `main`, never from the PR being judged. | `common.from_main` |
| Agents are read-only: no edit, shell, web, or warehouse access. | `agents.READ_ONLY` |
| Approvals from anyone who pushed to the PR don't count. | `gate.makers_of` |

## Repo tour

```
four_eyes/            the control (about 600 lines of Python)
  cli.py              commands: prod, evidence, gate, reconcile; evidence bundle; PR comment + status
  common.py           paths, and thin wrappers around git, gh, and dbt
  facts.py            deterministic facts: CI build, change classification, lineage, impact probe, tier floor
  agents.py           dossier agent, two-phase checker, cross-checks (Cursor SDK)
  schemas.py          pydantic shapes the agents must submit
  gate.py             the merge decision
  report.py           renders the PR comment
controls/             the rules, always read from main
  policy.yml          closed period, ticket regex, impact probes, tiers, approver groups
  prompts/            dossier.md, checker_phase1.md, checker_phase2.md
models/ seeds/ tests/ the dbt project: exchange transaction revenue (maker-taker fees and rebates)
.github/              PR template (makes intent checkable) and CODEOWNERS (routes reviews)
```

The dbt lineage:

```
raw_executions → stg_executions → int_member_monthly_volume (rebate tier rule)
                        │                   │
raw_fee_schedule → stg_fee_schedule → int_executions_priced → fct_execution_fees ┬→ fct_member_monthly_billing → member_invoicing_feed (SOX)
                        │                                                         └→ fct_net_transaction_revenue → quarterly_revenue_disclosure (SOX)
                        └→ fct_member_activity → member_activity_dashboard (not SOX)
```

## Running it

Prerequisites: macOS with Homebrew, `gh auth login`, and a Cursor API key in `.env` (see `.env.example`). dbt runs locally on DuckDB, so you don't need warehouse credentials.

```bash
uv sync                                # Python 3.12, dbt-core + dbt-duckdb, cursor-sdk
uv run four-eyes prod                  # build main into the prod schema (stand-in for the production job)
uv run four-eyes evidence --pr 2       # facts → dossier → checker → bundle → gate (about 5 minutes)
uv run four-eyes gate --pr 2 --watch   # re-evaluate as approvals come in
uv run four-eyes evidence --pr 2 --selftest drop_sox_exposure   # prove the control catches a bad dossier
uv run four-eyes reconcile             # after merging and rebuilding prod
```

Evidence lands in `evidence/pr-N/<head-sha>/`. To verify a bundle, run `shasum -a 256 -c BUNDLE.sha256` from inside its folder.

The demo scenes, the seed generator, and the presenter runbook live outside this repo, in `../demo-kit/`. Keeping them out means the agents can't read the answers.

## SOX change-control attributes

| Attribute | How Four Eyes evidences it |
|---|---|
| Authorized | PR template with change ticket; the gate requires a ticket for Tier 1 and 2 |
| Assessed for impact | Code-computed tier floor, the dossier, and the checker's independent challenge |
| Tested | dbt build and tests for the exact head commit, plus a period-level revenue impact probe |
| Approved by someone else | Tier-based approval policy enforced by the gate; makers' approvals don't count |
| Deployed as approved | `reconcile` maps every production commit to a gated PR with an identical tree |
| Documented | Hashed evidence bundle per head commit, including both agents' full transcripts |

## What this demo simplifies

| Demo | Production |
|---|---|
| dbt builds locally on DuckDB. `four-eyes prod` stands in for the production job | dbt platform CI job with compare changes, and the Admin API for run artifacts |
| You run the commands from your laptop. Statuses post under your GitHub login | A GitHub Actions or GitLab CI workflow under a bot identity, with branch protection pinned to that app |
| Agents read the repo and get facts in their prompt | They also get the dbt MCP server in Discovery-only mode for production health and lineage |
| Evidence is a local folder | Write-once storage (e.g. S3 Object Lock), keyed by repo, PR, and head commit |
| Approver groups live in `policy.yml` | Groups synced from your identity provider |
