"""Smoke tests for skill-tax-cli (stdlib only, pytest or plain python).

Run:  python3 -m pytest tests/ -q   # or: python3 tests/test_smoke.py
"""

import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skill_tax_cli import budget, measure, sources  # noqa: E402
from skill_tax_cli.cli import main  # noqa: E402

SMALL = "---\nname: tiny\ndescription: Does a tiny thing.\n---\n# Tiny\nBody.\n"
BIG_DESC = "Does a very big thing. " * 40  # 1000 chars of description
BIG = "---\nname: huge\ndescription: >\n  %s\n---\n# Huge\n%s\n" % (BIG_DESC, "Body text. " * 500)


def _mk_skill(root, rel, content):
    d = os.path.join(root, rel)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w") as f:
        f.write(content)
    return d


def _fixture_home():
    """Fake $HOME: user skill + plugin skill + rules + memory + mcp config."""
    home = tempfile.mkdtemp()
    _mk_skill(home, os.path.join(".claude", "skills", "tiny"), SMALL)
    _mk_skill(home, os.path.join(".claude", "plugins", "acme", "skills", "huge"), BIG)
    with open(os.path.join(home, ".claude", "CLAUDE.md"), "w") as f:
        f.write("# Rules\n" * 100)
    with open(os.path.join(home, ".claude", "MEMORY.md"), "w") as f:
        f.write("")
    with open(os.path.join(home, ".claude.json"), "w") as f:
        json.dump({"mcpServers": {"gh": {"command": "npx", "args": ["-y", "srv"]}}}, f)
    cwd = tempfile.mkdtemp()
    _mk_skill(cwd, os.path.join(".claude", "skills", "proj"), SMALL.replace("tiny", "proj"))
    with open(os.path.join(cwd, ".mcp.json"), "w") as f:
        json.dump({"mcpServers": {"pg": {"command": "uvx", "args": ["pg-srv"]}}}, f)
    return home, cwd


def test_frontmatter_parse():
    fm = measure.parse_frontmatter(BIG)
    assert fm["name"] == "huge", fm
    assert fm["description"].startswith("Does a very big thing."), fm["description"][:40]
    assert "\n" not in fm["description"]  # folded `>` collapsed to one line
    assert measure.parse_frontmatter("no frontmatter here") == {}
    print("frontmatter_parse ok")


def test_listing_cost_math():
    info = measure.read_skill(__file__, "x")  # any file; recompute by hand below
    home, cwd = _fixture_home()
    skills = sources.discover_skills(home, cwd)
    tiny = [s for s in skills if s["name"] == "tiny"][0]
    # listing = name + 1 + description chars, tokens = round(chars/4)
    fm = measure.parse_frontmatter(SMALL)
    expect_chars = len("tiny") + 1 + len(fm["description"])
    assert tiny["listing_tokens"] == round(expect_chars / 4), tiny
    assert tiny["load_tokens"] == round(len(SMALL) / 4), tiny
    assert info["name"]  # read_skill works on arbitrary files
    print("listing_cost_math ok: tiny listing=%d load=%d"
          % (tiny["listing_tokens"], tiny["load_tokens"]))


def test_discovery_all_sources():
    home, cwd = _fixture_home()
    data = sources.discover_all(home, cwd)
    names = {s["name"]: s["source"] for s in data["skills"]}
    assert names == {"tiny": "user", "huge": "plugin:acme", "proj": "project"}, names
    assert len(data["rules"]) == 1 and data["rules"][0]["tokens"] > 0
    assert len(data["memory"]) == 1  # empty MEMORY.md -> 0 tokens, still listed
    mcp = {m["name"] for m in data["mcp"]}
    assert mcp == {"mcp:gh", "mcp:pg"}, mcp
    print("discovery_all_sources ok")


def test_discovery_missing_dirs():
    empty = tempfile.mkdtemp()
    data = sources.discover_all(home=empty, cwd=empty)
    assert all(v == [] for v in data.values()), data
    print("discovery_missing_dirs ok")


def test_audit_ranking_and_json(capsys=None):
    home, cwd = _fixture_home()
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = main(["audit", "--home", home, "--cwd", cwd, "--json",
                   "--sources", "skills"])
    finally:
        sys.stdout = old
    assert rc == 0
    payload = json.loads(buf.getvalue())
    names = [s["name"] for s in payload["skills"]]
    assert names[0] == "huge" and set(names) == {"tiny", "huge", "proj"}, names
    assert payload["totals"]["skills"] == 3
    assert payload["skills"][0]["load_pct_of_window"] > 0
    print("audit_ranking_and_json ok: order=%s" % names)


