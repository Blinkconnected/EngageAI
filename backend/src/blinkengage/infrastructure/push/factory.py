"""Builds the configured push sender, or none at all. See
``docs/architecture/notifications.md``.

Returns ``None`` when push is not configured, rather than a no-op sender
that silently accepts everything. The dispatch sweep checks for ``None``
and does nothing — including not marking notifications as pushed — so
that configuring credentials later starts working immediately, and so
that "push is not set up" and "push is set up and failing" can never look
alike in the logs.
"""

from blinkengage.core.config import Settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.push import PushSender
from blinkengage.infrastructure.push.fcm import FcmPushSender
from blinkengage.infrastructure.push.service_account import ServiceAccount, ServiceAccountError

logger = get_logger(__name__)


def build_push_sender(settings: Settings) -> PushSender | None:
    if not settings.fcm_service_account_json:
        return None

    try:
        account = ServiceAccount.from_json(settings.fcm_service_account_json)
    except ServiceAccountError as exc:
        # Configured but unusable is a louder problem than not configured:
        # somebody intended push to work. Logged at error and treated as
        # unconfigured, because a sender that cannot sign anything has
        # nothing to contribute.
        logger.error("push_credentials_invalid", error=str(exc))
        return None

    # The project id lives in the key file, so requiring it separately
    # would be asking for something already supplied. The explicit
    # setting stays available to override it, for a deployment whose
    # service account sends on behalf of a different project.
    project_id = settings.fcm_project_id or account.project_id
    if not project_id:
        logger.error(
            "push_project_id_missing",
            detail="Set FCM_PROJECT_ID, or use a service-account file containing project_id.",
        )
        return None

    return FcmPushSender(project_id=project_id, account=account)


__all__ = ["build_push_sender"]
