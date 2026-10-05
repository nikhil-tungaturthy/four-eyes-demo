"""Four Eyes command line.

  four-eyes prod                      build main into the production schema
  four-eyes evidence --pr N           facts -> dossier agent -> checker agent -> evidence bundle -> gate
  four-eyes evidence --pr N --selftest hide_intent_mismatch
  four-eyes gate --pr N [--watch]     evaluate the merge gate and post the four-eyes/gate status
  four-eyes reconcile                 prove every production commit came through an approved PR
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time

import yaml
from dotenv import load_dotenv

from . import agents, facts, gate, report
from .common import EVIDENCE, PROD, REPO, ROOT, dbt, from_main, gh, git, read_json, worktree, write_json

PROMPTS = ("dossier", "checker_phase1", "checker_phase2")

# Self-tests corrupt the dossier on purpose, before the checker sees it, to prove the control catches it.
SELFTESTS = {
    # only the checker can catch this one: code can't judge intent
    "hide_intent_mismatch": lambda d: d.model_copy(update={
        "intent_alignment": "aligned",
        "intent_notes": "The change matches the ticket, the business justification, and the stated effective date."}),
    # code catches this one on its own (agents.cross_checks)
    "flip_closed_period": lambda d: d.model_copy(update={"closed_period_impact": False}),
}


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(prog="four-eyes")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prod")
    p = commands.add_parser("evidence")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--selftest", choices=sorted(SELFTESTS))
    p = commands.add_parser("gate")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--watch", action="store_true", help="re-evaluate every 15 seconds")
    commands.add_parser("reconcile")
    args = parser.parse_args()

    git("fetch", "--quiet", "--tags", "origin")   # always judge against the current main
    {"prod": prod, "evidence": evidence, "gate": gate_command, "reconcile": reconcile}[args.command](args)


# ---------------------------------------------------------------- prod

def prod(_args):
    """Stand-in for the dbt platform production job: build exactly what's on main into the prod schema."""
    sha = git("rev-parse", "origin/main")
    PROD.mkdir(parents=True, exist_ok=True)
    if not dbt("build", "--target", "prod", "--target-path", str(PROD), cwd=worktree(sha, "prod")):
        sys.exit("Production build failed")
    (PROD / "git_sha.txt").write_text(sha)
    print(f"Production built from main @ {sha[:7]}")


# ---------------------------------------------------------------- evidence

def evidence(args):
    pr = gh(f"{REPO}/pulls/{args.pr}")
    try:
        out = build_evidence(pr, args.selftest)
    except Exception:
        if not args.selftest:   # a broken pipeline must never read as a pass
            set_status(pr["head"]["sha"], "failure", "Evidence generation failed")
        raise

    if args.selftest:
        summary = read_json(out / "summary.json")
        caught = summary["verdict"] == "dispute" or summary["blocking"] > 0
        set_status(pr["head"]["sha"], "success" if caught else "failure",
                   f"Fault {'caught' if caught else 'NOT caught'}", context=f"four-eyes/selftest/{args.selftest}")
        print(f"Self-test {args.selftest}: {'caught' if caught else 'NOT CAUGHT'} · evidence in {out}")
    else:
        run_gate(args.pr)


def build_evidence(pr, selftest=None):
    number, head = pr["number"], pr["head"]["sha"]
    out = EVIDENCE / f"pr-{number}" / (head[:12] + (f"-selftest-{selftest}" if selftest else ""))
    shutil.rmtree(out, ignore_errors=True)   # evidence is all-or-nothing: never mix files from two runs
    policy_text = from_main("controls/policy.yml")
    policy = yaml.safe_load(policy_text)
    prompts = {name: from_main(f"controls/prompts/{name}.md") for name in PROMPTS}
    dossier_model, checker_model = os.environ["DOSSIER_MODEL"], os.environ["CHECKER_MODEL"]

    print(f"[1/4] dbt CI build and facts for PR #{number} @ {head[:7]}")
    git("fetch", "--quiet", "origin", f"pull/{number}/head")
    ci_dir, ci_ok = facts.run_ci(number, head)
    fx = facts.collect(pr, ci_dir, ci_ok, policy, {"policy.yml": policy_text, **prompts}, out)
    print(f"      tier floor {fx['tier_floor']['tier']}: {', '.join(f['rule'] for f in fx['tier_floor']['fired']) or 'default'}")

    pr_text = f"## PR title\n{pr['title']}\n\n## PR description\n{pr['body'] or ''}"
    diff = (out / "pr.diff").read_text()
    facts_json = json.dumps(fx, indent=2)

    print(f"[2/4] Dossier agent ({dossier_model})")
    dossier_prompt = "\n\n".join([prompts["dossier"], pr_text, fenced("facts.json", facts_json), fenced("Diff", diff)])
    dossier, dossier_transcript, dossier_usage = agents.run_dossier(dossier_model, ci_dir, dossier_prompt)
    if selftest:
        dossier = SELFTESTS[selftest](dossier)

    print(f"[3/4] Checker agent ({checker_model}): independent assessment, then adjudication")
    phase1 = "\n\n".join([prompts["checker_phase1"], pr_text, fenced("Diff", diff)])
    phase2 = "\n\n".join([prompts["checker_phase2"], fenced("Dossier", dossier.model_dump_json(indent=2)), fenced("facts.json", facts_json)])
    independent, verdict, checker_transcript, checker_usage = agents.run_checker(checker_model, number, head, phase1, phase2)

    print("[4/4] Cross-checks and evidence bundle")
    findings = agents.cross_checks(fx, dossier) + [
        {"source": "checker", **f.model_dump()} for f in verdict.findings if f.severity != "none"]
    tier = min(fx["tier_floor"]["tier"], dossier.assessed_tier, verdict.recommended_tier)   # strictest wins
    summary = {
        "pr": number, "head_sha": head, "head_tree": fx["pr"]["head_tree"], "ci_ok": ci_ok,
        "tier": tier, "tier_label": policy["tiers"][tier]["label"],
        "verdict": verdict.verdict, "blocking": sum(f["severity"] == "blocking" for f in findings),
        "models": {"dossier": dossier_model, "checker": checker_model},
        "selftest": selftest,
    }
    for name, data in {
        "dossier.json": dossier.model_dump(), "independent.json": independent.model_dump(),
        "verdict.json": verdict.model_dump(), "findings.json": findings, "summary.json": summary,
        "transcripts/dossier.json": dossier_transcript, "transcripts/checker.json": checker_transcript,
        "usage.json": {"dossier": dossier_usage, "checker": checker_usage},
    }.items():
        write_json(out / name, data)
    seal(out)
    print(f"      tier {tier} · checker {verdict.verdict} · {summary['blocking']} blocking · bundle {bundle_sha(out)[:16]}")
    return out


