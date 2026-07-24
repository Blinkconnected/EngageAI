#!/usr/bin/env python3
"""Simulate a customer sending a message over the Web Chat channel, so you
can watch a conversation arrive live in the Inbox while the app is open in
a browser — there's no embeddable customer-facing chat widget UI built yet
(only the backend WebSocket gateway), so this stands in for one.

Usage (new customer, starts a new conversation):
    python scripts/simulate_customer_message.py \
        --channel-config-id <web_chat channel config id> \
        --message "Hi, is anyone there?"

Usage (continue an existing conversation as the same customer):
    python scripts/simulate_customer_message.py \
        --channel-config-id <web_chat channel config id> \
        --session-token <token printed by a previous run> \
        --message "Following up on my last message"

Requires the `websockets` package (already present in backend/.venv):
    backend/.venv/bin/python scripts/simulate_customer_message.py ...
"""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx
import websockets


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost", help="Base URL (nginx)")
    parser.add_argument("--channel-config-id", required=True, help="Web Chat channel config id")
    parser.add_argument("--session-token", default=None, help="Reuse an existing customer session")
    parser.add_argument("--message", required=True, help="Message body to send")
    args = parser.parse_args()

    api_base = f"{args.base_url}/api/v1"
    ws_base = args.base_url.replace("http://", "ws://").replace("https://", "wss://")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{api_base}/web-chat/{args.channel_config_id}/sessions",
            json={"session_token": args.session_token} if args.session_token else {},
        )
        response.raise_for_status()
        session = response.json()

    url = (
        f"{ws_base}/api/v1/web-chat/ws/{args.channel_config_id}"
        f"?token={session['session_token']}"
    )
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.send(json.dumps({"body": args.message}))
        await asyncio.sleep(0.3)

    print(f"Sent as customer_id={session['customer_id']}")
    print("Session token (reuse with --session-token to continue this conversation):")
    print(session["session_token"])


if __name__ == "__main__":
    asyncio.run(main())
