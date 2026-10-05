"""Deterministic facts for one PR. Nothing in this file calls a model.

Anything an approver or auditor sees as a fact (lineage, SOX scope, test results, dollar deltas,
the tier floor) is computed here. The agents interpret these facts; they never produce them.
"""
import hashlib
import re
import shutil

import duckdb

from .common import DUCKDB, PROD, dbt, git, read_json, worktree, write_json

TRACKED = {"model", "seed", "snapshot"}


def run_ci(pr_number, head_sha):
    """Local stand-in for the dbt platform CI job: build what the PR changed, plus everything
    downstream, into its own schema. Unchanged parents are read from production (--defer)."""
    ci_dir = worktree(head_sha, f"pr-{pr_number}-ci")
    ok = dbt("build", "--select", "state:modified+", "--defer", "--state", str(PROD),
             "--target", "ci", cwd=ci_dir, schema=f"pr_{pr_number}")
    return ci_dir, ok


def collect(pr, ci_dir, ci_ok, policy, controls, out):
    """Compare the PR's CI build with production and write facts.json plus the raw artifacts to `out`."""
    head = pr["head"]["sha"]
    pr_m = read_json(ci_dir / "target/manifest.json")
    prod_m = read_json(PROD / "manifest.json")
    run_results = read_json(ci_dir / "target/run_results.json")

    diff = git("diff", f"origin/main...{head}")
    changed_files = git("diff", "--name-only", f"origin/main...{head}").splitlines()
    changes, changed_tests = classify(pr_m, prod_m)
    logic = [uid for uid, kinds in changes.items() if kinds != ["docs"]]   # docs-only changes can't move numbers
    impacted = downstream(pr_m, logic) | downstream(prod_m, logic)         # prod graph covers removed nodes
    everything = {**resources(prod_m), **resources(pr_m)}
    sox = sorted(uid for uid in impacted | set(logic) if is_sox(everything[uid]))
    probes = impact_probe(policy, pr_m, prod_m, run_results)

    facts = {
        "pr": {
            "number": pr["number"], "url": pr["html_url"], "title": pr["title"], "author": pr["user"]["login"],
            "head_sha": head, "head_tree": git("rev-parse", f"{head}^{{tree}}"),
            "ticket_refs": [m.group(0) for m in re.finditer(policy["ticket_regex"], pr["body"] or "")],
        },
        "closed_through": policy["closed_through"],
        "ci": ci_summary(run_results, pr_m, prod_m, ci_ok, schema=f"pr_{pr['number']}"),
        "changed_files": changed_files,
        "changes": changes,
        "changed_tests": changed_tests,
        "downstream": sorted(impacted),
        "sox_resources": sox,
        "impact_probe": probes,
        "tier_floor": tier_floor(policy, changed_files, changes, changed_tests, logic, sox, probes, everything),
        "controls_sha256": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in controls.items()},
    }

    (out / "ci").mkdir(parents=True, exist_ok=True)
    (out / "pr.diff").write_text(diff)
    shutil.copy(ci_dir / "target/manifest.json", out / "ci/manifest.pr.json")
    shutil.copy(PROD / "manifest.json", out / "ci/manifest.prod.json")
    shutil.copy(ci_dir / "target/run_results.json", out / "ci/run_results.json")
    write_json(out / "facts.json", facts)
    return facts


def classify(pr_m, prod_m):
    """Mark each model, seed, or snapshot as new, removed, or modified (body, config, contract, docs, macro)."""
    changes = {}
    for uid, node in pr_m["nodes"].items():
        if node["resource_type"] not in TRACKED:
            continue
        before = prod_m["nodes"].get(uid)
        if before is None:
            changes[uid] = ["new"]
            continue
        kinds = []
        if node["checksum"] != before["checksum"]:
            kinds.append("body")
        if node["unrendered_config"] != before["unrendered_config"]:
            kinds.append("config")
        if node.get("contract") != before.get("contract"):   # seeds have no contract
            kinds.append("contract")
        if not kinds and docs(node) != docs(before):
            kinds.append("docs")
        if kinds:
            changes[uid] = kinds

    for uid, node in prod_m["nodes"].items():
        if node["resource_type"] in TRACKED and uid not in pr_m["nodes"]:
            changes[uid] = ["removed"]

    changed_macros = {uid for uid, m in pr_m["macros"].items()
                      if m["macro_sql"] != prod_m["macros"].get(uid, {}).get("macro_sql")}
    for uid, node in pr_m["nodes"].items():
        if node["resource_type"] in TRACKED and changed_macros & set(node["depends_on"]["macros"]):
            changes.setdefault(uid, []).append("macro")

    tests_before = {**prod_m["nodes"], **prod_m["unit_tests"]}
    changed_tests = sorted(uid for uid, t in {**pr_m["nodes"], **pr_m["unit_tests"]}.items()
                           if t["resource_type"] in ("test", "unit_test")
                           and (uid not in tests_before or t["checksum"] != tests_before[uid]["checksum"]))
    return changes, changed_tests


def docs(node):
    return node["description"], {name: col["description"] for name, col in node["columns"].items()}


