from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntityMapping:
    entity_type: str
    entity_id: str
    relevance_score: float = 1.0


ENTITY_ALIASES: dict[str, EntityMapping] = {
    "samsung electronics": EntityMapping("company", "005930", 1.0),
    "005930": EntityMapping("company", "005930", 1.0),
    "samsung": EntityMapping("company", "005930", 0.8),
    "sk hynix": EntityMapping("company", "000660", 1.0),
    "000660": EntityMapping("company", "000660", 1.0),
    "semiconductor": EntityMapping("theme", "KOR_SEMI_MEMORY_UPCYCLE", 1.0),
    "semiconductors": EntityMapping("theme", "KOR_SEMI_MEMORY_UPCYCLE", 1.0),
    "semiconductor etf": EntityMapping("asset", "SEMI_ETF_PROXY", 1.0),
    "krx semiconductor": EntityMapping("asset", "SEMI_ETF_PROXY", 1.0),
    "semi": EntityMapping("sector", "SEMICONDUCTOR", 0.7),
    "sox": EntityMapping("asset", "SOX", 1.0),
    "memory": EntityMapping("theme", "KOR_SEMI_MEMORY_UPCYCLE", 0.8),
    "ai": EntityMapping("theme", "AI_INFRASTRUCTURE", 0.8),
    "ai capex": EntityMapping("macro_factor", "AI_CAPEX", 0.9),
    "rate": EntityMapping("macro_factor", "RATES", 0.8),
    "yield": EntityMapping("macro_factor", "RATES", 0.8),
    "fed": EntityMapping("macro_factor", "RATES", 0.8),
    "us10y": EntityMapping("macro_factor", "US10Y", 1.0),
    "dollar": EntityMapping("macro_factor", "USD", 0.8),
    "fx": EntityMapping("macro_factor", "FX", 0.8),
    "foreign flow": EntityMapping("macro_factor", "FOREIGN_FLOWS", 0.8),
    "kospi200": EntityMapping("asset", "KOSPI200", 1.0),
    "usdkrw": EntityMapping("asset", "USDKRW", 1.0),
    "vix": EntityMapping("asset", "VIX", 1.0),
    "oil": EntityMapping("macro_factor", "ENERGY", 0.8),
    "earnings": EntityMapping("fundamental", "EARNINGS", 0.8),
    "korea": EntityMapping("country", "KR", 0.8),
    "us": EntityMapping("country", "US", 0.6),
}

SYMBOL_ENTITY_MAPPINGS: dict[str, EntityMapping] = {
    "005930": EntityMapping("company", "005930", 1.0),
    "000660": EntityMapping("company", "000660", 1.0),
    "USDKRW": EntityMapping("asset", "USDKRW", 1.0),
    "US10Y": EntityMapping("macro_factor", "US10Y", 1.0),
    "SOX": EntityMapping("asset", "SOX", 1.0),
    "VIX": EntityMapping("asset", "VIX", 1.0),
    "KOSPI200": EntityMapping("asset", "KOSPI200", 1.0),
    "SEMI_ETF_PROXY": EntityMapping("asset", "SEMI_ETF_PROXY", 1.0),
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


def map_symbol_entity(symbol: str) -> list[dict[str, object]]:
    mapping = SYMBOL_ENTITY_MAPPINGS.get(symbol.upper())
    if mapping is None:
        return []
    return [
        {
            "entity_type": mapping.entity_type,
            "entity_id": mapping.entity_id,
            "relevance_score": mapping.relevance_score,
        }
    ]
