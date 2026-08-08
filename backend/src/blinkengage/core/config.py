"""Application configuration.

All runtime configuration is sourced from environment variables (see
``.env.example`` at the repository root). No secrets are hard-coded.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from blinkengage.domain.learning_cluster import (
    DEFAULT_JOIN_THRESHOLD,
    DEFAULT_MERGE_THRESHOLD,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "Blink Engage"
    #: What this build is, for connectors that declare a minimum. Compared
    #: with ``VersionInfo.minimum_platform`` so a connector shipped ahead of
    #: its platform says so plainly rather than failing halfway through a
    #: customer's flow. Semantic, and the pre-release suffix is ignored when
    #: comparing — a connector requiring 1.0.0 is satisfied by 1.0.0-beta.5,
    #: or nothing could declare a minimum before the first stable release.
    platform_version: str = "1.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    # The externally-visible scheme+host this API is served at (no
    # trailing slash) — used to reconstruct the *exact* webhook URL for
    # providers whose signature scheme signs the full URL (e.g. Twilio
    # SMS, see docs/architecture/sms.md). Deliberately a fixed setting
    # rather than trusting X-Forwarded-Proto/Host from the request: this
    # app's backend port is reachable directly (not only via nginx), so
    # trusting client-supplied forwarded headers for signature-relevant
    # URL reconstruction would be spoofable.
    public_base_url: str = "http://localhost"

    # --- Security ---
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    # How long a CSAT survey link stays valid after a conversation closes
    # (see docs/architecture/reports-analytics.md) — long enough for a
    # customer to get to it, unlike the much shorter access/refresh token
    # lifetimes above, since this token is emailed/messaged to a customer
    # rather than kept alive by an active session.
    csat_token_expire_days: int = 14
    # Encrypts secrets-at-rest (e.g. channel provider credentials — see
    # docs/architecture/channels.md). Deliberately separate from
    # jwt_secret_key so rotating one never invalidates the other.
    credentials_encryption_key: str = Field(..., min_length=32)

    # --- CORS ---
    # NoDecode: pydantic-settings otherwise tries to JSON-decode list-typed env
    # vars before our validator runs, which rejects a plain comma-separated string.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- Database ---
    database_url: str = Field(..., description="Async SQLAlchemy DSN")
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- RabbitMQ / Celery ---
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- Domain event bus (see docs/architecture/event-bus.md) ---
    events_exchange_name: str = "blinkengage.events"
    events_relay_batch_size: int = 100
    # Dead-letter guard: a row that fails this many times is excluded from
    # future claim_batch() calls (but not deleted) so one poisoned event
    # can't starve the relay's FIFO batch of every healthy event behind it
    # — see EventOutboxRepository.claim_batch's docstring for the real
    # incident this guards against.
    events_relay_max_attempts: int = 10

    # --- Object storage (MinIO / S3-compatible) ---
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_attachments: str = "blinkengage-attachments"
    s3_use_ssl: bool = False

    # --- Attachments (see docs/architecture/conversations.md) ---
    attachment_max_size_bytes: int = 25 * 1024 * 1024  # 25 MiB
    attachment_allowed_content_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "application/pdf",
            "text/plain",
            "text/csv",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            # --- Audio ---
            # Voice notes are among the most common things a customer sends
            # on WhatsApp, and every one of them was being **silently
            # dropped**: the ingest consumer validates against this same
            # list, so an unlisted type meant the agent simply never saw the
            # message. `audio/ogg` with an opus codec is exactly what
            # WhatsApp sends.
            "audio/mpeg",
            "audio/mp4",
            "audio/aac",
            "audio/ogg",
            "audio/opus",
            "audio/wav",
            "audio/x-wav",
            "audio/webm",
            # --- Video ---
            # `video/quicktime` is what an iPhone sends. Note the 25 MiB
            # ceiling above still applies, and phone video routinely exceeds
            # it — see docs/architecture/conversations.md.
            "video/mp4",
            "video/webm",
            "video/quicktime",
        ]
    )

    # --- Company logo upload (see docs/architecture/administration.md) ---
    # Deliberately its own, tighter limit/allow-list rather than reusing
    # attachment_max_size_bytes/attachment_allowed_content_types — a logo
    # is always a raster image, never a document, and is rendered at a
    # small fixed size everywhere it appears.
    logo_max_size_bytes: int = 2 * 1024 * 1024  # 2 MiB
    logo_allowed_content_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["image/png", "image/jpeg", "image/webp"]
    )

    # --- AI Engine (see docs/architecture/ai-engine.md) ---
    # Platform-level, not per-company: matches how these settings were
    # already structured before this milestone (env-configured, not a
    # ChannelConfig-style per-company credential row) — simpler, and a
    # per-company "bring your own AI provider" model can be layered on
    # later without a breaking change if a real enterprise need for it
    # emerges.
    ai_provider: Literal[
        "openai",
        "claude",
        "gemini",
        "azure_openai",
        "ollama",
        "mistral",
        "groq",
        "deepseek",
        "disabled",
    ] = "disabled"
    ai_model: str | None = None
    ai_default_max_tokens: int = 1000
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    ollama_base_url: str = "http://localhost:11434"
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # Azure OpenAI has no sensible universal default for the resource
    # endpoint/deployment name (both account-specific) — left unset like
    # openai_api_key/anthropic_api_key, deliberately not env-guessable.
    azure_openai_api_key: str | None = None
    azure_openai_base_url: str | None = None
    azure_openai_deployment_name: str | None = None
    azure_openai_api_version: str = "2024-02-15-preview"
    mistral_api_key: str | None = None
    mistral_base_url: str = "https://api.mistral.ai/v1"
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # --- Semantic retrieval (Company Intelligence Engine, stage 1) ---
    #
    # Selected independently of `ai_provider`, and that is the normal case
    # rather than an edge one: Anthropic publishes no embedding endpoint,
    # so every company reasoning with Claude must embed somewhere else.
    # "disabled" is the shipped default — a fresh deployment keeps the
    # existing substring search until an operator turns semantic retrieval
    # on, exactly as `ai_provider` defaults to off.
    embedding_provider: Literal["openai", "ollama", "hashing", "disabled"] = "disabled"
    embedding_model: str | None = None
    # `embedding_api_key`/`embedding_base_url` fall back to the matching
    # `openai_*`/`ollama_*` setting when unset, so a deployment already
    # using OpenAI for completions does not restate its key to turn
    # embeddings on — but a deployment that wants to embed through a
    # different account or a private gateway can say so without disturbing
    # the completion provider.
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    # **A schema commitment, not a preference.** The stored vector column
    # is created at exactly this width and an HNSW index requires a fixed
    # one, so changing this requires the migration to be rewritten and
    # every row re-embedded. 1536 fits text-embedding-3-small natively and
    # text-embedding-3-large truncated (its `dimensions` parameter), which
    # covers the realistic hosted choices without a schema change; bge-m3
    # via Ollama is 1024 and does need one.
    embedding_dimensions: int = 1536
    # How many chunks are sent to the provider per request. Every hosted
    # provider charges and rate-limits per request, so this is a real cost
    # lever, not a tuning detail.
    embedding_batch_size: int = 64
    # Articles re-indexed per sweep. Bounded so one enormous backfill
    # cannot monopolise the worker or the provider's rate limit; the sweep
    # simply picks up where it left off on its next run.
    embedding_index_batch_size: int = 25
    embedding_index_max_attempts: int = 5
    # Retrieval candidates pulled from each retriever *before* fusion.
    # Larger than the caller's limit on purpose: fusion can only rank what
    # it was given, and a retriever that returns exactly `limit` rows
    # contributes nothing the other could not have found alone.
    retrieval_candidate_pool: int = 50

    # --- Memory Platform (Company Intelligence Engine, stage 2) ---
    #
    # How often a fact's confidence is re-evaluated. Decay is *computed*,
    # not applied, so this is how stale a confidence number is allowed to
    # be rather than how fast memory fades — the fade is a function of
    # time and is correct the moment it is next read.
    memory_recompute_interval_seconds: int = 21600
    # How often the sweep runs, and how long a full pass over the corpus
    # may take. The batch is *derived* from these and the row count rather
    # than fixed: a constant batch cannot keep up with a growing corpus,
    # and the failure is silent — retrieval keeps ranking on a confidence
    # number that quietly becomes years stale.
    memory_sweep_interval_seconds: int = 3600
    memory_target_pass_hours: int = 24
    #: Floor and ceiling on the derived batch. The ceiling stops one
    #: enormous tenant making a single run unbounded.
    memory_decay_batch_size: int = 500
    memory_decay_batch_max: int = 20000
    #: Companies served per run. The budget is split between them, so a
    #: large tenant cannot starve small ones.
    memory_sweep_companies_per_run: int = 50
    #: Circuit breaker: a fact that fails this many recomputes stops being
    #: claimed and stays visible with its error.
    memory_recompute_max_attempts: int = 5
    memory_purge_batch_size: int = 500
    # Confidence history is the fastest-growing table here (one row per
    # fact per sweep) and its value is entirely in the recent tail — long
    # enough to explain a curve, not long enough to become a second copy
    # of the fact table.
    memory_confidence_history_days: int = 180

    # --- Learning Platform (Company Intelligence Engine, stage 3) ---
    #
    # Phase 1 is observe-only: no clustering, no detection, no candidates,
    # and no model calls. These bound the settle sweep, which promotes
    # observations whose outcome can no longer change.
    learning_settle_batch_size: int = 500
    #: How often the settle sweep runs, and — the reason it is a setting
    #: rather than a literal in the beat schedule — the width of the
    #: window a run claims. The two must agree: a run row is a *window*,
    #: so a window wider than the cadence means most sweeps record
    #: nothing at all, and the failures of the ones that recorded nothing
    #: are invisible on the health dashboard. Found in phase 1.5
    #: validation, where three sweeps in four left no trace.
    learning_settle_interval_seconds: int = 900

    # --- phase 2: clustering and pattern detection ---------------------
    #
    # Nothing here costs money either: clustering is lexical and the
    # statistics are arithmetic. What these bound is *work per sweep*, so
    # one large tenant cannot turn a scheduled job into an outage.
    #
    #: How often clusters are rebuilt, and the width of the window a
    #: cluster run claims — one setting for both, for the reason
    #: ``learning_settle_interval_seconds`` documents.
    learning_cluster_interval_seconds: int = 3600
    #: Observations read per company per clustering pass.
    learning_cluster_batch_size: int = 5000
    #: Companies served per sweep. The budget is split between them in id
    #: order, so a large tenant cannot starve small ones.
    learning_cluster_companies_per_run: int = 50
    #: How far back a sweep looks for observations to place. Longer than
    #: the cadence on purpose: an observation that settles late must still
    #: be picked up, and re-reading an already-clustered one costs a
    #: single indexed lookup that finds it and skips it.
    learning_cluster_lookback_days: int = 14
    #: Cosine similarity above which an observation joins a cluster, and
    #: above which two clusters fold together. Settings rather than only
    #: constants because the right value is **corpus-dependent**: phase
    #: 2.5 measured the usable band at 0.15–0.20 across five synthetic
    #: corpus shapes, and an installation whose conversations are longer
    #: or more repetitive will sit elsewhere in it. Tuning must not
    #: require a deploy.
    #:
    #: Changing either invalidates existing clusters — bump
    #: ``CLUSTER_ALGORITHM_VERSION`` alongside, so the new grouping is a
    #: parallel generation that can be compared against the old one.
    learning_cluster_join_threshold: float = DEFAULT_JOIN_THRESHOLD
    learning_cluster_merge_threshold: float = DEFAULT_MERGE_THRESHOLD
    #: Trend windows, and their width. Eight weekly windows is long enough
    #: for two seasonal cycles and short enough that last spring does not
    #: define what is normal now.
    learning_trend_windows: int = 8
    learning_trend_window_days: int = 7
    #: How often trends and anomalies are recomputed. Daily rather than
    #: hourly, and that is a statistical decision rather than a cost one:
    #: testing the same weekly windows twenty-four times a day would be
    #: multiple testing through the back door, and would defeat the
    #: correction the detector applies at the front.
    learning_analysis_interval_seconds: int = 86400
    #: How long an observation's outcome may still change. CSAT settles it
    #: immediately; this is the wait for the ones nobody rates, which is
    #: most of them. Deliberately far shorter than the 14-day CSAT token
    #: life — waiting for the last possible response would make every
    #: observation two weeks stale.
    learning_settle_hours: int = 72

    # --- Operational retention ------------------------------------------
    #
    # Both tables are telemetry about the platform running, not records
    # the platform is for. Unpruned they grow forever — scheduler_runs at
    # roughly a million rows a year, event_outbox on the write path of
    # every domain event.
    #
    # Thirty days is long enough to investigate an incident from and to
    # cover a monthly review; ninety would be a quarter of retained data
    # nobody reads. Audit logs are deliberately excluded from all of this.
    scheduler_run_retention_days: int = 30
    #: Dispatched outbox rows only. An undispatched row is work still
    #: owed, however old, and deleting one would silently drop an event.
    outbox_retention_days: int = 7
    #: Rows per delete batch. Batched so the statement never holds a long
    #: lock on a table the write path depends on.
    operational_retention_batch_size: int = 5000

    # --- Provider apps for channel OAuth (see
    # docs/architecture/channel-connectors.md) ---
    #
    # Unset by default, and that is a fully supported state rather than a
    # broken one: an installation with no Meta app offers the guided manual
    # path instead of OAuth, and the connector's resolved capabilities say
    # so. Obtaining these is weeks of app review, not an afternoon, so the
    # product cannot assume they exist.
    #
    # The floor, not the source of truth — the encrypted `meta_app` platform
    # settings group overrides them, so a self-hosted administrator can
    # supply their own app without redeploying. Same precedent as the mail
    # relay: stored settings override the environment, never replace it.
    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    #: Facebook Login for Business uses a configuration id rather than a raw
    #: scope list. One per template is the cleanest mapping.
    meta_login_config_id: str | None = None
    #: The token Meta echoes back when verifying the installation-wide
    #: webhook. One value for the whole app, because under a shared app the
    #: callback is configured once on the app and not per channel.
    meta_webhook_verify_token: str | None = None

    # --- Payments (see docs/architecture/billing.md) ---
    # Unset by default: a deployment without PayPal credentials simply
    # has no PayPal provider registered, rather than one that fails at
    # the first charge. Manual (bank transfer) is always available.
    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    # PayPal's own id for the webhook subscription. Without it inbound
    # webhooks cannot be verified and are refused — deliberately, since
    # an unverified webhook can mark an invoice paid.
    paypal_webhook_id: str | None = None
    paypal_sandbox: bool = True
    paypal_brand_name: str = "Blink Engage"
    # Where PayPal sends the customer back after approving or abandoning
    # a payment. The invoice id is appended as a query parameter.
    payment_return_url: str = "http://localhost:5173/billing/payment/complete"
    payment_cancel_url: str = "http://localhost:5173/billing/payment/cancelled"

    # --- Rate limiting ---
    rate_limit_per_minute: int = 60
    # Tighter than the generic limit above, and per-*user* rather than
    # per-IP (see api/deps.py::enforce_ai_rate_limit) — every AI Engine
    # call has a real external cost, unlike auth/webchat, which only cost
    # a DB round trip.
    ai_rate_limit_per_minute: int = 20
    # Per-user, like the AI limit above — "Test Connection" makes the
    # server originate a real outbound connection to an operator-chosen
    # host/port on every call (see channel-integration-spec.md's security
    # review), so it gets the same treatment as any other real-network-
    # cost action, not the generic per-IP limit.
    channel_test_connection_rate_limit_per_minute: int = 20
    # Same reasoning, applied to ERP "Test Connection" (see
    # docs/architecture/company-onboarding.md).
    erp_test_connection_rate_limit_per_minute: int = 20
    # Global Search (see docs/architecture/global-search.md) — per-user,
    # like the AI/test-connection limits above. One search fans out
    # across up to nine tables, each a leading-wildcard ILIKE that can't
    # use an index, so this backstops the frontend's debounce rather
    # than trusting it. Higher than those limits because typeahead is a
    # genuinely interactive affordance, not an occasional action.
    search_rate_limit_per_minute: int = 60

    # --- Web Chat (see docs/architecture/web-chat.md) ---
    webchat_session_ttl_hours: int = 720  # 30 days, sliding

    # --- Platform/system email (see docs/architecture/notifications.md) ---
    # Distinct from a company's per-channel EmailProvider credentials
    # (M15, ChannelConfig.credentials) — this is the platform's own
    # outbound email for transactional/system notifications (e.g. "you
    # were assigned a conversation"), which must work even for a company
    # that hasn't configured any customer-facing email channel.
    # --- Push notifications (see docs/architecture/notifications.md) ---
    # The JSON key file from the Firebase console, verbatim. Absent means
    # push is not configured: device registration still works and
    # notifications are still created, nothing is sent, and no
    # notification is marked as pushed — so configuring this later starts
    # delivering without a redeploy.
    fcm_service_account_json: str | None = None
    # Optional: the key file already carries `project_id`, and this only
    # exists for a deployment whose service account sends on behalf of a
    # different Firebase project.
    fcm_project_id: str | None = None
    # How old a notification may be and still be worth pushing. A push is
    # an interruption that claims to be current — "a customer is waiting"
    # arriving forty minutes late is worse than not arriving, since the
    # conversation has usually moved on. This window is also what bounds
    # retries: past it, a notification is marked as decided-upon and
    # skipped rather than retried forever, which is what stops a backlog
    # (a provider outage, or push being switched on for the first time)
    # from firing every stale alert at once.
    push_stale_after_minutes: int = 15

    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_address: str = "notifications@blinkengage.local"
    smtp_from_name: str = "Blink Engage"

    # --- Release / version metadata (see docs/architecture/release-changelog.md) ---
    # Path (relative to CWD, or absolute) to the Keep a Changelog file
    # parsed by ``core.changelog`` to derive the running application's
    # user-facing version/release-channel — see ``api/v1/endpoints/version.py``.
    # Overridden in tests to point at a small, stable test fixture instead
    # of the real, ever-growing repo-root CHANGELOG.md.
    changelog_path: str = "CHANGELOG.md"
    #: The Arabic edition, served to Arabic readers by ``GET /releases``.
    #:
    #: A parallel file rather than translations inside the English one:
    #: the parser, the running version and the version-consistency guard
    #: all read ``changelog_path``, and interleaving a second language
    #: there would put all three at the mercy of a translator. A release
    #: missing from this file falls back to its English entry, so a
    #: late translation shows English rather than nothing.
    changelog_path_ar: str = "CHANGELOG.ar.md"
    #: The product guide, served to the application by ``GET /guide`` so
    #: help inside the product and the file people read in review are the
    #: same text. Re-typing it into the frontend catalogue would create a
    #: copy, and the copy that drifts is the one customers read.
    guide_path: str = "docs/guides/blink-engage-user-guide.md"
    guide_path_ar: str = "docs/guides/blink-engage-user-guide.ar.md"
    # Populated by the CI/CD build pipeline (see .github/workflows/ci.yml);
    # left at their defaults for local `docker compose` development, where
    # there is no build pipeline to inject them.
    git_commit: str = "unknown"
    build_timestamp: str = "unknown"
    docker_image_tag: str = "development"

    @field_validator(
        "cors_allow_origins",
        "attachment_allowed_content_types",
        "logo_allowed_content_types",
        mode="before",
    )
    @classmethod
    def _split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Re-exported for typing convenience where a concrete DSN type is useful.
__all__ = ["Settings", "get_settings", "PostgresDsn", "RedisDsn"]
