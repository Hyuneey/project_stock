from __future__ import annotations

import pytest

from project_stock.playbooks.loader import load_playbook_dir
from project_stock.scenarios.loader import load_scenario_dir
from project_stock.thesis.loader import load_thesis_dir


def test_yaml_libraries_load(repo_root):
    theses = load_thesis_dir(repo_root / "thesis")
    scenarios = load_scenario_dir(repo_root / "scenarios")
    playbooks = load_playbook_dir(repo_root / "playbooks")

    assert len(theses) >= 2
    assert len(scenarios) >= 4
    assert len(playbooks) >= 3
    assert {item.thesis_id for item in theses} >= {"KOR_SEMI_MEMORY_UPCYCLE", "AI_INFRASTRUCTURE"}


def test_invalid_yaml_has_readable_validation_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("thesis_id: ONLY_ID\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid thesis YAML"):
        load_thesis_dir(tmp_path)
