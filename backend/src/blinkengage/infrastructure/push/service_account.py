"""Google service-account access tokens, for FCM's HTTP v1 API. See
``docs/architecture/notifications.md``.

FCM v1 will not accept the legacy server key; it wants a short-lived OAuth
access token belonging to a service account. Getting one is a two-step
exchange: sign a JWT assertion with the service account's private key,
then trade that assertion for an access token.

Implemented here in ~60 lines rather than by adding ``google-auth``:
the exchange is two well-specified HTTP requests and one signature this
codebase can already produce (``python-jose`` with the cryptography
backend, the same library every session token goes through), while
``google-auth`` brings a transport stack, its own credential-discovery
machinery and a dependency surface far wider than the one call we need.

The token is cached in-process until shortly before it expires. Minting
one costs a network round trip and an RSA signature, and a dispatch sweep
sends many messages per run — re-minting per message would make the
signature the dominant cost of pushing a notification.
"""

import time
from dataclasses import dataclass
from typing import Any, Final

import httpx
import orjson
from jose import jwt

#: The single scope FCM needs. Deliberately not the broader
#: ``cloud-platform`` scope some examples use: a leaked assertion should
#: grant sending a push and nothing else.
_SCOPE: Final[str] = "https://www.googleapis.com/auth/firebase.messaging"

#: Google rejects an assertion whose lifetime exceeds an hour.
_ASSERTION_TTL_SECONDS: Final[int] = 3600

#: Re-mint this many seconds before the token actually expires, so a
#: request never leaves with a credential that dies in flight.
_REFRESH_MARGIN_SECONDS: Final[int] = 120

_DEFAULT_TOKEN_URI: Final[str] = "https://oauth2.googleapis.com/token"


class ServiceAccountError(Exception):
    """The service-account credential cannot be used.

    Raised for a malformed key or a refused exchange — both of which are
    configuration faults an operator has to fix, not conditions a retry
    resolves. The dispatch sweep logs it and leaves the notification
    unmarked rather than treating it as a dead device.
    """


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    client_email: str
    private_key: str
    token_uri: str
    project_id: str | None

    @classmethod
    def from_json(cls, raw: str) -> "ServiceAccount":
        """Parse the JSON key file Firebase hands out.

        Only the four fields that matter are read; the rest of the file
        (``type``, ``client_id``, the certificate URLs) is Google's own
        bookkeeping and is deliberately ignored rather than validated,
        so a new field appearing in the file cannot break dispatch.
        """
        try:
            data: dict[str, Any] = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise ServiceAccountError(
                "The FCM service-account credential is not valid JSON."
            ) from exc

        missing = [key for key in ("client_email", "private_key") if not data.get(key)]
        if missing:
            raise ServiceAccountError(
                f"The FCM service-account credential is missing {', '.join(missing)}. "
                "Use the JSON key file downloaded from the Firebase console verbatim."
            )
        return cls(
            client_email=str(data["client_email"]),
            # A key pasted through an environment variable routinely
            # arrives with literal backslash-n instead of real newlines,
            # and PEM parsing fails in a way that names neither the cause
            # nor the fix. Repairing it here costs one call and removes an
            # entire category of "push is silently broken" deployment.
            private_key=str(data["private_key"]).replace("\\n", "\n"),
            token_uri=str(data.get("token_uri") or _DEFAULT_TOKEN_URI),
            project_id=str(data["project_id"]) if data.get("project_id") else None,
        )


class ServiceAccountTokenProvider:
    """Mints and caches one service account's access tokens."""

    def __init__(self, account: ServiceAccount) -> None:
        self._account = account
        self._token: str | None = None
        self._expires_at: float = 0.0

    async def token(self, client: httpx.AsyncClient) -> str:
        """A usable access token, minted only when the cached one is
        spent. Takes the caller's HTTP client rather than owning one, so a
        dispatch run reuses a single connection pool throughout.
        """
        now = time.time()
        if self._token is not None and now < self._expires_at:
            return self._token

        assertion = self._signed_assertion(now)
        try:
            response = await client.post(
                self._account.token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            raise ServiceAccountError(f"Could not reach {self._account.token_uri}.") from exc

        if response.status_code != 200:
            # The response body is Google's, and can name the exact
            # problem ("invalid_grant" for a clock skew, a revoked key).
            # Worth carrying into the exception: an operator debugging
            # this has nothing else to go on.
            raise ServiceAccountError(
                f"Token exchange failed with HTTP {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ServiceAccountError("Token exchange returned no access_token.")

        expires_in = int(payload.get("expires_in") or _ASSERTION_TTL_SECONDS)
        self._token = str(token)
        self._expires_at = now + max(expires_in - _REFRESH_MARGIN_SECONDS, 0)
        return self._token

    def _signed_assertion(self, now: float) -> str:
        issued_at = int(now)
        claims = {
            "iss": self._account.client_email,
            "scope": _SCOPE,
            "aud": self._account.token_uri,
            "iat": issued_at,
            "exp": issued_at + _ASSERTION_TTL_SECONDS,
        }
        try:
            return str(jwt.encode(claims, self._account.private_key, algorithm="RS256"))
        except Exception as exc:  # noqa: BLE001 - any signing failure is the same fault
            raise ServiceAccountError(
                "Could not sign the assertion with the service-account private key. "
                "The key is malformed or is not an RSA private key."
            ) from exc


__all__ = ["ServiceAccount", "ServiceAccountError", "ServiceAccountTokenProvider"]
