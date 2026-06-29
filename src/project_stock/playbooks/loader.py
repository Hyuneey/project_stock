from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from project_stock.schemas.playbooks import PlaybookDefinition


def load_playbook_file(path: Path | str) -> PlaybookDefinition:
    file_path = Path(path)
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        return PlaybookDefinition.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid playbook YAML {file_path}: {exc}") from exc


def load_playbook_dir(path: Path | str) -> list[PlaybookDefinition]:
    root = Path(path)
    return [load_playbook_file(file_path) for file_path in sorted(root.rglob("*.yaml"))]
