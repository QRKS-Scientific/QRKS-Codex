from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

CLIENT_RE = re.compile(r"^QC-\d{3,6}$")
CODE_RE = re.compile(r"^QDOCK-(\d{6})-(\d{3})$")
ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# What an activity event may carry. Anything else is dropped, so ligand names, sequences and
# structures cannot leave a laptop through this API even by mistake.
EVENT_FIELDS: dict[str, set[str]] = {
    "run_created": {"package"},
    "receptor_prepared": {"method", "ph", "box"},
    "ligands_prepared": {"ligands", "states"},
    "validation_completed": {"rmsd_top", "passed"},
    "run_completed": {"run_id", "ligands", "vina"},
    "ligand_renamed": set(),
    "report_generated": {"final", "file"},
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Strict):
    initials: str = Field(min_length=2, max_length=8)
    password: str = Field(min_length=1, max_length=200)
    device_id: str
    device_name: str = Field(default="", max_length=80)

    @field_validator("device_id")
    @classmethod
    def _device(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("device_id must be 8-64 letters, digits, dot, dash or underscore")
        return v


class RefreshIn(Strict):
    refresh_token: str = Field(min_length=20, max_length=200)
    device_id: str


class LogoutIn(Strict):
    refresh_token: str = Field(min_length=20, max_length=200)


class ChangePasswordIn(Strict):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class RunIn(Strict):
    client_code: str
    package: str = Field(default="", max_length=16)
    code: str | None = None                 # register a code that already exists on a laptop (an adopted folder)
    request_id: str | None = None           # makes a retried "create" safe

    @field_validator("client_code")
    @classmethod
    def _client(cls, v: str) -> str:
        v = v.strip().upper()
        if not CLIENT_RE.match(v):
            raise ValueError("client_code must look like QC-001")
        return v

    @field_validator("code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is not None and not CODE_RE.match(v):
            raise ValueError("code must look like QDOCK-260824-001")
        return v

    @field_validator("request_id")
    @classmethod
    def _req(cls, v: str | None) -> str | None:
        if v is not None and not ID_RE.match(v):
            raise ValueError("invalid request_id")
        return v


class EventIn(Strict):
    id: str
    type: str
    utc: str = Field(max_length=40)
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("invalid event id")
        return v

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in EVENT_FIELDS:
            raise ValueError(f"unknown event type '{v}'")
        return v


class EventsIn(Strict):
    events: list[EventIn] = Field(max_length=200)
