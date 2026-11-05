"""PhraseForge macro language: parser, engine and built-in commands."""
from phraseforge.macros.registry import MacroError, MacroInfo, catalog
from phraseforge.macros.engine import MacroEngine, apply_case, actions_to_text, html_to_text
from phraseforge.macros import commands  # noqa: F401  (registers commands)
from phraseforge.macros import commands_extra  # noqa: F401  (PhraseExpress-equivalent extras)
from phraseforge.macros import commands_pe  # noqa: F401  (PhraseExpress macros added for G-11)

__all__ = ["MacroEngine", "MacroInfo", "MacroError", "catalog", "apply_case", "actions_to_text", "html_to_text"]
