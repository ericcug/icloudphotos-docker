"""Tests for Telegram controller input tolerance (uppercase, spaces, auth commands)."""

from unittest.mock import MagicMock
import pytest

from control.telegram_bot import TelegramController


def test_telegram_sms_choice_case_and_whitespace_tolerance():
    service = MagicMock()
    mfa_provider = MagicMock()
    mfa_provider._code_event.is_set.return_value = False

    ctrl = TelegramController(
        service=service,
        chat_id="12345",
        mfa_provider=mfa_provider,
    )

    # Mobile keyboard capitalizes "A" and adds spaces "  A  "
    update = {
        "update_id": 1,
        "message": {
            "chat": {"id": 12345},
            "text": "  A  ",
        },
    }

    ctrl._process_update(update)
    mfa_provider.provide_code.assert_called_once_with("a")


def test_telegram_mfa_code_whitespace_tolerance():
    service = MagicMock()
    mfa_provider = MagicMock()

    ctrl = TelegramController(
        service=service,
        chat_id="12345",
        mfa_provider=mfa_provider,
    )

    update = {
        "update_id": 2,
        "message": {
            "chat": {"id": 12345},
            "text": "  654321  ",
        },
    }

    ctrl._process_update(update)
    mfa_provider.provide_code.assert_called_once_with("654321")


def test_telegram_auth_command_variants():
    service = MagicMock()
    auth_manager = MagicMock()

    ctrl = TelegramController(
        service=service,
        chat_id="12345",
        auth_manager=auth_manager,
    )
    ctrl.request_reauth = MagicMock()

    # "<user> auth"
    update1 = {
        "update_id": 3,
        "message": {
            "chat": {"id": 12345},
            "text": "eric auth",
        },
    }
    ctrl._process_update(update1)
    assert ctrl.request_reauth.call_count == 1

    # "AUTH"
    update2 = {
        "update_id": 4,
        "message": {
            "chat": {"id": 12345},
            "text": "  AUTH  ",
        },
    }
    ctrl._process_update(update2)
    assert ctrl.request_reauth.call_count == 2
