"""Token measurement and SKILL.md frontmatter parsing (stdlib only)."""

from __future__ import annotations

import os
import re


def estimate_tokens(chars: int) -> int:
    """Chars -> tokens using Anthropic's ~4-chars-per-token rule of thumb."""
    return round(chars / 4)


def _unfold(value: str) -> str:
    """Collapse a YAML folded (`>`) or literal (`|`) scalar to one line."""
    lines = value.splitlines()
    stripped = [ln.strip() for ln in lines if ln.strip()]
    if value.lstrip().startswith("|"):
        return "\n".join(stripped)
    return " ".join(stripped)


def parse_frontmatter(text: str) -> dict:
    """Extract a small subset of SKILL.md YAML frontmatter (name, description).

    Hand-rolled, stdlib-only parser: handles plain scalars, single/double
    quoted scalars, and folded (`>`) / literal (`|`) blocks indented under
    the key. Returns {} when there is no frontmatter block.
    """
    out: dict = {}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    if end == -1:
        return out
    block = text[3:end]
    key = None
    buf: list[str] = []
    style = None

    def flush():
        if key is not None:
            raw = "\n".join(buf)
            out[key] = _unfold(raw) if style else raw.strip().strip("'\"")

    for line in block.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            flush()
            key, rest = m.group(1), m.group(2).strip()
            if rest in (">", ">-", "|", "|-"):
                style, buf = rest[0], []
            else:
                style, buf = None, [rest]
        elif key is not None and line[:1] in (" ", "\t"):
            buf.append(line)
        elif key is not None and not line.strip():
            buf.append(line)
    flush()
    return out


def read_skill(path: str, default_name: str) -> dict:
    """Read one SKILL.md and compute its listing + full-load costs."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    fm = parse_frontmatter(text)
    name = (fm.get("name") or default_name).strip()
    description = (fm.get("description") or "").strip()
    # The always-on listing carries the name always; the description is what
    # Claude Code drops first when the listing budget overflows.
    name_chars = len(name)
    desc_chars = len(description)
    load_chars = len(text)
    return {
        "name": name,
        "path": path,
        "description": description,
        "name_tokens": estimate_tokens(name_chars),
        "desc_tokens": estimate_tokens(desc_chars),
        "listing_tokens": estimate_tokens(name_chars + 1 + desc_chars),
        "load_chars": load_chars,
        "load_tokens": estimate_tokens(load_chars),
    }


def file_cost(path: str, label: str, source: str) -> dict:
    """Static always-on cost of a rules/memory file (fully injected)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return {}
    chars = len(text)
    return {
        "name": label,
        "path": path,
        "source": source,
        "chars": chars,
        "tokens": estimate_tokens(chars),
    }


def rel_home(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path
