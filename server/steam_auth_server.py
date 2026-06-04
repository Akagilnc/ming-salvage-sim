#!/usr/bin/env python3
"""Minimal trusted server for Steam Web API ticket authentication.

Do not ship this file or its environment variables inside the game client.
Deploy it on your backend infrastructure and keep STEAM_PUBLISHER_WEB_API_KEY secret.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


STEAM_AUTH_URL = "https://partner.steam-api.com/ISteamUserAuth/AuthenticateUserTicket/v1/"


def _env_int(name: str, default: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _allowed_origins() -> List[str]:
    raw = os.environ.get("STEAM_AUTH_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _publisher_key() -> str:
    key = os.environ.get("STEAM_PUBLISHER_WEB_API_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=500, detail="STEAM_PUBLISHER_WEB_API_KEY is not configured.")
    return key


def _expected_app_id() -> int:
    app_id = _env_int("STEAM_APP_ID") or _env_int("MING_SIM_STEAM_APP_ID")
    if app_id <= 0:
        raise HTTPException(status_code=500, detail="STEAM_APP_ID is not configured.")
    return app_id


def _expected_identity() -> str:
    return os.environ.get("STEAM_AUTH_IDENTITY", "").strip() or "ming-salvage-server"


def _validate_ticket_hex(ticket: str) -> str:
    value = (ticket or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="ticket is required.")
    if len(value) > 8192:
        raise HTTPException(status_code=400, detail="ticket is too large.")
    if len(value) % 2 != 0:
        raise HTTPException(status_code=400, detail="ticket must be even-length hex.")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="ticket must be hex encoded.") from None
    return value


class SteamLoginRequest(BaseModel):
    appid: int = Field(..., gt=0)
    identity: str = ""
    ticket: str
    # Client-supplied values are useful for logs/UI correlation only. Never trust them as identity.
    steamId64: str = ""
    personaName: str = ""


def authenticate_user_ticket(appid: int, ticket: str, identity: str) -> Dict[str, Any]:
    params = urlencode({
        "key": _publisher_key(),
        "appid": str(appid),
        "ticket": ticket,
        "identity": identity,
    })
    request = Request(f"{STEAM_AUTH_URL}?{params}", method="GET")
    try:
        with urlopen(request, timeout=12) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Steam Web API HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Steam Web API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Steam Web API request timed out.") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Steam Web API returned invalid JSON.") from exc

    response = data.get("response") if isinstance(data, dict) else None
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="Steam Web API response missing response object.")

    params_obj = response.get("params")
    error_obj = response.get("error")
    if error_obj:
        raise HTTPException(status_code=401, detail={"steam_error": error_obj})
    if not isinstance(params_obj, dict) or not params_obj.get("steamid"):
        raise HTTPException(status_code=401, detail="Steam ticket authentication failed.")
    return params_obj


app = FastAPI(title="Ming Salvage Steam Auth Server")

origins = _allowed_origins()
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["POST", "GET"],
        allow_headers=["content-type", "authorization"],
    )


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "steam_app_id_configured": _env_int("STEAM_APP_ID") > 0 or _env_int("MING_SIM_STEAM_APP_ID") > 0,
        "publisher_key_configured": bool(os.environ.get("STEAM_PUBLISHER_WEB_API_KEY", "").strip()),
        "identity": _expected_identity(),
    }


@app.post("/steam/login")
async def steam_login(body: SteamLoginRequest) -> Dict[str, Any]:
    expected_app_id = _expected_app_id()
    expected_identity = _expected_identity()
    if body.appid != expected_app_id:
        raise HTTPException(status_code=400, detail=f"appid mismatch: expected {expected_app_id}.")
    if (body.identity or "").strip() != expected_identity:
        raise HTTPException(status_code=400, detail=f"identity mismatch: expected {expected_identity!r}.")

    ticket = _validate_ticket_hex(body.ticket)
    steam_params = authenticate_user_ticket(expected_app_id, ticket, expected_identity)
    steamid = str(steam_params["steamid"])

    return {
        "ok": True,
        "steamid": steamid,
        "appid": expected_app_id,
        "identity": expected_identity,
        "ownersteamid": steam_params.get("ownersteamid"),
        "vacbanned": steam_params.get("vacbanned"),
        "publisherbanned": steam_params.get("publisherbanned"),
    }
