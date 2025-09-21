from league.models import NotificationReceipt
from django.conf import settings

def notifications_context(request):
    if not request.user.is_authenticated:
        return {"notifications": [], "notif_count": 0}
    qs = (
        NotificationReceipt.objects
        .filter(user=request.user, read_at__isnull=True)
        .select_related("notification")
        .order_by("-notification__created_at")[:10]
    )
    return {
        "notifications": qs,
        "notif_count": qs.count()
    }

def sms_flags(request):
    return {
        "SMS_FEATURE_ENABLED": bool(getattr(settings, "ENABLE_SMS", False)),
        "SMS_PROVIDER": getattr(settings, "SMS_PROVIDER", "brevo"),
    }