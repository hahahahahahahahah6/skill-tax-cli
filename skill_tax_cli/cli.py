"""skill-tax-cli: audit the context tax of your Claude Code skills."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .budget import default_budget_tokens, load_usage, simulate
from .measure import rel_home
from .sources import discover_all

KINDS = ("skills", "rules", "memory", "mcp")


def _parse_kinds(value: str) -> tuple:
    kinds = tuple(k.strip() for k in value.split(",") if k.strip())
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        raise ValueError("unknown source kind(s): %s (choose from %s)"
                         % (", ".join(unknown), ", ".join(KINDS)))
    return kinds or KINDS


def cmd_list(args) -> int:
    data = discover_all(home=args.home, cwd=args.cwd,
                        kinds=_parse_kinds(args.sources))
    skills = data.get("skills", [])
    rows = [{
        "name": s["name"],
        "source": s["source"],
        "path": rel_home(s["path"]),
        "listing_tokens": s["listing_tokens"],
        "load_tokens": s["load_tokens"],
    } for s in sorted(skills, key=lambda s: s["name"])]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print("%-28s %-18s %5d listing / %6d load tokens  %s"
                  % (r["name"], r["source"], r["listing_tokens"],
                     r["load_tokens"], r["path"]))
        print("%d skill(s)" % len(rows))
    return 0


def _fmt_pct(part: int, whole: int) -> str:
    return "%.1f%%" % (100.0 * part / whole) if whole else "n/a"


def cmd_audit(args) -> int:
    kinds = _parse_kinds(args.sources)
    data = discover_all(home=args.home, cwd=args.cwd, kinds=kinds)
    skills = sorted(data.get("skills", []),
                    key=lambda s: s["load_tokens"], reverse=True)
    window = args.window

    payload = {
        "window": window,
        "skills": [{
            "name": s["name"],
            "source": s["source"],
            "path": rel_home(s["path"]),
            "listing_tokens": s["listing_tokens"],
            "load_tokens": s["load_tokens"],
            "load_pct_of_window": round(100.0 * s["load_tokens"] / window, 2),
        } for s in skills],
        "totals": {},
    }
    total_load = sum(s["load_tokens"] for s in skills)
    total_listing = sum(s["listing_tokens"] for s in skills)
    payload["totals"] = {
        "skills": len(skills),
        "load_tokens": total_load,
        "listing_tokens": total_listing,
        "load_pct_of_window": round(100.0 * total_load / window, 2),
    }
    for kind in ("rules", "memory", "mcp"):
        entries = data.get(kind, [])
        payload[kind] = [{
            "name": e["name"],
            "tokens": e["tokens"],
            "path": rel_home(e.get("path", "")),
        } for e in entries]
        payload["totals"][kind + "_tokens"] = sum(e["tokens"] for e in entries)

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("skill                          source        listing    load  load%%window")
    print("---------------------------  --------------  -------  ------  ----------")
    for s in payload["skills"]:
        print("%-27s  %-14s  %7d  %6d  %9.2f%%"
              % (s["name"][:27], s["source"][:14], s["listing_tokens"],
                 s["load_tokens"], s["load_pct_of_window"]))
    print("---------------------------  --------------  -------  ------  ----------")
    print("TOTAL (%d skills)                              %7d  %6d  %9.2f%%"
          % (len(skills), total_listing, total_load,
             payload["totals"]["load_pct_of_window"]))
    for kind in ("rules", "memory", "mcp"):
        entries = data.get(kind, [])
        if entries:
            print("\n[%s] always-on static cost:" % kind)
            for e in entries:
                print("  %-40s %6d tokens  %s"
                      % (e["name"][:40], e["tokens"], rel_home(e.get("path", ""))))
            print("  subtotal: %d tokens (%s of %d window)"
                  % (payload["totals"][kind + "_tokens"],
                     _fmt_pct(payload["totals"][kind + "_tokens"], window), window))
    return 0


def cmd_gate(args) -> int:
    """CI gate: exit 1 if any skill would be silently dropped from the listing.

    Exit codes: 0 = clean, 1 = silent drops detected, 2 = config/usage error.
    """
    try:
        usage = load_usage(args.usage)
    except (FileNotFoundError, ValueError) as exc:
        print("skill-tax-cli gate: %s" % exc, file=sys.stderr)
        return 2
    skills = discover_all(home=args.home, cwd=args.cwd,
                          kinds=("skills",)).get("skills", [])
    budget = (args.budget_tokens if args.budget_tokens is not None
              else default_budget_tokens(args.window, args.budget_pct))
    sim = simulate(skills, budget, usage)
    result = {
        "budget_tokens": budget,
        "window": args.window,
        "skills": len(skills),
        "listing_tokens": sim["listing_tokens"],
        "dropped": [{"name": s["name"], "source": s["source"],
                     "desc_tokens": s["desc_tokens"],
                     "usage": usage.get(s["name"], 0)} for s in sim["dropped"]],
        "clean": not sim["dropped"],
    }
    if args.json:
        print(json.dumps(result, indent=2))
    elif sim["dropped"]:
        print("SILENT-DROP RISK: %d of %d skill(s) exceed the %d-token listing "
              "budget (%d tokens used):" % (
                  len(sim["dropped"]), len(skills), budget, sim["listing_tokens"]))
        for d in result["dropped"]:
            print("  - %s [%s] desc ~%d tokens, usage=%d -> description would be "
                  "silently stripped" % (
                      d["name"], d["source"], d["desc_tokens"], d["usage"]))
        print("Trim descriptions, raise skillListingBudgetFraction, or remove "
              "unused skills.")
    else:
        print("OK: %d skill(s), listing ~%d tokens within %d-token budget."
              % (len(skills), sim["listing_tokens"], budget))
    return 0 if result["clean"] else 1


def _add_common(sp):
    sp.add_argument("--home", default=None,
                    help="override $HOME for skill discovery (testing)")
    sp.add_argument("--cwd", default=None,
                    help="override cwd for project-scope discovery (testing)")
    sp.add_argument("--json", action="store_true", help="machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="skill-tax-cli",
        description="Audit the context tax of your Claude Code skills: "
                    "rank load costs, simulate the listing budget, and fail CI "
                    "when skills would be silently dropped.")
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)

    sub = ap.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list all discovered skills")
    p_list.add_argument("--sources", default="skills",
                        help="comma-separated subset of: " + ",".join(KINDS))
    _add_common(p_list)
    p_list.set_defaults(func=cmd_list)

    p_audit = sub.add_parser("audit", help="rank skills by context cost")
    p_audit.add_argument("--window", type=int, default=200000,
                         help="model context window in tokens (default 200000)")
    p_audit.add_argument("--sources", default=",".join(KINDS),
                         help="comma-separated subset of: " + ",".join(KINDS))
    _add_common(p_audit)
    p_audit.set_defaults(func=cmd_audit)

    p_gate = sub.add_parser("gate", help="CI gate: fail if the listing overflows")
    p_gate.add_argument("--window", type=int, default=200000)
    p_gate.add_argument("--budget-pct", type=float, default=0.01,
                        help="listing budget fraction of window (default 0.01)")
    p_gate.add_argument("--budget-tokens", type=int, default=None,
                        help="explicit listing budget in tokens (overrides --budget-pct)")
    p_gate.add_argument("--usage", default=None, metavar="FILE",
                        help="JSON {skill_name: invocation_count} for drop order")
    _add_common(p_gate)
    p_gate.set_defaults(func=cmd_gate)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print("skill-tax-cli: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
