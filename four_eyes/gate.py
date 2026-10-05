"""The merge decision. Deterministic code, no model calls. Nothing an agent writes can turn it green."""
import re


def makers_of(pr, commits):
    """The PR author plus everyone who authored or committed to the PR. GitHub's own web-flow
    committer and bots are skipped; a bot's commits count against the PR author, already a maker."""
    makers = {pr["user"]["login"]}
    for commit in commits:
        for role in ("author", "committer"):
            login = (commit.get(role) or {}).get("login")
            if login and login != "web-flow" and not login.endswith("[bot]"):
                makers.add(login)
    return makers


def evaluate(summary, policy, pr, reviews, commits):
    """Check the conditions in order and stop at the first one that isn't met."""
    head = pr["head"]["sha"]

    def result(state, description, approvals=(), not_counted=()):
        return {"state": state, "description": description, "approvals": list(approvals), "not_counted": sorted(not_counted)}

    if not summary or summary["head_sha"] != head:
        return result("failure", "No evidence for the current head commit")
    if not summary["ci_ok"]:
        return result("failure", "dbt CI did not pass for the head commit")
    tier = summary["tier"]
    if tier <= 2 and not re.search(policy["ticket_regex"], pr["body"] or ""):
        return result("failure", f"Tier {tier} change needs a change ticket in the PR description")
    if summary["verdict"] != "concur" or summary["blocking"]:
        return result("failure", f"Checker verdict {summary['verdict']} with {summary['blocking']} blocking finding(s)")

    latest = {}   # each reviewer's most recent decisive review wins
    for review in sorted(reviews, key=lambda r: r["submitted_at"] or ""):
        if review["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[review["user"]["login"]] = review
    approved = {login for login, r in latest.items() if r["state"] == "APPROVED" and r["commit_id"] == head}
    makers = makers_of(pr, commits)
    eligible = approved - makers   # nobody approves their own change

    approvals, used = [], set()    # each requirement must be met by different people
    for req in policy["tiers"][tier]["approvals"]:
        people = sorted(u for u in eligible - used if u in policy["groups"][req["group"]])[: req["min"]]
        used.update(people)
        approvals.append({"group": req["group"], "min": req["min"], "approvers": people, "met": len(people) >= req["min"]})

    missing = [a["group"] for a in approvals if not a["met"]]
    if missing:
        return result("pending", f"Tier {tier}: waiting on {', '.join(missing)}", approvals, approved & makers)
    return result("success", f"Tier {tier}: evidence, checker, and approvals satisfied", approvals, approved & makers)
