#!/usr/bin/env python3
"""Render/check plan attribution from NOTRIOS_IMPORT_EXECUTION.json (stdlib only)."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
FIELDS = (
    ("coding_agent", "Coding agent"),
    ("planned_worker", "Planned worker"),
    ("configured_model", "Planned configured model"),
    ("configured_reasoning_effort", "Planned reasoning effort"),
    ("assignment_confirmation", "Assignment confirmation"),
    ("actual_worker", "Actual worker"),
    ("child_thread", "Child thread"),
    ("actual_model", "Actual model"),
    ("reasoning_effort", "Reasoning effort"),
    ("worker_contribution", "Worker contribution"),
    ("parent", "Parent"),
    ("parent_underlying_model_family", "Parent underlying model family"),
    ("parent_reasoning_effort", "Parent reasoning effort"),
    ("parent_contribution", "Parent contribution"),
    ("validation", "Validation"),
    ("delegation_failure_or_reassignment", "Delegation failure or reassignment"),
    ("planned_assignment_evidence", "Planned assignment evidence"),
    ("evidence", "Execution evidence"),
    ("commit", "Commit"),
)


def cell(value):
    if isinstance(value, list):
        value = "; ".join(value) or "none"
    return str(value).replace("|", "&#124;").replace("\n", " ")


def section(text, name, content):
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"expected one marker pair for {name}")
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    return before + start + "\n" + content.rstrip() + "\n" + end + after


def render(text, ledger):
    rows = re.findall(r"^\| (\w+) / (Main|Luna|Terra)(?: — complete)? \|", text, re.M)
    slices = ledger["slices"]
    ids = [s["id"] for s in slices]
    if len(ids) != len(set(ids)) or {r[0] for r in rows} != set(ids):
        raise ValueError("slice coverage or duplicate-ID mismatch")
    aliases = {"Main": "parent", "Luna": "luna_worker", "Terra": "terra_worker"}
    planned = {s["id"]: s["planned_worker"] for s in slices}
    for ident, alias in rows:
        if planned[ident] != aliases[alias]:
            raise ValueError(f"planned owner drift for {ident}")
    for s in slices:
        for field, _ in FIELDS:
            if field not in s or s[field] == "":
                raise ValueError(f"missing attribution {s['id']}: {field}")
            if s["status"] == "complete" and s[field] == "pending":
                raise ValueError(f"incomplete execution record {s['id']}: {field}")
        if s["actual_worker"] == "none" and any(s[k] != "none" for k in
                ("child_thread", "actual_model", "reasoning_effort", "worker_contribution")):
            raise ValueError(f"inconsistent parent-only attribution {s['id']}")
    session = ledger["session"]
    assignment = [f"Session confirmation: **{cell(session['confirmation'])}**.", "",
                  cell(session["confirmation_evidence"]), "",
                  "| Coding agent | Execution owner | Configured model | Reasoning effort | Availability | Billing route |",
                  "|---|---|---|---|---|---|"]
    for a in ledger["assignments"]:
        assignment.append("| " + " | ".join(cell(a[k]) for k in
            ("coding_agent", "owner", "model", "reasoning_effort", "availability", "billing_route")) + " |")
    assignment += ["", f"Runtime-reported parent family: **{cell(session['underlying_model_family'])}**. "
                   f"Product/client version: {cell(session['product_client_version'])}; "
                   f"model provider: {cell(session['model_provider'])}.", ""]
    assignment.extend("- " + cell(note) for note in session["notes"])
    text = section(text, "NOTRIOS-ASSIGNMENTS", "\n".join(assignment))
    records = []
    for s in slices:
        records += [f"<details><summary>{s['id']} — {cell(s['status'])}; planned {cell(s['planned_worker'])}</summary>",
                    "", "| Property | Value |", "|---|---|"]
        records.extend(f"| {label} | {cell(s[key])} |" for key, label in FIELDS)
        records += ["", "</details>", ""]
    return section(text, "NOTRIOS-EXECUTION", "\n".join(records))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="refuse stale generated sections; write nothing")
    args = parser.parse_args()
    ledger = json.loads((ROOT / "NOTRIOS_IMPORT_EXECUTION.json").read_text(encoding="utf-8"))
    path = ROOT / ledger["plan"]
    text = path.read_text(encoding="utf-8")
    updated = render(text, ledger)
    if args.check:
        if updated != text:
            raise SystemExit("Plan attribution is stale; run python3 -B render_notrios_execution.py")
        print(f"Attribution current: {len(ledger['slices'])} slices; planned owners and actual records checked.")
    else:
        path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
