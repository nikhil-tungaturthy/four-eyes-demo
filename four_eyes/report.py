"""Renders the one PR comment approvers read, from the evidence bundle plus the latest gate result."""
from decimal import Decimal

MARKER = "<!-- four-eyes -->"   # how we find our own comment to update it
HEADLINE = {"success": "✅ ready to merge", "pending": "⏳ waiting on approvals", "failure": "❌ blocked"}


def render(gate, summary=None, facts=None, dossier=None, verdict=None, findings=(), bundle_sha=""):
    if summary is None:
        return f"### Four Eyes · {HEADLINE['failure']}\n\n{gate['description']}. Run `four-eyes evidence`.\n\n{MARKER}"

    lines = [
        f"### Four Eyes · Tier {summary['tier']} ({summary['tier_label']}) · {HEADLINE[gate['state']]}",
        f"**Gate:** {gate['description']}",
        "",
        f"**What changed:** {dossier['summary']}",
        "",
        f"**Intent check:** {dossier['intent_alignment'].replace('_', ' ')}. {dossier['intent_notes']}",
        "",
    ]

    for probe in facts["impact_probe"]:
        if not probe["rebuilt_in_ci"]:
            lines.append(f"**Financial impact:** none. {probe['model']} was not rebuilt by this change.")
        elif not probe["by_period"]:
            lines.append(f"**Financial impact:** {probe['model']} rebuilt with no change to {probe['measure']}.")
        else:
            periods = " · ".join(f"{p[:7]} {Decimal(d):+,.2f}" for p, d in sorted(probe["by_period"].items()))
            lines.append(f"**Financial impact** ({probe['measure']}, PR build vs production): {periods}")
            if probe["closed_period_impact"]:
                lines.append(f"⚠️ Periods are closed through {facts['closed_through']}, so this **restates closed periods**.")
    lines.append("")

    sox = ", ".join(f"`{uid.split('.')[-1]}`" for uid in facts["sox_resources"] if uid.startswith("exposure.")) or "none"
    floor = " · ".join(f"`{f['rule']}` ({f['why']})" for f in facts["tier_floor"]["fired"]) or "default"
    lines += [f"**SOX reporting affected:** {sox}", f"**Tier floor (code):** {floor}", ""]

    ci = facts["ci"]
    units = ", ".join(f"`{u['name']}` {u['status']}" + (" (edited in this PR)" if u["modified_in_pr"] else "")
                      for u in ci["unit_tests"]) or "none ran"
    lines += [
        f"**Testing:** dbt CI {'passed' if ci['ok'] else '**failed**'} in schema `{ci['schema']}` · "
        f"data tests {ci['data_tests']['pass']} passed, {ci['data_tests']['fail']} failed · unit tests: {units}",
        *[f"- Gap: {gap}" for gap in dossier["test_gaps"]],
        "",
    ]

    blocking = [f for f in findings if f["severity"] == "blocking"]
    advisory = [f for f in findings if f["severity"] == "advisory"]
    lines += [
        f"**Checker** ({summary['models']['checker']}, assessed independently before seeing the dossier): "
        f"{verdict['verdict']} · {len(blocking)} blocking · {len(advisory)} advisory",
        *[f"- {f['severity']}: {f['detail']}" for f in blocking + advisory],
        "",
    ]

    if gate["approvals"]:
        checks = " · ".join(f"{a['group']} {'✓ ' + ', '.join(a['approvers']) if a['met'] else '✗'}" for a in gate["approvals"])
        lines.append(f"**Approvals for Tier {summary['tier']}:** {checks}")
    if gate["not_counted"]:
        lines.append(f"**Not counted:** {', '.join(gate['not_counted'])} (pushed commits to this PR, so they're a maker)")

    lines += [
        "",
        "<details><summary>Approver questions, backout plan, and claims</summary>",
        "",
        "**Questions for approvers**",
        *[f"- {q}" for q in dossier["approver_questions"]],
        "",
        f"**Backout plan:** {dossier['backout_plan']}",
        "",
        "**Claims the checker tried to falsify**",
        *[f"- {c['id']}: {c['statement']}" for c in dossier["claims"]],
        "</details>",
        "",
        f"<sub>Evidence bundle sha256 `{bundle_sha[:16]}` · head `{summary['head_sha'][:7]}` · "
        f"dossier {summary['models']['dossier']} · checker {summary['models']['checker']}</sub>",
        MARKER,
    ]
    return "\n".join(lines)
