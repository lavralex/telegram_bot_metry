#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    root = Path(__file__).resolve().parent.parent
    env = os.getenv("ENV", "development")
    load_dotenv(root / ".env", override=False)
    load_dotenv(root / f".env.{env}", override=True)


def _getenv(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def _post_form(url: str, form: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    body = urlencode(form).encode("utf-8")
    req = Request(url=url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        payload = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {payload}") from e
    except URLError as e:
        raise RuntimeError(f"Network error: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Non-JSON response: {raw[:400]}") from e

    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response type: {type(data).__name__}")

    if data.get("error"):
        err = data.get("error")
        desc = data.get("error_description")
        raise RuntimeError(f"Bitrix error: {err}; {desc}")

    return data


def _print_token_block(data: Dict[str, Any], fallback_refresh: str = "") -> None:
    access_token = str(data.get("access_token") or "").strip()
    refresh_token = str(data.get("refresh_token") or fallback_refresh or "").strip()
    expires_in = int(data.get("expires_in") or 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    if not access_token:
        raise RuntimeError("Response has no access_token")
    if not refresh_token:
        raise RuntimeError("Response has no refresh_token")

    print("Tokens received:")
    print(f"access_token:  {access_token}")
    print(f"refresh_token: {refresh_token}")
    print(f"expires_in:    {expires_in}")
    print(f"expires_at:    {expires_at.isoformat()}")
    print("")
    print("Put into .env:")
    print(f"BITRIX24_OAUTH_ACCESS_TOKEN={access_token}")
    print(f"BITRIX24_OAUTH_REFRESH_TOKEN={refresh_token}")
    print(f"BITRIX24_OAUTH_EXPIRES_IN={expires_in}")


def cmd_auth_url(args: argparse.Namespace) -> int:
    base = args.portal.rstrip("/")
    if not base.startswith("http://") and not base.startswith("https://"):
        base = f"https://{base}"

    query = urlencode(
        {
            "client_id": args.client_id,
            "response_type": "code",
            "redirect_uri": args.redirect_uri,
        }
    )
    url = f"{base}/oauth/authorize/?{query}"
    print(url)
    return 0


def cmd_exchange_code(args: argparse.Namespace) -> int:
    payload = {
        "grant_type": "authorization_code",
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "code": args.code,
        "redirect_uri": args.redirect_uri,
    }
    data = _post_form(args.token_url, payload)
    _print_token_block(data)
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    payload = {
        "grant_type": "refresh_token",
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "refresh_token": args.refresh_token,
    }
    data = _post_form(args.token_url, payload)
    _print_token_block(data, fallback_refresh=args.refresh_token)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Bitrix24 OAuth helper for getting and refreshing tokens."
    )
    sub = p.add_subparsers(dest="command", required=True)

    env_portal = _getenv("BITRIX24_PORTAL_URL") or _getenv("BITRIX24_PORTAL")
    env_client_id = _getenv("BITRIX24_OAUTH_CLIENT_ID") or _getenv("BITRIX24_CLIENT_ID")
    env_client_secret = _getenv("BITRIX24_OAUTH_CLIENT_SECRET") or _getenv("BITRIX24_CLIENT_SECRET")
    env_redirect_uri = _getenv("BITRIX24_OAUTH_REDIRECT_URI") or _getenv("BITRIX24_REDIRECT_URI")
    env_token_url = _getenv("BITRIX24_OAUTH_TOKEN_URL", "https://oauth.bitrix.info/oauth/token/")
    env_refresh = _getenv("BITRIX24_OAUTH_REFRESH_TOKEN")

    pa = sub.add_parser("auth-url", help="Print OAuth authorize URL for obtaining code.")
    pa.add_argument("--portal", default=env_portal, required=not bool(env_portal))
    pa.add_argument("--client-id", default=env_client_id, required=not bool(env_client_id))
    pa.add_argument("--redirect-uri", default=env_redirect_uri, required=not bool(env_redirect_uri))
    pa.set_defaults(func=cmd_auth_url)

    pe = sub.add_parser("exchange-code", help="Exchange auth code to access/refresh tokens.")
    pe.add_argument("--code", required=True)
    pe.add_argument("--client-id", default=env_client_id, required=not bool(env_client_id))
    pe.add_argument("--client-secret", default=env_client_secret, required=not bool(env_client_secret))
    pe.add_argument("--redirect-uri", default=env_redirect_uri, required=not bool(env_redirect_uri))
    pe.add_argument("--token-url", default=env_token_url)
    pe.set_defaults(func=cmd_exchange_code)

    pr = sub.add_parser("refresh", help="Get new access token from refresh token.")
    pr.add_argument("--refresh-token", default=env_refresh, required=not bool(env_refresh))
    pr.add_argument("--client-id", default=env_client_id, required=not bool(env_client_id))
    pr.add_argument("--client-secret", default=env_client_secret, required=not bool(env_client_secret))
    pr.add_argument("--token-url", default=env_token_url)
    pr.set_defaults(func=cmd_refresh)

    return p


def main() -> int:
    _load_dotenv_if_available()
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
