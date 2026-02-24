from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone


os.environ.setdefault("BOT_TOKEN", "test_token")

from app.infrastructure.external.bitrix_oauth import BitrixOAuthService


class BitrixOAuthServiceLogicTests(unittest.TestCase):
    def test_is_expiring_true_when_close_to_now(self):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        self.assertTrue(BitrixOAuthService._is_expiring(expires_at, skew_seconds=120))

    def test_is_expiring_false_when_far_from_now(self):
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=20)
        self.assertFalse(BitrixOAuthService._is_expiring(expires_at, skew_seconds=120))

    def test_invalid_refresh_error_detection(self):
        self.assertTrue(BitrixOAuthService._is_invalid_refresh_error("invalid_grant", ""))
        self.assertTrue(BitrixOAuthService._is_invalid_refresh_error("", "refresh token has expired"))
        self.assertFalse(BitrixOAuthService._is_invalid_refresh_error("temporarily_unavailable", "try later"))


if __name__ == "__main__":
    unittest.main()
