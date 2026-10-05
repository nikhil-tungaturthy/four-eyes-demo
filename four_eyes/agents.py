"""The two agents, on the Cursor SDK's local runtime. Both are read-only, and both must submit
structured output through a custom tool that validates it. Then code cross-checks the dossier."""
import dataclasses
import json
import re

from cursor_sdk import Agent, AgentOptions, CustomTool, LocalAgentOptions
from pydantic import ValidationError

from .common import worktree
from .schemas import Dossier, IndependentAssessment, Verdict

READ_ONLY = ["read", "grep", "glob", "ls", "mcp"]   # no edit, shell, or web. "mcp" carries the custom submit tools.


def submit_tool(key, schema, sink):
    """A custom tool whose input schema is the pydantic model. Invalid submissions are rejected
    with the validation errors, so the agent can fix them and try again."""
    def execute(args, _context):
        try:
            sink[key] = schema.model_validate(args)
            return "Accepted."
        except ValidationError as err:
            return f"Rejected. Fix every error below and call the tool again.\n{err}"

    return CustomTool(description=f"Submit your final {key}.", input_schema=schema.model_json_schema(), execute=execute)


def converse(model, cwd, tools, steps, sink):
    """Send each (prompt, key) step to one agent, in order. A step must end with a valid submission
    under `key`; the agent gets one reminder, then we fail closed."""
    transcript, usage = [], []
    options = AgentOptions(model=model, tools=READ_ONLY, local=LocalAgentOptions(cwd=str(cwd), custom_tools=tools))
    with Agent.create(options) as agent:
        for prompt, key in steps:
            for message in (prompt, f"You have not submitted a valid {key}. Call the submit tool now."):
                run = agent.send(message)
                result = run.wait()
                transcript += json.loads(run.conversation_json() or "[]")
                usage.append(dataclasses.asdict(result.usage) if result.usage else {})
                if key in sink:
                    break
            if key not in sink:
                raise RuntimeError(f"Agent never submitted a valid {key}; failing closed")
    return transcript, {"model": model, "runs": usage}


def run_dossier(model, cwd, prompt):
    """The maker-side analyst: works in the PR's CI checkout with facts and diff in its prompt."""
    sink = {}
    tools = {"submit_dossier": submit_tool("dossier", Dossier, sink)}
    transcript, usage = converse(model, cwd, tools, [(prompt, "dossier")], sink)
    return sink["dossier"], transcript, usage


def run_checker(model, pr_number, head_sha, phase1, phase2):
    """The independent checker, on a different model. Phase 1 sees only the code, PR text, and diff,
    in a clean checkout with no facts or dossier. Phase 2 reveals them on the same conversation, so
    the transcript proves the independent assessment came first."""
    cwd = worktree(head_sha, f"pr-{pr_number}-checker")
    sink = {}
    tools = {"submit_independent_assessment": submit_tool("independent", IndependentAssessment, sink),
             "submit_verdict": submit_tool("verdict", Verdict, sink)}
    transcript, usage = converse(model, cwd, tools, [(phase1, "independent"), (phase2, "verdict")], sink)
    return sink["independent"], sink["verdict"], transcript, usage


def cross_checks(facts, dossier):
    """Code-level checks of the dossier's key assertions against the facts. No model involved."""
    findings = []

    def add(severity, detail):
        findings.append({"source": "cross_check", "severity": severity, "detail": detail})

    if any(p.get("closed_period_impact") for p in facts["impact_probe"]) and not dossier.closed_period_impact:
        add("blocking", "Facts show closed-period impact, but the dossier says there is none")
    if facts["sox_resources"] and not dossier.affected_reporting:
        add("blocking", "SOX-scoped resources are reached, but the dossier lists no affected reporting")
    if dossier.assessed_tier > facts["tier_floor"]["tier"]:
        add("advisory", f"Dossier assessed Tier {dossier.assessed_tier}, looser than the Tier "
                        f"{facts['tier_floor']['tier']} floor (the floor still applies)")

    facts_text = json.dumps(facts)
    amounts = re.findall(r"\d[\d,]*\.\d{2}(?!\d)", dossier.model_dump_json())   # e.g. 1,393.00
    unsourced = sorted({a for a in amounts if a.replace(",", "") not in facts_text})
    if unsourced:
        add("advisory", f"Amounts in the dossier that don't appear in the facts: {', '.join(unsourced[:5])}")
    return findings
