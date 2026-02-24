#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    root = Path(__file__).resolve().parent.parent
    env = os.getenv("ENV", "development")
    load_dotenv(root / ".env", override=False)
    load_dotenv(root / f".env.{env}", override=True)


def _get(name: str, fallback: str = "") -> str:
    return (os.getenv(name, fallback) or "").strip()


def _normalize_portal(portal: str) -> str:
    p = portal.strip()
    if not p:
        return ""
    if p.startswith("http://") or p.startswith("https://"):
        return p.rstrip("/")
    if urlparse(p).scheme:
        return p.rstrip("/")
    return f"https://{p}".rstrip("/")


def main() -> int:
    _load_env()

    portal = _get("BITRIX24_PORTAL_URL") or _get("BITRIX24_PORTAL")
    client_id = _get("BITRIX24_OAUTH_CLIENT_ID") or _get("BITRIX24_CLIENT_ID")
    redirect_uri = _get("BITRIX24_OAUTH_REDIRECT_URI") or _get("BITRIX24_REDIRECT_URI")

    missing = []
    if not portal:
        missing.append("BITRIX24_PORTAL_URL (or BITRIX24_PORTAL)")
    if not client_id:
        missing.append("BITRIX24_OAUTH_CLIENT_ID (or BITRIX24_CLIENT_ID)")
    if not redirect_uri:
        missing.append("BITRIX24_OAUTH_REDIRECT_URI (or BITRIX24_REDIRECT_URI)")

    if missing:
        print("ERROR: missing env vars:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 2

    base = _normalize_portal(portal)
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
        }
    )
    print(f"{base}/oauth/authorize/?{query}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
