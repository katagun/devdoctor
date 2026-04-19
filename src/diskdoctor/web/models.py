from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from diskdoctor.types import Risk


class RecipeRequest(BaseModel):
    providers: list[str] | None = None


class RecipeResponse(BaseModel):
    script: str


class ProviderInfo(BaseModel):
    name: str
    description: str
    risk: Literal["safe", "reclaimable", "dangerous"]
    platforms: list[str]
    available: bool
    required_binary: str | None
    kind: Literal["class", "yaml"]
    reason_if_unavailable: str | None = None


class CleanJobCreate(BaseModel):
    entry_ids: list[str] = Field(min_length=1)
    yes_safe: bool = False
    allow_dangerous: bool = False


class CleanJobCreated(BaseModel):
    job_id: str


class PromptAnswer(BaseModel):
    entry_id: str
    choice: Literal["y", "n", "a", "s", "q"]


class ConfirmAnswer(BaseModel):
    confirmed: bool


class SnapshotCreate(BaseModel):
    note: str | None = None


class SnapshotMeta(BaseModel):
    name: str
    path: str
    scanned_at: str
    hostname: str
    platform: str
    note: str | None
    total_bytes: int


_RISK_VALUES: set[str] = {r.value for r in Risk}
