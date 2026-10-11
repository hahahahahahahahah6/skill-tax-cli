"""Discover always-on context sources: skills, rules, memory, MCP configs."""

from __future__ import annotations

import json
import os

from .measure import file_cost, read_skill

SKILL_FILE = "SKILL.md"


def _skill_dirs(root: str, source: str) -> list[dict]:
    """Find <dir>/SKILL.md directly under root (root/<skill>/SKILL.md)."""
    found = []
    if not os.path.isdir(root):
        return found
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in entries:
        skill_md = os.path.join(root, entry, SKILL_FILE)
        if os.path.isfile(skill_md):
            info = read_skill(skill_md, default_name=entry)
            info["source"] = source
            found.append(info)
    return found


def discover_skills(home: str | None = None, cwd: str | None = None) -> list[dict]:
    """All skills from user, project, and plugin-marketplace locations.

    - user:    ~/.claude/skills/<skill>/SKILL.md
    - project: ./.claude/skills/<skill>/SKILL.md (cwd)
    - plugin:  ~/.claude/plugins/<plugin>/skills/<skill>/SKILL.md
    """
    home = home or os.path.expanduser("~")
    cwd = cwd or os.getcwd()
    skills: list[dict] = []
    skills += _skill_dirs(os.path.join(home, ".claude", "skills"), "user")
    skills += _skill_dirs(os.path.join(cwd, ".claude", "skills"), "project")

    plugins_root = os.path.join(home, ".claude", "plugins")
    if os.path.isdir(plugins_root):
        try:
            plugins = sorted(os.listdir(plugins_root))
        except OSError:
            plugins = []
        for plugin in plugins:
            for info in _skill_dirs(
                os.path.join(plugins_root, plugin, "skills"), "plugin:" + plugin
            ):
                skills.append(info)
    return skills


def discover_rules(home: str | None = None, cwd: str | None = None) -> list[dict]:
    """Always-injected rule files (CLAUDE.md)."""
    home = home or os.path.expanduser("~")
    cwd = cwd or os.getcwd()
    candidates = [
        (os.path.join(home, ".claude", "CLAUDE.md"), "~/.claude/CLAUDE.md", "rules"),
        (os.path.join(cwd, "CLAUDE.md"), "./CLAUDE.md", "rules"),
        (os.path.join(cwd, ".claude", "CLAUDE.md"), "./.claude/CLAUDE.md", "rules"),
    ]
    out = []
    for path, label, source in candidates:
        if os.path.isfile(path):
            info = file_cost(path, label, source)
            if info:
                out.append(info)
    return out


def discover_memory(home: str | None = None, cwd: str | None = None) -> list[dict]:
    """Auto-loaded memory files (MEMORY.md)."""
    home = home or os.path.expanduser("~")
    cwd = cwd or os.getcwd()
    candidates = [
        (os.path.join(cwd, "MEMORY.md"), "./MEMORY.md", "memory"),
        (os.path.join(home, ".claude", "MEMORY.md"), "~/.claude/MEMORY.md", "memory"),
    ]
    projects_root = os.path.join(home, ".claude", "projects")
    if os.path.isdir(projects_root):
        try:
            projects = sorted(os.listdir(projects_root))
        except OSError:
            projects = []
        for proj in projects:
            mem = os.path.join(projects_root, proj, "memory", "MEMORY.md")
            if os.path.isfile(mem):
                candidates.append(
                    (mem, "~/.claude/projects/%s/memory/MEMORY.md" % proj, "memory")
                )
    out = []
    for path, label, source in candidates:
        if os.path.isfile(path):
            info = file_cost(path, label, source)
            if info:
                out.append(info)
    return out


def _mcp_servers_from(path: str, scope: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return out
    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict):
        return out
    for name in sorted(servers):
        entry = servers[name]
        blob = json.dumps({name: entry}, separators=(",", ":"))
        out.append({"name": name, "scope": scope, "entry_chars": len(blob)})
    return out


def discover_mcp(home: str | None = None, cwd: str | None = None) -> list[dict]:
    """Configured MCP servers (static entry cost only).

    This counts the config-entry tax, not the schema tax: every configured
    server's tool schemas are injected at session start, which requires a
    live handshake to measure. For the true schema cost, pair this with
    mcp-tax (github.com/hahahahahahahahah6/mcp-tax).
    """
    from .measure import estimate_tokens

    home = home or os.path.expanduser("~")
    cwd = cwd or os.getcwd()
    servers = _mcp_servers_from(os.path.join(home, ".claude.json"), "global")
    servers += _mcp_servers_from(os.path.join(cwd, ".mcp.json"), "project")
    out = []
    for srv in servers:
        out.append({
            "name": "mcp:%s" % srv["name"],
            "path": "(%s scope)" % srv["scope"],
            "source": "mcp",
            "chars": srv["entry_chars"],
            "tokens": estimate_tokens(srv["entry_chars"]),
            "note": "config entry only; schema tax needs mcp-tax",
        })
    return out


def discover_all(home: str | None = None, cwd: str | None = None,
                 kinds: tuple = ("skills", "rules", "memory", "mcp")) -> dict:
    """Return {kind: [entries]} for the requested always-on source kinds."""
    home = home or os.path.expanduser("~")
    cwd = cwd or os.getcwd()
    result: dict = {}
    if "skills" in kinds:
        result["skills"] = discover_skills(home, cwd)
    if "rules" in kinds:
        result["rules"] = discover_rules(home, cwd)
    if "memory" in kinds:
        result["memory"] = discover_memory(home, cwd)
    if "mcp" in kinds:
        result["mcp"] = discover_mcp(home, cwd)
    return result