def fenced(title, text):
    return f"## {title}\n```\n{text}\n```"


def seal(out):
    """Hash every file into BUNDLE.sha256 (verify with `shasum -a 256 -c BUNDLE.sha256`)."""
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "BUNDLE.sha256")
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out)}" for p in files]
    (out / "BUNDLE.sha256").write_text("\n".join(lines) + "\n")


def bundle_sha(out):
    return hashlib.sha256((out / "BUNDLE.sha256").read_bytes()).hexdigest()


# ---------------------------------------------------------------- gate

def gate_command(args):
    last = None
    while True:
        last = run_gate(args.pr, previous=last)
        if not args.watch:
            return
        time.sleep(15)


def run_gate(number, previous=None):
    """Evaluate the gate with main's policy and the PR's current reviews and commits, then publish
    the four-eyes/gate status and refresh the PR comment."""
    policy = yaml.safe_load(from_main("controls/policy.yml"))
    pr = gh(f"{REPO}/pulls/{number}")
    reviews = gh(f"{REPO}/pulls/{number}/reviews?per_page=100")
    commits = gh(f"{REPO}/pulls/{number}/commits?per_page=100")
    out = EVIDENCE / f"pr-{number}" / pr["head"]["sha"][:12]
    summary = read_json(out / "summary.json") if (out / "BUNDLE.sha256").exists() else None

    result = gate.evaluate(summary, policy, pr, reviews, commits)
    if result == previous:   # --watch: only publish when something changed
        return result

    set_status(pr["head"]["sha"], result["state"], result["description"])
    if summary:
        body = report.render(result, summary, read_json(out / "facts.json"), read_json(out / "dossier.json"),
                             read_json(out / "verdict.json"), read_json(out / "findings.json"), bundle_sha(out))
    else:
        body = report.render(result)
    upsert_comment(number, body)
    print(f"four-eyes/gate → {result['state']}: {result['description']}")
    return result


def set_status(sha, state, description, context="four-eyes/gate"):
    gh(f"{REPO}/statuses/{sha}", "POST", {"state": state, "context": context, "description": description[:140]})


def upsert_comment(number, body):
    comments = gh(f"{REPO}/issues/{number}/comments?per_page=100")
    ours = next((c for c in comments if report.MARKER in c["body"]), None)
    if ours:
        gh(f"{REPO}/issues/comments/{ours['id']}", "PATCH", {"body": body})
    else:
        gh(f"{REPO}/issues/{number}/comments", "POST", {"body": body})


# ---------------------------------------------------------------- reconcile

def reconcile(_args):
    """Deployment integrity: every commit in the production build must map to a merged PR whose gate
    was green, whose evidence exists, and whose approved tree is exactly the tree that merged."""
    prod_sha = (PROD / "git_sha.txt").read_text().strip()
    rows = []
    for sha in git("rev-list", "--first-parent", f"four-eyes-baseline..{prod_sha}").split():
        merged = [p for p in gh(f"{REPO}/commits/{sha}/pulls") if p["merged_at"]]
        if not merged:
            rows.append({"commit": sha[:7], "pr": None, "problems": ["no PR: pushed straight to main"]})
            continue
        pr, problems = merged[0], []
        head = pr["head"]["sha"]
        statuses = gh(f"{REPO}/commits/{head}/status")["statuses"]
        if not any(s["context"] == "four-eyes/gate" and s["state"] == "success" for s in statuses):
            problems.append("four-eyes/gate was not green on the approved head")
        if gh(f"{REPO}/git/commits/{head}")["tree"]["sha"] != git("rev-parse", f"{sha}^{{tree}}"):
            problems.append("merged tree differs from the approved tree")
        if not (EVIDENCE / f"pr-{pr['number']}" / head[:12] / "BUNDLE.sha256").exists():
            problems.append("no evidence bundle for the approved head")
        rows.append({"commit": sha[:7], "pr": pr["number"], "problems": problems})

    print(f"Production @ {prod_sha[:7]}: {len(rows)} commit(s) since the baseline")
    for row in rows:
        status = "ok" if not row["problems"] else "EXCEPTION: " + "; ".join(row["problems"])
        print(f"  {row['commit']}  PR #{row['pr'] or '-'}  {status}")
    write_json(EVIDENCE / "reconcile.json", {"prod_sha": prod_sha, "commits": rows})
    if any(row["problems"] for row in rows):
        sys.exit(1)
