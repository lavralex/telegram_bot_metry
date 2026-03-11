#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict

import aiohttp


def _bootstrap_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        load_dotenv = None

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    env = os.getenv("ENV", "development")
    if load_dotenv:
        load_dotenv(root / ".env", override=False)
        load_dotenv(root / f".env.{env}", override=True)
    os.environ.setdefault("BOT_TOKEN", "script_dummy_token")


_bootstrap_env()

from app.core.config import config
from app.infrastructure.external.bitrix_oauth import BitrixOAuthService, OAUTH_TOKEN_URL


def _env(name: str, fallback: str = "") -> str:
    return (os.getenv(name, fallback) or "").strip()


def _required(value: str, field: str) -> str:
    v = str(value or "").strip()
    if not v:
        raise RuntimeError(f"{field} is required")
    return v


async def _token_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(OAUTH_TOKEN_URL, data=payload) as resp:
            data = await resp.json(content_type=None)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected token response: {type(data).__name__}")
    if data.get("error"):
        err = str(data.get("error") or "")
        desc = str(data.get("error_description") or "")
        raise RuntimeError(f"Bitrix token error: {err}: {desc}")
    if "access_token" not in data:
        raise RuntimeError(f"Bitrix token response has no access_token: {data}")
    return data


def _save_tokens(*, access_token: str, refresh_token: str, expires_in: int) -> None:
    oauth = BitrixOAuthService()
    oauth.save_oauth_tokens(
        access_token=_required(access_token, "access_token"),
        refresh_token=_required(refresh_token, "refresh_token"),
        expires_in=int(expires_in or 3600),
    )


def _print_state() -> None:
    oauth = BitrixOAuthService()
    st = oauth.get_token_state()
    print(
        {
            "portal": st.get("portal"),
            "token_present": st.get("token_present"),
            "refresh_present": st.get("refresh_present"),
            "is_valid": st.get("is_valid"),
            "expires_at": st.get("expires_at"),
            "seconds_left": st.get("seconds_left"),
            "version": st.get("version"),
        }
    )


async def cmd_save(args: argparse.Namespace) -> int:
    _save_tokens(
        access_token=args.access_token,
        refresh_token=args.refresh_token,
        expires_in=args.expires_in,
    )
    print("OAuth tokens saved.")
    _print_state()
    return 0


async def cmd_exchange_code(args: argparse.Namespace) -> int:
    client_id = _required(args.client_id, "client_id")
    client_secret = _required(args.client_secret, "client_secret")
    redirect_uri = _required(args.redirect_uri, "redirect_uri")
    code = _required(args.code, "code")

    data = await _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    )
    _save_tokens(
        access_token=str(data.get("access_token") or ""),
        refresh_token=str(data.get("refresh_token") or ""),
        expires_in=int(data.get("expires_in", 3600)),
    )
    print("OAuth tokens exchanged by code and saved.")
    _print_state()
    return 0


async def cmd_refresh(args: argparse.Namespace) -> int:
    client_id = _required(args.client_id, "client_id")
    client_secret = _required(args.client_secret, "client_secret")
    refresh_token = _required(args.refresh_token, "refresh_token")

    data = await _token_request(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    )
    _save_tokens(
        access_token=str(data.get("access_token") or ""),
        refresh_token=str(data.get("refresh_token") or refresh_token),
        expires_in=int(data.get("expires_in", 3600)),
    )
    print("OAuth tokens refreshed and saved.")
    _print_state()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Update/save Bitrix OAuth tokens to DB.")
    sub = p.add_subparsers(dest="command", required=True)

    env_client_id = _env("BITRIX24_OAUTH_CLIENT_ID") or _env("BITRIX24_CLIENT_ID")
    env_client_secret = _env("BITRIX24_OAUTH_CLIENT_SECRET") or _env("BITRIX24_CLIENT_SECRET")
    env_redirect_uri = _env("BITRIX24_OAUTH_REDIRECT_URI") or _env("BITRIX24_REDIRECT_URI")
    env_refresh = _env("BITRIX24_OAUTH_REFRESH_TOKEN")

    s1 = sub.add_parser("save", help="Save access/refresh token to DB.")
    s1.add_argument("--access-token", required=True)
    s1.add_argument("--refresh-token", required=True)
    s1.add_argument("--expires-in", type=int, default=3600)
    s1.set_defaults(func=cmd_save)

    s2 = sub.add_parser("exchange-code", help="Exchange code -> tokens and save.")
    s2.add_argument("--code", required=True)
    s2.add_argument("--client-id", default=env_client_id, required=not bool(env_client_id))
    s2.add_argument("--client-secret", default=env_client_secret, required=not bool(env_client_secret))
    s2.add_argument("--redirect-uri", default=env_redirect_uri, required=not bool(env_redirect_uri))
    s2.set_defaults(func=cmd_exchange_code)

    s3 = sub.add_parser("refresh", help="Refresh by refresh_token and save.")
    s3.add_argument("--refresh-token", default=env_refresh, required=not bool(env_refresh))
    s3.add_argument("--client-id", default=env_client_id, required=not bool(env_client_id))
    s3.add_argument("--client-secret", default=env_client_secret, required=not bool(env_client_secret))
    s3.set_defaults(func=cmd_refresh)

    return p


async def _run() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(await args.func(args))


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        raise SystemExit(130)
