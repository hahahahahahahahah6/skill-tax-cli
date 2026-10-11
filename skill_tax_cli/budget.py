"""Listing-budget simulation and silent-drop detection.

Claude Code injects every skill's name + description into context on every
turn. The listing's budget defaults to 1% of the model's context window
(`skillListingBudgetFraction`, default 0.01). When the listing overflows,
Claude Code drops *descriptions* starting with the skills you invoke least;
names always survive. A description-less skill keeps nothing for the model
to match a request against, so it quietly stops being chosen -- with no
warning in the UI (only a `--debug` log line).

This module replays that rule deterministically so CI can catch it.
"""

from __future__ import annotations


def default_budget_tokens(window: int, fraction: float = 0.01) -> int:
    return int(window * fraction)


def _drop_order(skills: list[dict], usage: dict) -> list[dict]:
    """Deterministic drop order: least-used first.

    usage maps skill name -> invocation count. Skills missing from usage are
    treated as never used (0). Ties break by larger listing cost first, then
    by name -- fully deterministic without usage data.
    """
    return sorted(
        skills,
        key=lambda s: (usage.get(s["name"], 0), -s["desc_tokens"], s["name"]),
    )


def simulate(skills: list[dict], budget_tokens: int, usage: dict | None = None) -> dict:
    """Replay the listing-budget overflow rule.

    Returns {dropped, survivors, budget_tokens, listing_tokens,
    dropped_tokens, names_tokens}. `dropped` are the skills whose
    descriptions Claude Code would silently strip; `survivors` keep theirs.
    Names are never dropped (they always stay in the listing).
    """
    usage = usage or {}
    order = _drop_order(skills, usage)
    names_tokens = sum(s["name_tokens"] for s in skills)
    desc_tokens = sum(s["desc_tokens"] for s in skills)
    total = names_tokens + desc_tokens

    dropped: list[dict] = []
    idx = 0
    while total > budget_tokens and idx < len(order):
        victim = order[idx]
        dropped.append(victim)
        total -= victim["desc_tokens"]
        idx += 1
    survivors = order[idx:]
    return {
        "dropped": dropped,
        "survivors": survivors,
        "budget_tokens": budget_tokens,
        "listing_tokens": names_tokens + desc_tokens,
        "dropped_tokens": sum(s["desc_tokens"] for s in dropped),
        "names_tokens": names_tokens,
        "overflow": total > budget_tokens,
    }


def load_usage(path: str | None) -> dict:
    """Load {skill_name: invocation_count} JSON. Missing path -> {}."""
    if not path:
        return {}
    import json
    import os

    if not os.path.isfile(path):
        raise FileNotFoundError("usage file not found: %s" % path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("usage file must be a JSON object, got %s" % type(data))
    return {str(k): int(v) for k, v in data.items()}
