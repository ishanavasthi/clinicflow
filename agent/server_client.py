"""Async HTTP client for the ClinicFlow FastAPI server.

Thin wrappers over the persistence endpoints. Callers (the function tools) catch
exceptions and translate them into {ok: False, error} so a persistence hiccup
never crashes the live call.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx


class ServerClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url or os.getenv(
            "CLINICFLOW_API_URL", "http://localhost:8000"
        )
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _json(self, method: str, path: str, body: Any = None) -> Any:
        res = await self._client.request(method, path, json=body)
        res.raise_for_status()
        return res.json()

    async def create_call(self, room: str) -> dict:
        return await self._json("POST", "/calls", {"room": room})

    async def end_call(
        self,
        call_id: int,
        routed_department: Optional[str] = None,
        recording_url: Optional[str] = None,
    ) -> dict:
        return await self._json(
            "POST",
            f"/calls/{call_id}/end",
            {"routed_department": routed_department, "recording_url": recording_url},
        )

    async def add_event(self, call_id: int, type: str, payload: dict) -> dict:
        return await self._json(
            "POST", f"/calls/{call_id}/events", {"type": type, "payload": payload}
        )

    async def create_patient(self, **fields: Any) -> dict:
        return await self._json("POST", "/patients", fields)

    async def update_patient(self, patient_id: int, **fields: Any) -> dict:
        return await self._json("PATCH", f"/patients/{patient_id}", fields)

    async def availability(
        self, department: str, limit: int = 3
    ) -> list[dict]:
        return await self._json(
            "GET", f"/appointments/availability?department={department}&limit={limit}"
        )

    async def book(self, patient_id: int, slot_id: int, reason: str) -> dict:
        return await self._json(
            "POST",
            "/appointments",
            {"patient_id": patient_id, "slot_id": slot_id, "reason": reason},
        )
