from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from project_stock.schemas.scenarios import ScenarioDefinition


def load_scenario_file(path: Path | str) -> ScenarioDefinition:
    file_path = Path(path)
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        return ScenarioDefinition.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid scenario YAML {file_path}: {exc}") from exc


def load_scenario_dir(path: Path | str) -> list[ScenarioDefinition]:
    root = Path(path)
    return [load_scenario_file(file_path) for file_path in sorted(root.rglob("*.yaml"))]
