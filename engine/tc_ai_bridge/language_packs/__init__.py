"""Language QA rule packs: rules as bundled data (layered-rules brief, Phase 3).

A pack is a folder: pack.json plus rules/*.json. docs/LANGUAGE_QA_RULE_PACK.md
documents the schema. The loader validates the pack, compiles its matchers,
and runs every rule's examples before the pack can be used: a broken pack
never goes live silently.
"""
from .loader import (  # noqa: F401
    PackError, RulePack, default_pack, load_pack, load_project_overrides, loaded_pack,
)
