# --- Event key constants (single source of truth) ---
SUBPLAN_CREATED_FOR_PLAYER   = "SUBPLAN_CREATED_FOR_PLAYER"
SUBPLAN_UPDATED_FOR_PLAYER   = "SUBPLAN_UPDATED_FOR_PLAYER"
SUBPLAN_CANCELLED_FOR_PLAYER = "SUBPLAN_CANCELLED_FOR_PLAYER"
RESULT_POSTED_FOR_PLAYER     = "RESULT_POSTED_FOR_PLAYER"
LINEUP_PUBLISHED_FOR_PLAYER  = "LINEUP_PUBLISHED_FOR_PLAYER"

# Optional: central registry (not enforced, but handy for linting/autocomplete)
SUPPORTED_EVENTS = {
    SUBPLAN_CREATED_FOR_PLAYER,
    SUBPLAN_UPDATED_FOR_PLAYER,
    SUBPLAN_CANCELLED_FOR_PLAYER,
    RESULT_POSTED_FOR_PLAYER,
    LINEUP_PUBLISHED_FOR_PLAYER,
}

from ..models import Notification, NotificationReceipt

def notify(event, *, season=None, fixture=None, players=None, users=None, title="", body="", url=""):
    """Create a Notification and fan out NotificationReceipts.

    Args:
        event (str): One of the event key constants above.
        season (Season|None)
        fixture (Fixture|None)
        players (Iterable[Player]|None): recipients resolved via their linked user.
        users (Iterable[User]|None): recipients as users.
        title (str)
        body (str)
        url (str): optional deep link.
    Returns:
        Notification: the created notification object.
    """
    n = Notification.objects.create(
        event=event,
        season=season,
        fixture=fixture,
        title=title,
        body=body,
        url=url
    )
    audience_users = set(users or [])
    if players:
        audience_users |= {p.user for p in players if getattr(p, 'user_id', None)}
    if not audience_users:
        # No recipients; keep the Notification record for audit/history
        return n
    receipts = [NotificationReceipt(notification=n, user=u) for u in audience_users]
    NotificationReceipt.objects.bulk_create(receipts)
    return n