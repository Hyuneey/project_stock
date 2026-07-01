from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from project_stock.schemas.thesis import ThesisDefinition


def _version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.replace("-", ".").split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def load_thesis_file(path: Path | str) -> ThesisDefinition:
    file_path = Path(path)
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        return ThesisDefinition.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid thesis YAML {file_path}: {exc}") from exc


def load_thesis_dir(path: Path | str) -> list[ThesisDefinition]:
    root = Path(path)
    latest: dict[str, ThesisDefinition] = {}
    for file_path in sorted(root.rglob("*.yaml")):
        thesis = load_thesis_file(file_path)
        current = latest.get(thesis.thesis_id)
        if current is None or _version_key(thesis.version) >= _version_key(current.version):
            latest[thesis.thesis_id] = thesis
    return [latest[thesis_id] for thesis_id in sorted(latest)]
