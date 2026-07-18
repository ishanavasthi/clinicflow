"""Mint LiveKit access tokens.

Two roles share one room per call:
  - caller:   publishes mic, subscribes to the agent audio.
  - observer: the dashboard. Subscribe-only and hidden, so it never appears as a
              participant or shows up in the agent's audio graph.
"""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from livekit import api
from pydantic import BaseModel

from config import get_settings

router = APIRouter(prefix="/token", tags=["token"])


class TokenRequest(BaseModel):
    role: Literal["caller", "observer"]
    room: Optional[str] = None
    identity: Optional[str] = None


class TokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str


@router.post("", response_model=TokenResponse)
def create_token(req: TokenRequest) -> TokenResponse:
    settings = get_settings()
    try:
        url, key, secret = settings.require_livekit()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    room = req.room or f"call-{uuid.uuid4().hex[:8]}"
    identity = req.identity or f"{req.role}-{uuid.uuid4().hex[:6]}"

    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_subscribe=True,
        can_publish=req.role == "caller",
        can_publish_data=req.role == "caller",
        hidden=req.role == "observer",
    )

    token = (
        api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .to_jwt()
    )

    return TokenResponse(token=token, url=url, room=room, identity=identity)