def test_budget_no_overflow():
    skills = [
        {"name": "a", "source": "user", "name_tokens": 2, "desc_tokens": 10},
        {"name": "b", "source": "user", "name_tokens": 2, "desc_tokens": 10},
    ]
    sim = budget.simulate(skills, budget_tokens=100, usage={"a": 5, "b": 3})
    assert sim["dropped"] == [] and len(sim["survivors"]) == 2, sim
    assert not sim["overflow"]
    print("budget_no_overflow ok")


def test_budget_least_used_first():
    skills = [
        {"name": "hot", "source": "user", "name_tokens": 1, "desc_tokens": 90},
        {"name": "cold", "source": "user", "name_tokens": 1, "desc_tokens": 90},
    ]
    # budget 100: names(2) + one desc(90) = 92 fits; least-used loses its desc
    sim = budget.simulate(skills, budget_tokens=100,
                          usage={"hot": 50, "cold": 1})
    assert [s["name"] for s in sim["dropped"]] == ["cold"], sim
    assert [s["name"] for s in sim["survivors"]] == ["hot"], sim
    print("budget_least_used_first ok")


def test_budget_tiebreak_deterministic():
    skills = [
        {"name": "b-big", "source": "user", "name_tokens": 1, "desc_tokens": 80},
        {"name": "a-big", "source": "user", "name_tokens": 1, "desc_tokens": 80},
        {"name": "c-small", "source": "user", "name_tokens": 1, "desc_tokens": 10},
    ]
    # equal usage (none given): drop biggest desc first; name breaks the tie
    sim = budget.simulate(skills, budget_tokens=50, usage={})
    assert [s["name"] for s in sim["dropped"]] == ["a-big", "b-big"], sim
    # re-run: identical result (deterministic)
    sim2 = budget.simulate(skills, budget_tokens=50, usage={})
    assert [s["name"] for s in sim2["dropped"]] == ["a-big", "b-big"]
    print("budget_tiebreak_deterministic ok")


def test_gate_exit_codes():
    home, cwd = _fixture_home()
    usage = os.path.join(tempfile.mkdtemp(), "usage.json")
    with open(usage, "w") as f:
        json.dump({"tiny": 100, "huge": 1, "proj": 100}, f)
    # generous budget -> clean -> exit 0
    assert main(["gate", "--home", home, "--cwd", cwd,
                 "--budget-tokens", "10000000"]) == 0
    # tiny budget -> silent drops -> exit 1
    assert main(["gate", "--home", home, "--cwd", cwd,
                 "--budget-tokens", "10", "--usage", usage]) == 1
    # missing usage file -> exit 2
    assert main(["gate", "--home", home, "--cwd", cwd,
                 "--usage", "/nope/missing.json"]) == 2
    # malformed usage file -> exit 2
    bad = os.path.join(tempfile.mkdtemp(), "bad.json")
    with open(bad, "w") as f:
        f.write("[1,2]")
    assert main(["gate", "--home", home, "--cwd", cwd, "--usage", bad]) == 2
    print("gate_exit_codes ok")


def test_silent_drop_names_survive():
    """Names are never dropped -- only descriptions are stripped."""
    skills = [{"name": "solo", "source": "user",
               "name_tokens": 2, "desc_tokens": 500}]
    sim = budget.simulate(skills, budget_tokens=10, usage={})
    assert [s["name"] for s in sim["dropped"]] == ["solo"]
    # even after dropping every description, the names still cost budget
    assert sim["names_tokens"] == 2
    print("silent_drop_names_survive ok")


def _run_all():
    test_frontmatter_parse()
    test_listing_cost_math()
    test_discovery_all_sources()
    test_discovery_missing_dirs()
    test_audit_ranking_and_json()
    test_budget_no_overflow()
    test_budget_least_used_first()
    test_budget_tiebreak_deterministic()
    test_gate_exit_codes()
    test_silent_drop_names_survive()
    print("ALL SMOKE TESTS PASSED (10/10)")


if __name__ == "__main__":
    _run_all()
