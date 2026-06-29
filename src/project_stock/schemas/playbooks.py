from __future__ import annotations

from pydantic import Field

from project_stock.schemas.common import EmergencyLevel, SchemaBase


class PlaybookActivation(SchemaBase):
    emergency_level_min: EmergencyLevel
    required_confirmation: list[str] = Field(default_factory=list)


class PlaybookDefinition(SchemaBase):
    playbook_id: str
    version: str
    linked_scenarios: list[str]
    activation: PlaybookActivation
    allowed_actions: list[str]
    forbidden_actions: list[str]
    cooldown: dict[str, object] = Field(default_factory=dict)


class PlaybookExecutionResult(SchemaBase):
    playbook_id: str
    activated: bool
    allowed_actions: list[str]
    forbidden_actions: list[str]
    rationale: str
