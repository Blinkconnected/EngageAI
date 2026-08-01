"""The push contract and the FCM payload/error mapping, in isolation —
no HTTP, no database. See ``docs/architecture/notifications.md``.

The mapping tests are the valuable ones here: the difference between "this
token is dead" and "try again shortly" decides whether a device row is
deleted or a notification is retried, and getting it backwards is a silent
failure either way.
"""

import httpx
import orjson
import pytest

from blinkengage.domain.push import (
    DevicePlatform,
    PushMessage,
    PushOutcome,
    PushResult,
)
from blinkengage.infrastructure.push.fcm import FcmPushSender, _error_code
from blinkengage.infrastructure.push.service_account import (
    ServiceAccount,
    ServiceAccountError,
)

_ACCOUNT = ServiceAccount(
    client_email="pusher@example.iam.gserviceaccount.com",
    private_key="-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
    token_uri="https://oauth2.googleapis.com/token",
    project_id="blink-engage-test",
)


def _response(status_code: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=orjson.dumps(payload) if payload is not None else b"",
        headers={"Content-Type": "application/json"} if payload is not None else None,
        request=httpx.Request("POST", "https://fcm.googleapis.com/"),
    )


class TestPushMessage:
    def test_data_values_must_be_strings(self) -> None:
        # FCM rejects the whole payload for one non-string value, which
        # would show up as a notification that silently never arrives.
        with pytest.raises(ValueError, match="must be strings"):
            PushMessage(
                token="t" * 20,
                platform=DevicePlatform.IOS,
                title="Hi",
                body="There",
                data={"unread": 3},  # type: ignore[dict-item]
            )

    def test_string_data_is_accepted(self) -> None:
        message = PushMessage(
            token="t" * 20,
            platform=DevicePlatform.IOS,
            title="Hi",
            body="There",
            data={"conversation_id": "abc"},
        )
        assert message.data == {"conversation_id": "abc"}

    def test_empty_data_is_fine(self) -> None:
        assert (
            PushMessage(token="t" * 20, platform=DevicePlatform.WEB, title="Hi", body="There").data
            == {}
        )


class TestOutcome:
    def test_only_delivered_counts_as_delivered(self) -> None:
        assert PushResult(PushOutcome.DELIVERED).is_delivered
        assert not PushResult(PushOutcome.RETRY).is_delivered
        assert not PushResult(PushOutcome.DEVICE_GONE).is_delivered


class TestFcmPayload:
    def _sender(self) -> FcmPushSender:
        return FcmPushSender(project_id="blink-engage-test", account=_ACCOUNT)

    def test_notification_and_data_are_both_sent(self) -> None:
        # Both, always: an app that only handled `data` would render
        # nothing while backgrounded, which is the moment push exists for.
        body = self._sender()._build_message(
            PushMessage(
                token="tok" * 10,
                platform=DevicePlatform.ANDROID,
                title="New conversation",
                body="A customer is waiting",
                data={"conversation_id": "c-1"},
            )
        )
        assert body["notification"] == {
            "title": "New conversation",
            "body": "A customer is waiting",
        }
        assert body["data"] == {"conversation_id": "c-1"}
        assert body["token"] == "tok" * 10

    def test_android_gets_high_priority(self) -> None:
        body = self._sender()._build_message(
            PushMessage(token="t" * 20, platform=DevicePlatform.ANDROID, title="t", body="b")
        )
        assert body["android"] == {"priority": "high"}
        assert "apns" not in body

    def test_ios_gets_a_sound_not_a_silent_alert(self) -> None:
        body = self._sender()._build_message(
            PushMessage(token="t" * 20, platform=DevicePlatform.IOS, title="t", body="b")
        )
        assert body["apns"]["headers"]["apns-priority"] == "10"
        assert body["apns"]["payload"]["aps"]["sound"] == "default"
        assert "android" not in body

    def test_web_gets_no_platform_block(self) -> None:
        body = self._sender()._build_message(
            PushMessage(token="t" * 20, platform=DevicePlatform.WEB, title="t", body="b")
        )
        assert "android" not in body
        assert "apns" not in body

    def test_data_is_omitted_when_empty(self) -> None:
        body = self._sender()._build_message(
            PushMessage(token="t" * 20, platform=DevicePlatform.WEB, title="t", body="b")
        )
        assert "data" not in body


class TestErrorCode:
    def test_specific_fcm_error_code_wins_over_generic_status(self) -> None:
        # The errorCode in details is what distinguishes a dead token; the
        # outer status is only ever a category.
        assert (
            _error_code(
                _response(
                    404,
                    {
                        "error": {
                            "status": "NOT_FOUND",
                            "details": [
                                {
                                    "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                                    "errorCode": "UNREGISTERED",
                                }
                            ],
                        }
                    },
                )
            )
            == "UNREGISTERED"
        )

    def test_falls_back_to_status_when_there_are_no_details(self) -> None:
        assert _error_code(_response(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})) == (
            "RESOURCE_EXHAUSTED"
        )

    def test_unparseable_body_is_none_not_a_guess(self) -> None:
        # A body we cannot read must never be mistaken for a dead device —
        # that would delete a live registration.
        assert _error_code(_response(500)) is None
        assert _error_code(_response(200, {"name": "projects/p/messages/1"})) is None


class TestServiceAccount:
    def test_parses_the_firebase_key_file(self) -> None:
        account = ServiceAccount.from_json(
            orjson.dumps(
                {
                    "type": "service_account",
                    "project_id": "blink-engage",
                    "client_email": "a@b.iam.gserviceaccount.com",
                    "private_key": "-----BEGIN PRIVATE KEY-----\nk\n-----END PRIVATE KEY-----\n",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            ).decode()
        )
        assert account.project_id == "blink-engage"
        assert account.client_email == "a@b.iam.gserviceaccount.com"

    def test_escaped_newlines_in_the_key_are_repaired(self) -> None:
        # A key pasted through an env var arrives with literal \n, and PEM
        # parsing then fails in a way that names neither cause nor fix.
        raw = '{"client_email":"a@b","private_key":"-----BEGIN X-----\\\\nkey\\\\n-----END X-----"}'
        account = ServiceAccount.from_json(raw)
        assert "\\n" not in account.private_key
        assert "\n" in account.private_key

    def test_a_missing_private_key_is_named(self) -> None:
        with pytest.raises(ServiceAccountError, match="private_key"):
            ServiceAccount.from_json('{"client_email":"a@b"}')

    def test_invalid_json_is_refused_clearly(self) -> None:
        with pytest.raises(ServiceAccountError, match="not valid JSON"):
            ServiceAccount.from_json("not json at all")

    def test_token_uri_defaults_when_absent(self) -> None:
        account = ServiceAccount.from_json('{"client_email":"a@b","private_key":"k"}')
        assert account.token_uri == "https://oauth2.googleapis.com/token"
        assert account.project_id is None
