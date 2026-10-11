"""skill-tax-cli: audit the context tax of your Claude Code skills.

Scans every skill source (user skills, project skills, plugin marketplace
skills), measures each skill's always-on listing cost and full-load cost in
tokens, simulates Claude Code's listing budget (default 1% of the context
window), and detects skills that would be *silently* excluded from the
model-visible listing when the budget overflows.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
