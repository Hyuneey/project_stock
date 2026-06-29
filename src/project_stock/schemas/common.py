from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class SchemaBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ThesisStatus(str, Enum):
    candidate = "candidate"
    watch = "watch"
    active = "active"
    core_overweight = "core_overweight"
    crowded = "crowded"
    deteriorating = "deteriorating"
    suspended = "suspended"
    invalidated = "invalidated"
    archived = "archived"


class ScenarioStatus(str, Enum):
    draft = "draft"
    reviewed = "reviewed"
    verified = "verified"
    active = "active"
    triggered = "triggered"
    resolved = "resolved"
    expired = "expired"
    retired = "retired"
    archived = "archived"


class EmergencyLevel(str, Enum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    E4 = "E4"
    E5 = "E5"


EMERGENCY_LEVEL_ORDER = {
    EmergencyLevel.E0: 0,
    EmergencyLevel.E1: 1,
    EmergencyLevel.E2: 2,
    EmergencyLevel.E3: 3,
    EmergencyLevel.E4: 4,
    EmergencyLevel.E5: 5,
}
