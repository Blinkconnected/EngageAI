#!/usr/bin/env python3
"""Seed a demo company, agent, channels, and two live customer
conversations for manually validating the product end to end.
See docs/deployment/demo-guide.md for the full walkthrough this feeds.

Usage:
    backend/.venv/bin/python scripts/seed_demo_data.py

Safe to re-run: if the demo company's owner email is already registered,
registration is skipped (existing data is left alone, not duplicated) and
the script logs in as that owner instead before continuing. Requires
httpx and websockets (both already present in backend/.venv).
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
import websockets

BASE_URL = "http://localhost"
API_BASE = f"{BASE_URL}/api/v1"
WS_BASE = "ws://localhost"

OWNER_EMAIL = "owner@blinkdemo.io"
OWNER_PASSWORD = "DemoPass123!"
COMPANY_NAME = "Blink Demo"
AGENT_EMAIL = "agent@blinkdemo.io"
AGENT_PASSWORD = "AgentPass123!"


async def get_or_create_owner_token(client: httpx.AsyncClient) -> str:
    register = await client.post(
        f"{API_BASE}/auth/register",
        json={
            "company_name": COMPANY_NAME,
            "owner_full_name": "Demo Owner",
            "owner_email": OWNER_EMAIL,
            "owner_password": OWNER_PASSWORD,
        },
    )
    if register.status_code == 201:
        print(f"Registered company '{COMPANY_NAME}' with owner {OWNER_EMAIL}")
        return register.json()["tokens"]["access_token"]

    print(
        f"'{COMPANY_NAME}' already exists (owner email already registered) — logging in instead"
    )
    login = await client.post(
        f"{API_BASE}/auth/login",
        json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
    )
    login.raise_for_status()
    return login.json()["access_token"]


async def ensure_agent(client: httpx.AsyncClient, headers: dict) -> None:
    existing = await client.get(
        f"{API_BASE}/agents", headers=headers, params={"page_size": 100}
    )
    existing.raise_for_status()
    if any(a["email"] == AGENT_EMAIL for a in existing.json()["items"]):
        print(f"Agent {AGENT_EMAIL} already exists — skipping")
        return
    response = await client.post(
        f"{API_BASE}/agents",
        headers=headers,
        json={
            "email": AGENT_EMAIL,
            "full_name": "Alex Agent",
            "password": AGENT_PASSWORD,
            "title": "Support Agent",
        },
    )
    response.raise_for_status()
    print(f"Created agent {AGENT_EMAIL}")


async def ensure_channel(
    client: httpx.AsyncClient,
    headers: dict,
    channel_type: str,
    display_name: str,
    credentials: dict,
) -> str:
    existing = await client.get(
        f"{API_BASE}/channel-configs", headers=headers, params={"page_size": 100}
    )
    existing.raise_for_status()
    match = next(
        (c for c in existing.json()["items"] if c["display_name"] == display_name), None
    )
    if match:
        print(f"Channel '{display_name}' already exists — skipping")
        return match["id"]

    response = await client.post(
        f"{API_BASE}/channel-configs",
        headers=headers,
        json={
            "channel_type": channel_type,
            "display_name": display_name,
            "credentials": credentials,
        },
    )
    response.raise_for_status()
    channel_id = response.json()["id"]
    print(f"Connected channel '{display_name}' ({channel_id})")
    return channel_id


async def simulate_message(
    client: httpx.AsyncClient, channel_config_id: str, body: str
) -> str:
    session = await client.post(
        f"{API_BASE}/web-chat/{channel_config_id}/sessions", json={}
    )
    session.raise_for_status()
    data = session.json()
    url = f"{WS_BASE}/api/v1/web-chat/ws/{channel_config_id}?token={data['session_token']}"
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.send(json.dumps({"body": body}))
        await asyncio.sleep(0.3)
    return data["customer_id"]


async def ensure_demo_conversations(
    client: httpx.AsyncClient, headers: dict, webchat_id: str
) -> None:
    existing = await client.get(
        f"{API_BASE}/conversations", headers=headers, params={"page_size": 100}
    )
    existing.raise_for_status()
    total = existing.json()["total"]
    if total > 0:
        print(f"{total} conversation(s) already exist — skipping message simulation")
        return

    customer1 = await simulate_message(
        client,
        webchat_id,
        "Hi, I ordered a laptop last week and it hasn't arrived yet. Can you help?",
    )
    customer2 = await simulate_message(
        client, webchat_id, "Hello! Do you offer international shipping to Canada?"
    )

    await client.patch(
        f"{API_BASE}/customers/{customer1}",
        headers=headers,
        json={
            "full_name": "Priya Sharma",
            "email": "priya.sharma@example.com",
            "phone": "+1-555-0142",
            "tags": ["vip"],
        },
    )
    await client.patch(
        f"{API_BASE}/customers/{customer2}",
        headers=headers,
        json={"full_name": "Marco Rossi", "email": "marco.rossi@example.com"},
    )
    print("Seeded 2 demo conversations (Priya Sharma, Marco Rossi)")


async def main() -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        access_token = await get_or_create_owner_token(client)
        headers = {"Authorization": f"Bearer {access_token}"}

        await ensure_agent(client, headers)
        await ensure_channel(
            client,
            headers,
            "whatsapp",
            "Support WhatsApp",
            {
                "phone_number_id": "demo-phone-id",
                "access_token": "demo-access-token",
                "verify_token": "demo-verify-token",
            },
        )
        webchat_id = await ensure_channel(
            client, headers, "web_chat", "Website Chat", {}
        )
        await ensure_demo_conversations(client, headers, webchat_id)

    print("\nDemo environment ready.")
    print(f"  URL:      {BASE_URL}")
    print(f"  Owner:    {OWNER_EMAIL} / {OWNER_PASSWORD}")
    print(f"  Agent:    {AGENT_EMAIL} / {AGENT_PASSWORD}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except httpx.HTTPStatusError as exc:
        print(
            f"Request failed: {exc.request.url} -> {exc.response.status_code} {exc.response.text}",
            file=sys.stderr,
        )
        sys.exit(1)
