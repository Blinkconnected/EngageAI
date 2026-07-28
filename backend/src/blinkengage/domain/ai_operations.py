"""Canonical names for the ``operation`` dimension on AI usage rollups.

``AiDailyStats.operation``/``AgentAiDailyStats.operation`` carry two
kinds of value: the AI capability names ``AiService`` publishes on
``ai.completed`` (``suggest_reply``, ``summarize_conversation``, …), and
the synthetic ``autopilot_<trigger>`` names the reporting consumer
derives from ``conversation.autopilot_replied``. The latter are strings
assembled in one place (the consumer) and matched in another (the
reporting repository's per-agent breakdown), which is exactly the kind
of pair that silently drifts — so the prefix and the derivation live
here, in the domain, where both layers may import them.
"""

AUTOPILOT_OPERATION_PREFIX = "autopilot_"


def autopilot_operation(trigger: str) -> str:
    """``"sla"`` -> ``"autopilot_sla"``. Takes the raw trigger string
    (``AutopilotTrigger``'s value) rather than the enum so the reporting
    consumer, which only ever sees the serialized event payload, doesn't
    have to reach into the application layer to re-parse it."""
    return f"{AUTOPILOT_OPERATION_PREFIX}{trigger}"


AUTOPILOT_AGENT_REQUEST_OPERATION = autopilot_operation("agent_request")
AUTOPILOT_SLA_OPERATION = autopilot_operation("sla")
AUTOPILOT_NEW_MESSAGE_OPERATION = autopilot_operation("new_message")
