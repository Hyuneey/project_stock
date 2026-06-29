from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from project_stock.schemas.thesis import ThesisDefinition


def load_thesis_file(path: Path | str) -> ThesisDefinition:
    file_path = Path(path)
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        return ThesisDefinition.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid thesis YAML {file_path}: {exc}") from exc


def load_thesis_dir(path: Path | str) -> list[ThesisDefinition]:
    root = Path(path)
    return [load_thesis_file(file_path) for file_path in sorted(root.rglob("*.yaml"))]
