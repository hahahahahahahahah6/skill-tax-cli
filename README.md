# skill-tax-cli

Audit the **context tax** of your Claude Code skills — and catch the ones
Claude Code silently stops seeing.

Every skill you install adds its name and description to the model's context
on **every turn**, used or not. Claude Code budgets that listing at 1% of
your context window (`skillListingBudgetFraction`, default `0.01`). When the
listing overflows, it drops descriptions starting with your least-used
skills — no warning in the UI, only a `--debug` log line. A skill without a
description keeps nothing for the model to match a request against, so it
quietly stops being chosen. One measured setup found a full plugin install
pushing the listing to ~10.8x the default budget.

skill-tax-cli measures that tax per skill, ranks the offenders, replays the
overflow rule deterministically, and fails your CI when a skill would be
silently dropped.

Zero dependencies. Python standard library only.

## Install

```bash
pip install skill-tax-cli
# or with pipx:
pipx install skill-tax-cli
```

Requires Python 3.9+. No other packages.

## Usage

**List every skill Claude Code can see**, across all three sources
(`user` = `~/.claude/skills`, `project` = `./.claude/skills`,
`plugin:<name>` = marketplace plugins under `~/.claude/plugins`):

```bash
$ skill-tax-cli list
huge          plugin:acme        236 listing /   1482 load tokens  ~/.claude/plugins/acme/skills/huge/SKILL.md
proj          project             6 listing /     16 load tokens  ./.claude/skills/proj/SKILL.md
tiny          user                6 listing /     16 load tokens  ~/.claude/skills/tiny/SKILL.md
3 skill(s)
```

**Audit the tax** — ranks skills by full-load cost, with listing cost and
share of your context window, plus the other always-on sources
(`--sources skills,rules,memory,mcp`):

```bash
$ skill-tax-cli audit --window 200000
skill                          source        listing    load  load%window
---------------------------  --------------  -------  ------  ----------
huge                           plugin:acme        236    1482       0.74%
tiny                           user                 6      16       0.01%
proj                           project              6      16       0.01%
---------------------------  --------------  -------  ------  ----------
TOTAL (3 skills)                                 248    1514       0.76%

[rules] always-on static cost:
  ~/.claude/CLAUDE.md                         175 tokens  ~/.claude/CLAUDE.md
  subtotal: 175 tokens (0.1% of 200000 window)

[memory] always-on static cost:
  ...
[mcp] always-on static cost:
  mcp:gh                                        9 tokens  (global scope)
  subtotal: 9 tokens (0.0% of 200000 window)
```

(`listing` = name + description, injected every turn; `load` = the full
`SKILL.md` injected when the skill is invoked. The `mcp` rows count the
config-entry tax only — the true tool-schema tax needs a live handshake;
pair with
[mcp-tax](https://github.com/hahahahahahahahah6/mcp-tax) for that.)

**Gate your CI** — exits non-zero when the listing budget would silently
strip a skill's description:

```bash
$ skill-tax-cli gate --window 200000 --budget-pct 0.01
SILENT-DROP RISK: 2 of 34 skill(s) exceed the 2000-token listing budget (3120 tokens used):
  - huge [plugin:acme] desc ~230 tokens, usage=1 -> description would be silently stripped
  - helper [user] desc ~88 tokens, usage=0 -> description would be silently stripped
Trim descriptions, raise skillListingBudgetFraction, or remove unused skills.
$ echo $?
1
```

Exit codes: `0` = clean, `1` = silent drops detected, `2` = config/usage
error. Drop order follows the documented rule — least-used skills first.
Pass `--usage usage.json` (`{"skill-name": invocation_count}`) to replay
your real usage; without it, ties break deterministically by larger
description first, then name. Pin an exact token budget with
`--budget-tokens`.

All commands accept `--json` for scripting, and `--home` / `--cwd` to
audit a different machine layout (also handy for tests).

## How the token estimate works

`est. tokens = round(chars / 4)` — Anthropic's ~4-chars-per-token rule of
thumb on English/markdown text, the same gauge
[mcp-tax](https://github.com/hahahahahahahahah6/mcp-tax) uses. The listing
cost counts the skill's `name` + `description` from its frontmatter; the
load cost counts the whole `SKILL.md`. Real token counts vary with the
tokenizer, so treat the numbers as an order-of-magnitude gauge — good
enough to answer "which skill is eating my window?", not a billing meter.

## Differentiation

- **The only CI-friendly, deterministic skill auditor.** The official
  `/skill-doctor` (v2.1.261) and every community skill-doctor I found are
  interactive — they show you a report inside a session. skill-tax-cli is a
  plain CLI with stable exit codes and `--json` output, built for pre-commit
  hooks and CI pipelines.
- **Silent-exclusion detection is the point, not a footnote.** Nobody else
  replays the listing-budget overflow rule: official docs describe the 1%
  budget and the least-used-first drop order, but `/skill-doctor` only shows
  the current state. skill-tax-cli tells you *which* skills would lose their
  descriptions *before* it happens, so you can trim them instead of
  wondering why Claude stopped reaching for them.
- **One CLI for all always-on sources.** Skills, rules (`CLAUDE.md`),
  memory (`MEMORY.md`), and MCP configs are measured together — the full
  per-turn tax in one table, not four tools.

## Limitations

- The estimate is chars/4, not the real tokenizer — order-of-magnitude only.
- Without `--usage`, drop order among equally-used skills is a documented
  heuristic (bigger description first), not your real invocation history.
- The MCP rows measure the config entry, not tool schemas (needs a live
  handshake — that's what
  [mcp-tax](https://github.com/hahahahahahahahah6/mcp-tax) is for).
- Plugin skills are discovered from `~/.claude/plugins/*/skills/`; skills
  installed through other managers outside these paths won't be seen.

## Development

```bash
python3 tests/test_smoke.py   # 10 smoke tests: cost math, discovery,
                              # budget simulation, silent-drop detection,
                              # gate exit codes
```

## License

MIT — see [LICENSE](LICENSE).
