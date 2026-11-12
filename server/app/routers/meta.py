from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends

from .. import API_VERSION
from ..deps import Principal, get_clock, get_settings, require_any

router = APIRouter(tags=["meta"])


@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.get("/v1/meta")
def meta(s=Depends(get_settings), clock: Callable[[], float] = Depends(get_clock)):
    return {"api": API_VERSION, "min_app": s.min_app_version, "server_time": clock()}


@router.get("/v1/me")
def me(p: Principal = Depends(require_any)):
    u = p.user
    return {"initials": u.initials, "display_name": u.display_name, "role": u.role, "must_change": bool(u.must_change), "scope": p.scope}
