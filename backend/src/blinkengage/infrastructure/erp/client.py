"""``ErpNextClient`` — the one concrete ``ErpClient`` implementation, a
thin REST wrapper over Frappe/ERPNext's generic
``/api/resource/<doctype>`` API. See
``docs/architecture/erp-integration.md``.

Auth is Frappe's own token scheme: ``Authorization: token <api_key>:
<api_secret>`` — no OAuth dance, no session cookies, matching how every
other HTTP-based provider in this codebase (WhatsApp/Telegram/OpenAI/...)
authenticates with a static credential rather than a login flow.

``list_records`` filters on a ``"customer"`` field by default — the
field name Frappe's own Sales Invoice/Sales Order/Payment Entry doctypes
use out of the box. Some doctypes (e.g. a customized Quotation or a
support-ticket doctype) may use a different field
(``party_name``, ``raised_by``, ...); this is a known, documented
limitation rather than an attempt to special-case every possible ERPNext
customization — callers needing a different filter field can extend this
method's ``customer_field`` parameter without a breaking change.
"""

import httpx


class ErpNextClient:
    def __init__(self, *, base_url: str, api_key: str, api_secret: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"token {api_key}:{api_secret}",
            "Content-Type": "application/json",
        }

    async def create_customer(self, *, name: str, email: str | None, phone: str | None) -> str:
        payload: dict[str, object] = {"customer_name": name, "customer_type": "Individual"}
        if email:
            payload["email_id"] = email
        if phone:
            payload["mobile_no"] = phone

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/api/resource/Customer",
                headers=self._headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return str(data["data"]["name"])

    async def list_records(
        self, *, doctype: str, customer_name: str, customer_field: str = "customer"
    ) -> list[dict[str, object]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/api/resource/{doctype}",
                headers=self._headers,
                params={
                    "filters": f'[["{customer_field}","=","{customer_name}"]]',
                    "limit_page_length": 0,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return list(data.get("data", []))

    async def health_check(self) -> tuple[bool, str | None]:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._base_url}/api/method/frappe.auth.get_logged_user",
                    headers=self._headers,
                    timeout=5,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return False, str(exc)
        return True, None
