from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntityMapping:
    entity_type: str
    entity_id: str
    relevance_score: float = 1.0


ENTITY_ALIASES: dict[str, EntityMapping] = {
    "samsung electronics": EntityMapping("company", "005930", 1.0),
    "samsung": EntityMapping("company", "005930", 0.8),
    "sk hynix": EntityMapping("company", "000660", 1.0),
    "semiconductor": EntityMapping("theme", "KOR_SEMI_MEMORY_UPCYCLE", 1.0),
    "semiconductors": EntityMapping("theme", "KOR_SEMI_MEMORY_UPCYCLE", 1.0),
    "memory": EntityMapping("theme", "KOR_SEMI_MEMORY_UPCYCLE", 0.8),
    "ai": EntityMapping("theme", "AI_INFRASTRUCTURE", 0.8),
    "rate": EntityMapping("macro", "RATES", 0.8),
    "yield": EntityMapping("macro", "RATES", 0.8),
    "fed": EntityMapping("macro", "RATES", 0.8),
    "dollar": EntityMapping("macro", "USD", 0.8),
    "usdkrw": EntityMapping("macro", "USDKRW", 0.8),
    "oil": EntityMapping("macro", "ENERGY", 0.8),
    "earnings": EntityMapping("fundamental", "EARNINGS", 0.8),
}


def map_entities(text: str) -> list[dict[str, object]]:
    lowered = text.lower()
    results: dict[tuple[str, str], EntityMapping] = {}
    for alias, mapping in ENTITY_ALIASES.items():
        if alias in lowered:
            key = (mapping.entity_type, mapping.entity_id)
            current = results.get(key)
            if current is None or mapping.relevance_score > current.relevance_score:
                results[key] = mapping
    return [
        {
            "entity_type": mapping.entity_type,
            "entity_id": mapping.entity_id,
            "relevance_score": mapping.relevance_score,
        }
        for mapping in results.values()
    ]