def resources(manifest):
    return {**manifest["nodes"], **manifest["exposures"], **manifest["metrics"]}


def downstream(manifest, start):
    """Everything that depends on `start`, directly or indirectly."""
    children = {}
    for uid, res in resources(manifest).items():
        for parent in res.get("depends_on", {}).get("nodes", []):
            children.setdefault(parent, set()).add(uid)
    seen, stack = set(), list(start)
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in seen and not child.startswith("test."):
                seen.add(child)
                stack.append(child)
    return seen


def is_sox(resource):
    """Models carry config.meta.sox_scope: true; exposures carry config.meta.sox: true."""
    meta = {**resource.get("meta", {}), **resource.get("config", {}).get("meta", {})}
    return bool(meta.get("sox_scope") or meta.get("sox"))


def impact_probe(policy, pr_m, prod_m, run_results):
    """For each probed table the CI run rebuilt, compare the measure by key: CI schema vs production.
    Only aggregates are computed, and only here; the agents never touch the warehouse."""
    built = {r["unique_id"] for r in run_results["results"] if r["status"] == "success"}
    out = []
    with duckdb.connect(str(DUCKDB), read_only=True) as con:
        for probe in policy["impact_probes"]:
            uid = next(u for u, n in pr_m["nodes"].items() if n["resource_type"] == "model" and n["name"] == probe["model"])
            if uid not in built:
                out.append({"model": probe["model"], "measure": probe["measure"], "rebuilt_in_ci": False})
                continue

            keys = ", ".join(probe["keys"])
            totals = {}
            for side, manifest in (("prod", prod_m), ("ci", pr_m)):
                relation = manifest["nodes"][uid]["relation_name"]   # e.g. "warehouse"."pr_2"."fct_net_transaction_revenue"
                rows = con.execute(f"select {keys}, sum({probe['measure']}) from {relation} group by {keys}").fetchall()
                totals[side] = {tuple(str(v) for v in row[:-1]): row[-1] for row in rows}

            deltas, by_period = [], {}
            for key in sorted(totals["prod"].keys() | totals["ci"].keys()):
                delta = totals["ci"].get(key, 0) - totals["prod"].get(key, 0)
                if delta:
                    row = dict(zip(probe["keys"], key))
                    deltas.append({**row, "delta": f"{delta:.2f}"})
                    by_period[row[probe["period"]]] = by_period.get(row[probe["period"]], 0) + delta

            out.append({
                "model": probe["model"], "measure": probe["measure"], "rebuilt_in_ci": True,
                "closed_period_impact": any(period <= policy["closed_through"] for period in by_period),
                "by_period": {period: f"{d:.2f}" for period, d in by_period.items()},   # money as 2-decimal strings
                "deltas": deltas,
            })
    return out


def ci_summary(run_results, pr_m, prod_m, ok, schema):
    results = run_results["results"]
    data_tests = [r for r in results if r["unique_id"].startswith("test.")]
    unit_tests = [r for r in results if r["unique_id"].startswith("unit_test.")]
    return {
        "ok": ok,
        "schema": schema,
        "models_built": sorted(name(r["unique_id"]) for r in results if r["unique_id"].startswith("model.")),
        "data_tests": {"pass": sum(r["status"] == "pass" for r in data_tests),
                       "fail": sum(r["status"] != "pass" for r in data_tests)},
        "unit_tests": [{"name": name(r["unique_id"]), "status": r["status"],
                        "modified_in_pr": pr_m["unit_tests"][r["unique_id"]]["checksum"]
                        != prod_m["unit_tests"].get(r["unique_id"], {}).get("checksum")} for r in unit_tests],
        "failures": [name(r["unique_id"]) for r in results if r["status"] in ("error", "fail")],
    }


def tier_floor(policy, changed_files, changes, changed_tests, logic, sox, probes, everything):
    """Code sets the floor. Every rule that fires is recorded with a reason; the strictest tier wins."""
    fired = []

    def fire(rule, tier, why):
        fired.append({"rule": rule, "tier": tier, "why": why})

    control = [f for f in changed_files if f.startswith(tuple(policy["control_plane_paths"]))]
    if control:
        fire("control_plane_change", 1, f"changes {', '.join(control)}")
    if sox:
        fire("sox_logic_change", 1, f"{names(logic)} reaches {names(sox)}")
    closed = [p for p in probes if p.get("closed_period_impact")]
    if closed:
        fire("closed_period_impact", 1, f"{closed[0]['measure']} changes on or before {policy['closed_through']}")
    finance = [uid for uid in logic if everything[uid].get("original_file_path", "").startswith(policy["finance_path"])]
    if finance and not sox:
        fire("finance_logic_change", 2, names(finance))
    if not logic and not control and (changes or changed_tests):
        fire("docs_or_tests_only", 3, "no logic, config, or contract changes")

    tier = min((f["tier"] for f in fired), default=policy["default_tier"])
    return {"tier": tier, "label": policy["tiers"][tier]["label"], "fired": fired}


def name(uid):
    return uid.split(".")[-1]


def names(uids):
    return ", ".join(name(u) for u in uids)
