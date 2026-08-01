from datetime import date
from uuid import UUID

from pydantic import BaseModel


class ConversationStatsRowResponse(BaseModel):
    stat_date: date
    channel_type: str
    opened: int
    closed: int
    resolved: int
    first_response_breached: int
    resolution_breached: int


class ExecutiveDashboardResponse(BaseModel):
    date_from: date
    date_to: date
    conversations_opened: int
    conversations_closed: int
    conversations_resolved: int
    first_response_breached: int
    resolution_breached: int
    top_channels: list[ConversationStatsRowResponse]
    csat_average_rating: float | None
    csat_response_count: int
    ai_calls_total: int
    active_agent_count: int


class AgentDashboardResponse(BaseModel):
    agent_id: UUID
    date_from: date
    date_to: date
    conversations_assigned: int
    conversations_closed: int
    messages_sent: int


class LiveAgentCountsResponse(BaseModel):
    online: int
    away: int
    busy: int
    offline: int


class LiveConversationCountsResponse(BaseModel):
    #: Alive and not waiting on the customer. Spans four statuses now, which
    #: is why the two new fields below exist — this one can no longer tell
    #: "nobody has picked it up" from "somebody is on it".
    open: int
    pending: int
    #: In a queue, nobody working it. What a supervisor means by "waiting".
    waiting: int = 0
    #: Somebody is working it right now.
    in_progress: int = 0
    resolved: int
    closed: int
    unassigned: int
    total: int
    active: int
    #: Active (open/pending) conversations currently past an SLA target —
    #: a live "needs attention right now" figure, distinct from the
    #: retrospective, date-ranged breach counts on `GET /reports/sla`.
    sla_breached: int


class LiveQueueDepthResponse(BaseModel):
    queue_id: UUID
    queue_name: str
    department_id: UUID | None
    department_name: str | None
    open_conversations: int
    waiting_count: int
    assigned_count: int
    # P3.14 — waiting/picked/active/resolved/closed queue stages, split
    # out of assigned_count/throughput_24h (both kept for compatibility;
    # see LiveQueueMetrics's docstrings for the exact derivation).
    picked_count: int
    active_count: int
    avg_wait_seconds: float | None
    longest_wait_seconds: float | None
    pickup_avg_seconds_24h: float | None
    abandoned_count_24h: int
    sla_breached_count: int
    throughput_24h: int
    resolved_24h: int
    closed_24h: int


class AgentWorkloadResponse(BaseModel):
    agent_id: UUID
    agent_name: str
    open_count: int
    pending_count: int
    total_count: int


class LiveDashboardResponse(BaseModel):
    agents: LiveAgentCountsResponse
    conversations: LiveConversationCountsResponse
    queues: list[LiveQueueDepthResponse]
    agent_workload: list[AgentWorkloadResponse]


class AgentPerformanceRowResponse(BaseModel):
    agent_id: UUID
    agent_name: str
    conversations_assigned: int
    conversations_closed: int
    messages_sent: int


class QueueStatsRowResponse(BaseModel):
    queue_id: UUID
    queue_name: str
    conversations_entered: int
    sla_breached: int


class SlaReportResponse(BaseModel):
    date_from: date
    date_to: date
    first_response_breached: int
    resolution_breached: int
    conversations_opened: int
    by_queue: list[QueueStatsRowResponse]


class CsatDailyRowResponse(BaseModel):
    stat_date: date
    response_count: int
    average_rating: float | None


class CsatAgentRowResponse(BaseModel):
    agent_id: UUID
    agent_name: str
    response_count: int
    average_rating: float | None


class CsatReportResponse(BaseModel):
    date_from: date
    date_to: date
    response_count: int
    average_rating: float | None
    daily_trend: list[CsatDailyRowResponse]
    by_agent: list[CsatAgentRowResponse]


class AiOperationRowResponse(BaseModel):
    operation: str
    calls: int


class AiAgentUsageRowResponse(BaseModel):
    agent_id: UUID
    agent_name: str
    total_calls: int
    #: Autopilot replies this agent explicitly asked for.
    autopilot_agent_requests: int
    #: Autopilot replies that fired automatically on this agent's
    #: conversations because an SLA target was slipping — nobody asked
    #: for them, so they measure AI covering for the agent rather than
    #: the agent choosing to use AI.
    autopilot_sla_triggers: int


class AiUsageBucketResponse(BaseModel):
    #: First day of the bucket at whatever granularity was requested, so
    #: one field labels the x-axis for daily, weekly and monthly alike.
    bucket_start: date
    calls: int


class AiUsageReportResponse(BaseModel):
    by_operation: list[AiOperationRowResponse]
    by_agent: list[AiAgentUsageRowResponse]
    trend: list[AiUsageBucketResponse]
    total_calls: int
