from __future__ import annotations


def normalize_entity_name(name: str) -> str:
    return " ".join(name.strip().lower().split())
