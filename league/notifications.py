# league/notifications.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import time
import json
import logging
import os
from typing import Iterable, Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse
import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import Template, Context
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import (
    Notification,
    NotificationReceipt,
    DeliveryAttempt,
    NotificationPreference,
    Player,
)

logger = logging.getLogger(__name__)



# ----------------------------- Events ----------------------------------------


@dataclass(frozen=True)
class Event:
    key: str                    # e.g. "LINEUP_PUBLISHED_FOR_PLAYER"
    subject: str                # subject template (can include {{vars}})
    template_html: str          # HTML email template path
    template_txt: str           # TXT email template path
    sms_template: str           # SMS template path (plain text)

# Event key constants (exported)
LINEUP_PUBLISHED_FOR_PLAYER = "LINEUP_PUBLISHED_FOR_PLAYER"
RESULT_POSTED_FOR_PLAYER = "RESULT_POSTED_FOR_PLAYER"
SUBPLAN_CREATED = "SUBPLAN_CREATED"
SUBPLAN_UPDATED_FOR_PLAYER = "SUBPLAN_UPDATED_FOR_PLAYER"
SUBPLAN_CANCELLED_FOR_PLAYER = "SUBPLAN_CANCELLED_FOR_PLAYER"
MATCH_REMINDER_24H = "MATCH_REMINDER_24H"
AVAILABILITY_REMINDER_5D = "AVAILABILITY_REMINDER_5D"
LINEUP_OVERDUE = "LINEUP_OVERDUE"
SCORES_OVERDUE = "SCORES_OVERDUE"


SUBJECT_DEFAULTS: Dict[str, str] = {
    "LINEUP_PUBLISHED_FOR_PLAYER": "Royals: You’re in the lineup!",
    "RESULT_POSTED_FOR_PLAYER": "Royals: Your match result is posted",
    "LINEUP_OVERDUE": "Royals: Lineup is overdue",
}

# Known events (extend as you add more)
EVENTS: Dict[str, Event] = {
    "LINEUP_PUBLISHED_FOR_PLAYER": Event(
        key="LINEUP_PUBLISHED_FOR_PLAYER",
        subject="{{ first_name|default:player_first_name|default:recipient.first_name|default:user.first_name|default:'Player' }}: You're in the Royals Lineup!",
        template_html="emails/lineup_published.html",
        template_txt="emails/lineup_published.txt",
        sms_template="sms/lineup_published.txt",
    ),
    "RESULT_POSTED_FOR_PLAYER": Event(
        key="RESULT_POSTED_FOR_PLAYER",
        subject="Royals: Your match result is posted",
        template_html="emails/result_posted.html",
        template_txt="emails/result_posted.txt",
        sms_template="sms/result_posted.txt",
    ),
    "SUBPLAN_CREATED": Event(
        key="SUBPLAN_CREATED",
        subject="Royals: You’ve been selected as a sub",
        template_html="emails/subplan_created.html",
        template_txt="emails/subplan_created.txt",
        sms_template="sms/subplan_created.txt",
    ),
    "SUBPLAN_UPDATED_FOR_PLAYER": Event(
        key="SUBPLAN_UPDATED_FOR_PLAYER",
        subject="Royals: Your sub match has been updated",
        template_html="emails/subplan_updated_for_player.html",
        template_txt="emails/subplan_updated_for_player.txt",
        sms_template="sms/subplan_updated_for_player.txt",
    ),
    "SUBPLAN_CANCELLED_FOR_PLAYER": Event(
        key="SUBPLAN_CANCELLED_FOR_PLAYER",
        subject="Royals: Your sub match was cancelled",
        template_html="emails/subplan_cancelled_for_player.html",
        template_txt="emails/subplan_cancelled_for_player.txt",
        sms_template="sms/subplan_cancelled_for_player.txt",
    ),
    "MATCH_REMINDER_24H": Event(
        key="MATCH_REMINDER_24H",
        subject="Royals: Match reminder for tomorrow",
        template_html="emails/match_reminder_24h.html",
        template_txt="emails/match_reminder_24h.txt",
        sms_template="sms/match_reminder_24h.txt",
    ),
    "AVAILABILITY_REMINDER_5D": Event(
        key="AVAILABILITY_REMINDER_5D",
        subject="Royals: Please submit your availability",
        template_html="emails/availability_reminder_5d.html",
        template_txt="emails/availability_reminder_5d.txt",
        sms_template="sms/availability_reminder_5d.txt",
    ),
    "LINEUP_OVERDUE": Event(
        key="LINEUP_OVERDUE",
        subject="Royals: Lineup is overdue",
        template_html="emails/lineup_overdue.html",
        template_txt="emails/lineup_overdue.txt",
        sms_template="sms/lineup_overdue.txt",
    ),
    "SCORES_OVERDUE": Event(
        key="SCORES_OVERDUE",
        subject="Royals: Scores are overdue",
        template_html="emails/scores_overdue.html",
        template_txt="emails/scores_overdue.txt",
        sms_template="sms/scores_overdue.txt",
    ),
}


# ----------------------------- Per-event preferences -------------------------

# Map event keys to NotificationPreference boolean fields for email/SMS
PREF_EMAIL_FIELDS: Dict[str, str] = {
    "LINEUP_PUBLISHED_FOR_PLAYER": "lineup_published_email",
    "RESULT_POSTED_FOR_PLAYER": "result_posted_email",
    "LINEUP_OVERDUE": "lineup_overdue_staff_email",
    "SCORES_OVERDUE": "scores_overdue_staff_email",
    "SUBPLAN_CREATED": "subplan_created_email",
    "SUBPLAN_UPDATED_FOR_PLAYER": "subplan_created_email",
    "SUBPLAN_CANCELLED_FOR_PLAYER": "subplan_created_email",
    "MATCH_REMINDER_24H": "match_reminder_24h_email",
    "AVAILABILITY_REMINDER_5D": "availability_reminder_5d_email",
}

PREF_SMS_FIELDS: Dict[str, str] = {
    "LINEUP_PUBLISHED_FOR_PLAYER": "lineup_published_sms",
    "RESULT_POSTED_FOR_PLAYER": "result_posted_sms",
    "SUBPLAN_CREATED": "subplan_created_sms",
    "SUBPLAN_UPDATED_FOR_PLAYER": "subplan_created_sms",
    "SUBPLAN_CANCELLED_FOR_PLAYER": "subplan_created_sms",
    "MATCH_REMINDER_24H": "match_reminder_24h_sms",
    "AVAILABILITY_REMINDER_5D": "availability_reminder_5d_sms",
}

STAFF_ONLY_EVENTS = {"LINEUP_OVERDUE", "SCORES_OVERDUE"}


def _is_captain_or_staff(user) -> bool:
    try:
        if getattr(user, "is_staff", False):
            return True
        pp = getattr(user, "player_profile", None)
        return bool(pp and getattr(pp, "is_captain", False))
    except Exception:
        return False


# ----------------------------- Helpers ---------------------------------------


def _render_subject(event: Event, ctx: Dict[str, Any]) -> str:
    raw = event.subject or SUBJECT_DEFAULTS.get(event.key) or "Royals Industrial League"
    try:
        return Template(raw).render(Context(ctx))
    except Exception:
        return raw


def _render_email_parts(event: Event, ctx: Dict[str, Any]) -> tuple[str, Optional[str]]:
    """
    Return (text_body, html_body). Either template may be missing if you prefer.
    """
    txt = render_to_string(event.template_txt, ctx) if event.template_txt else ""
    html = render_to_string(event.template_html, ctx) if event.template_html else None
    return txt.strip(), (html.strip() if html else None)


def _get_prefs(user) -> NotificationPreference:
    prefs, _ = NotificationPreference.objects.get_or_create(user=user)
    return prefs


def _quiet_hours_range() -> tuple[int, int]:
    """Return (start_hour, end_hour). Honors either a tuple setting or START/END ints.
    Defaults to (22, 8) if nothing is configured.
    """
    try:
        # Primary: NOTIFY_QUIET_HOURS = (start, end)
        if hasattr(settings, "NOTIFY_QUIET_HOURS") and settings.NOTIFY_QUIET_HOURS:
            start_h, end_h = settings.NOTIFY_QUIET_HOURS
            return int(start_h), int(end_h)
    except Exception:
        pass
    # Fallback: separate START/END ints (often set via env)
    try:
        start_h = int(getattr(settings, "NOTIFY_QUIET_HOURS_START", 22))
        end_h = int(getattr(settings, "NOTIFY_QUIET_HOURS_END", 8))
        return start_h, end_h
    except Exception:
        return 22, 8


def _in_quiet_hours() -> bool:
    start_h, end_h = _quiet_hours_range()
    # If start and end are the same, treat quiet hours as disabled
    if start_h == end_h:
        return False
    now = timezone.localtime()
    t = now.time()
    start = time(hour=start_h)
    end = time(hour=end_h)
    if start_h < end_h:
        # Quiet window is same-day, e.g., 1 -> 6
        return start <= t < end
    # Quiet window wraps midnight, e.g., 22 -> 8
    return not (end <= t < start)


def _has_verified_phone(user) -> bool:
    prefs = _get_prefs(user)
    phone = getattr(prefs, "phone_e164", None)
    verified = bool(getattr(prefs, "phone_verified_at", None))
    return bool(phone and verified)


def _should_send_email(user, event_key: str) -> bool:
    """Per-event email checks + global email_enabled + staff-only restrictions."""
    # Staff-only events cannot go to non-captains/non-staff
    if event_key in STAFF_ONLY_EVENTS and not _is_captain_or_staff(user):
        return False

    prefs = _get_prefs(user)
    if not (bool(getattr(prefs, "email_enabled", True)) and bool(user.email)):
        return False

    field = PREF_EMAIL_FIELDS.get(event_key)
    if field is None:
        # Default: if we don't recognize the event, allow email
        return True
    return bool(getattr(prefs, field, False))


def _should_send_sms(user, event_key: str) -> bool:
    """Per-event SMS checks + global sms_enabled + verified phone + quiet hours + staff-only restrictions."""
    if event_key in STAFF_ONLY_EVENTS and not _is_captain_or_staff(user):
        return False

    prefs = _get_prefs(user)
    # Global user-level SMS toggle (or legacy opt_in field)
    if not bool(getattr(prefs, "sms_enabled", False) or getattr(prefs, "sms_opt_in", False)):
        return False

    # Per-event opt-in
    field = PREF_SMS_FIELDS.get(event_key)
    if field is not None and not bool(getattr(prefs, field, False)):
        return False

    # Safety gates
    if not _has_verified_phone(user):
        return False
    if _in_quiet_hours():
        return False
    return True


def _absolute_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path

    # Prefer explicit base URL
    base = getattr(settings, "SITE_BASE_URL", None)
    if base:
        return urljoin(base.rstrip("/") + "/", path.lstrip("/"))

    # Fallback to SITE_DOMAIN + protocol
    domain = getattr(settings, "SITE_DOMAIN", "").lstrip("/")
    proto = "https" if getattr(settings, "SECURE_SSL_REDIRECT", False) else "http"
    return f"{proto}://{domain}{path}" if domain else f"http://localhost:8000{path}"


# ----------------------------- Site base helper -----------------------------
def _site_base() -> str:
    """
    Absolute site base (scheme + host) for email assets.
    Prefers settings.SITE_BASE_URL (e.g., https://dev.royalsleague.com),
    otherwise builds from SITE_DOMAIN + SECURE_SSL_REDIRECT.
    """
    base = getattr(settings, "SITE_BASE_URL", None)
    if base:
        return str(base).rstrip("/")
    domain = getattr(settings, "SITE_DOMAIN", "").lstrip("/")
    proto = "https" if getattr(settings, "SECURE_SSL_REDIRECT", False) else "http"
    return f"{proto}://{domain}" if domain else "http://localhost:8000"


# ----------------------------- Channel senders -------------------------------


def _send_email(user, event: Event, ctx: Dict[str, Any], attempt: DeliveryAttempt):
    txt, html = _render_email_parts(event, ctx)
    subject = ctx.get("_subject_override") or _render_subject(event, ctx)
    to_list = [attempt.to or user.email]

    msg = EmailMultiAlternatives(
        subject=subject,
        body=txt or "",
        to=to_list,
    )
    if html:
        msg.attach_alternative(html, "text/html")

    sent_count = msg.send()  # 1 on success (Django); Anymail may attach status

    attempt.status = "SENT" if sent_count else "FAILED"
    attempt.sent_at = timezone.now()
    # If using Anymail, you can capture provider id like:
    # status = getattr(msg, "anymail_status", None)
    # if status and status.message_id:
    #     attempt.provider_message_id = status.message_id
    attempt.save()


def _send_sms(user, event: Event, ctx: Dict[str, Any], attempt: DeliveryAttempt):
    # Resolve provider and feature flag (single source of truth: settings.ENABLE_SMS)
    provider = (getattr(settings, "SMS_PROVIDER", "") or getattr(settings, "SMS_PROVIDE", "")).lower()
    feature_on = bool(getattr(settings, "ENABLE_SMS", False))
    api_key = getattr(settings, "BREVO_API_KEY", "") or getattr(settings, "BREVO_SMS_API_KEY", "")

    if not (feature_on and provider == "brevo" and api_key):
        attempt.status = "SUPPRESSED"
        attempt.error = "SMS disabled/misconfigured"
        attempt.save()
        return

    test_to = os.getenv("SMS_TEST_NUMBER", "").strip()
    if test_to:
        phone = test_to
        # Normalize simple cases for test number
        if phone.startswith("00"):
            phone = "+" + phone[2:]
        if not phone.startswith("+"):
            digits = "".join(ch for ch in phone if ch.isdigit())
            if getattr(settings, "SMS_DEFAULT_COUNTRY", "US") == "US" and not digits.startswith("1"):
                digits = "1" + digits
            phone = "+" + digits
    else:
        prefs = _get_prefs(user)
        phone = getattr(prefs, "phone_e164", None)
        # We already checked opt-in and verified phone in _should_send_sms; treat missing here as a hard failure
        if not phone or not _has_verified_phone(user):
            attempt.status = "FAILED"
            attempt.error = "no verified phone"
            attempt.save()
            return
        # Normalize stored phone (ensure leading '+')
        phone = str(phone).strip()
        if phone.startswith("00"):
            phone = "+" + phone[2:]
        if not phone.startswith("+"):
            digits = "".join(ch for ch in phone if ch.isdigit())
            if getattr(settings, "SMS_DEFAULT_COUNTRY", "US") == "US" and not digits.startswith("1"):
                digits = "1" + digits
            phone = "+" + digits

    sms_text = render_to_string(event.sms_template, ctx).strip()

    headers = {
        "api-key": api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }
    payload = {
        "sender": getattr(settings, "BREVO_SMS_SENDER", "ROYALS"),
        "recipient": phone,
        "content": sms_text[:1600],
        "type": "transactional",
    }

    logger.info("Attempting Brevo SMS → to=%s sender=%s len=%d", phone, getattr(settings, "BREVO_SMS_SENDER", "ROYALS"), len(sms_text))

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/transactionalSMS/send",
            headers=headers,
            data=json.dumps(payload),
            timeout=10,
        )
        if resp.status_code in (200, 201, 202):
            data = resp.json() if resp.text else {}
            attempt.status = "SENT"
            attempt.provider_message_id = str(data.get("messageId", ""))[:255]
            attempt.sent_at = timezone.now()
        else:
            attempt.status = "FAILED"
            attempt.error = f"{resp.status_code} {resp.text[:500]}"
    except Exception as e:
        attempt.status = "FAILED"
        attempt.error = str(e)[:500]
    finally:
        attempt.save()


# ----------------------------- Public API ------------------------------------


def notify(
    event_key: str,
    *,
    users: Iterable,                    # iterable of auth.User
    title: str = "",
    body: str = "",
    url: Optional[str] = None,          # absolute or relative
    context: Optional[Dict[str, Any]] = None,
    html_template: Optional[str] = None,
    txt_template: Optional[str] = None,
) -> tuple[Notification, int]:
    """
    Create a Notification, then for each user:
      - create a NotificationReceipt so the bell shows it
      - create DeliveryAttempt(s) for channels that pass gates
      - send channels inline (sequential)

    Returns (notification, attempts_created)
    """
    context = context or {}
    evt = EVENTS.get(event_key) or Event(
        key=event_key,
        subject=(title or SUBJECT_DEFAULTS.get(event_key, "Royals Industrial League")),
        template_html=html_template or "emails/generic.html",
        template_txt=txt_template or "emails/generic.txt",
        sms_template="sms/generic.txt",
    )

    # Build notification URL (relative allowed; will be absolutized in template if needed)
    notif_url = url or ""

    notification = Notification.objects.create(
        event=event_key,
        title=title or evt.subject,
        body=body or "",
        url=notif_url,
    )

    attempts = 0

    for user in users:
        # Receipt first so the bell always updates even if send fails
        NotificationReceipt.objects.get_or_create(notification=notification, user=user)

        # Build per-recipient context (init, then set fields)
        ctx = dict(context)
        ctx["user"] = user
        ctx.setdefault("recipient", user)
        ctx.setdefault("notification_url", _absolute_url(notif_url) if notif_url else "")

        base = getattr(settings, "SITE_BASE_URL", None)
        if base:
            parsed = urlparse(base)
            ctx.setdefault("protocol", parsed.scheme)
            ctx.setdefault("domain", parsed.netloc)
        else:
            # fallbacks
            proto = "https" if getattr(settings, "SECURE_SSL_REDIRECT", False) else "http"
            domain = getattr(settings, "SITE_DOMAIN", "").lstrip("/")
            ctx.setdefault("protocol", proto)
            ctx.setdefault("domain", domain or "localhost:8000")

        ctx.setdefault("site_domain", _site_base())

        # Attach Player object if available (for templates that reference {{ player }})
        try:
            upmap = context.get("_user_player_map") or {}
            p_for_user = upmap.get(getattr(user, "id", None))
            if p_for_user:
                ctx.setdefault("player", p_for_user)
        except Exception:
            logger.exception("[notify] failed to attach player for user %s", getattr(user, "id", None))

        # Merge per-user extras (e.g., slot_label, player_first_name)
        try:
            extras = (context.get("_per_user_ctx") or {}).get(getattr(user, "id", None)) or {}
            if extras:
                ctx.update(extras)
                # Provide a canonical first_name for templates that expect it
                if "first_name" not in ctx and extras.get("player_first_name"):
                    ctx["first_name"] = extras["player_first_name"]
        except Exception:
            logger.exception("[notify] failed to merge per-user context for user %s", getattr(user, "id", None))

        # EMAIL
        if _should_send_email(user, event_key):
            attempt = DeliveryAttempt.objects.create(
                notification=notification,
                channel="EMAIL",
                to=(user.email or ""),
                status="PENDING",
                retry_count=0,
            )
            try:
                _send_email(user, evt, ctx, attempt)
            except Exception as e:
                attempt.status = "FAILED"
                attempt.error = str(e)[:500]
                attempt.save()
            finally:
                attempts += 1
        else:
            # Create a SUPPRESSED attempt for parity + log concise reason
            reason = "blocked"
            try:
                prefs_obj = _get_prefs(user)
                if event_key in STAFF_ONLY_EVENTS and not _is_captain_or_staff(user):
                    reason = "not captain/staff"
                elif not (bool(getattr(prefs_obj, "email_enabled", True)) and bool(user.email)):
                    reason = "email disabled/missing"
                else:
                    fld = PREF_EMAIL_FIELDS.get(event_key)
                    if fld and not bool(getattr(prefs_obj, fld, False)):
                        reason = "opt-out"
                logger.info(
                    "[notify] EMAIL suppressed: user=%s event=%s reason=%s",
                    getattr(user, "id", None), event_key, reason,
                )
            except Exception:
                logger.exception("[notify] EMAIL suppressed: reason calc failed for user=%s event=%s", getattr(user, "id", None), event_key)

            attempt = DeliveryAttempt.objects.create(
                notification=notification,
                channel="EMAIL",
                to=(user.email or ""),
                status="SUPPRESSED",
                retry_count=0,
                error=reason,
            )
            attempts += 1

        # SMS: respect per-event and global gates
        prefs_obj = _get_prefs(user)
        phone = getattr(prefs_obj, "phone_e164", None) or ""

        if not _should_send_sms(user, event_key):
            # Determine a friendly suppression reason for visibility
            reason = "disabled"
            if not (getattr(prefs_obj, "sms_enabled", False) or getattr(prefs_obj, "sms_opt_in", False)):
                reason = "user disabled"
            elif event_key in STAFF_ONLY_EVENTS and not _is_captain_or_staff(user):
                reason = "not captain/staff"
            elif not _has_verified_phone(user) or not phone:
                reason = "no verified phone"
            elif _in_quiet_hours():
                reason = "quiet hours"

            attempt = DeliveryAttempt.objects.create(
                notification=notification,
                channel="SMS",
                to=phone,
                status="SUPPRESSED",
                retry_count=0,
                error=reason,
            )
            attempts += 1
            try:
                logger.info(
                    "[notify] SMS suppressed: user=%s event=%s reason=%s",
                    getattr(user, "id", None), event_key, reason,
                )
            except Exception:
                logger.exception("[notify] SMS suppressed: reason log failed for user=%s event=%s", getattr(user, "id", None), event_key)
        else:
            attempt = DeliveryAttempt.objects.create(
                notification=notification,
                channel="SMS",
                to=phone,
                status="PENDING",
                retry_count=0,
            )
            try:
                _send_sms(user, evt, ctx, attempt)
            except Exception as e:
                attempt.status = "FAILED"
                attempt.error = str(e)[:500]
                attempt.save()
            finally:
                attempts += 1

    return notification, attempts


def lineup_published(players: Optional[Iterable[Player]], fixture, season=None) -> tuple[int, int]:
    """
    Convenience wrapper for the common case of publishing a lineup.
    Derives recipients from lineup slots if players is None or empty.

    Returns (recipient_count, attempts_created)
    """
    # Collect recipients from provided players or from lineup slots
    recipients: List[Player] = []
    seen_pids = set()

    if players:
        for p in players:
            if not p:
                continue
            if getattr(p, "id", None) and getattr(p, "user_id", None) and p.id not in seen_pids:
                seen_pids.add(p.id)
                recipients.append(p)
    else:
        try:
            slots = fixture.lineup.slots.select_related("player1__user", "player2__user")
            for s in slots:
                for p in (s.player1, s.player2):
                    if p and getattr(p, "user_id", None) and p.id not in seen_pids:
                        seen_pids.add(p.id)
                        recipients.append(p)
        except Exception:
            logger.exception("[lineup_published] could not derive recipients from lineup")

    # Build per-user extra context **directly from LineupSlot codes** (S1..S3, D1..D3)
    per_user_ctx: Dict[int, Dict[str, Any]] = {}
    try:
        lu = getattr(fixture, "lineup", None)
        if not lu:
            raise ValueError("No lineup attached to fixture")

        # Always use the canonical relation: lineup.slots
        slots_qs = getattr(lu, "slots", None)
        if hasattr(slots_qs, "all"):
            slots = list(slots_qs.all())
        elif callable(slots_qs):
            slots = list(slots_qs() or [])
        else:
            slots = list(slots_qs or [])

        def _full_name(u):
            try:
                fn = getattr(u, "first_name", "") or ""
                ln = getattr(u, "last_name", "") or ""
                nm = (fn + " " + ln).strip()
                return nm or None
            except Exception:
                return None

        for s in slots:
            try:
                code = getattr(s, "slot", None)  # e.g., 'S3', 'D2'
                # Human label from choices: 'Singles 3', 'Doubles 2'
                try:
                    label = s.get_slot_display()
                except Exception:
                    label = str(code) if code else "TBD"

                # Doubles flag from code prefix
                is_doubles = bool(code and str(code).upper().startswith("D"))

                p1 = getattr(s, "player1", None)
                p2 = getattr(s, "player2", None)

                def add_ctx(p_self, p_partner):
                    if not p_self or not getattr(p_self, "user_id", None):
                        return
                    u = getattr(p_self, "user", None)
                    extras = {
                        "slot_label": label,
                        "slot_name": label,
                        "player_first_name": getattr(u, "first_name", None) if u else None,
                        "is_doubles": is_doubles,
                    }
                    if is_doubles and p_partner and getattr(p_partner, "user", None):
                        pu = p_partner.user
                        extras.update({
                            "partner_first_name": getattr(pu, "first_name", None),
                            "partner_last_name": getattr(pu, "last_name", None),
                            "partner_full_name": _full_name(pu),
                        })
                    per_user_ctx[p_self.user_id] = extras

                add_ctx(p1, p2)
                add_ctx(p2, p1)
            except Exception:
                logger.exception("[lineup_published] failed to process LineupSlot entry")
    except Exception:
        logger.exception("[lineup_published] could not build per-user slot context from LineupSlot")

    try:
        logger.info("[lineup_published] per_user_ctx keys=%s", list(per_user_ctx.keys()))
    except Exception:
        pass
    try:
        logger.info("[lineup_published] sample per_user_ctx=%s", {k: {kk: vv for kk, vv in v.items() if kk in ("slot_label", "is_doubles", "_score")} for k, v in list(per_user_ctx.items())[:5]})
    except Exception:
        pass

    if not recipients:
        logger.info("[lineup_published] no eligible recipients for fixture %s", getattr(fixture, "id", None))
        return 0, 0

    # Title/body/url
    opp = getattr(fixture, "opponent", "") or "Opponent"
    dt = getattr(fixture, "date", None)
    ha = "Home" if getattr(fixture, "home", False) else "Away"
    title = "You're in the Royals Lineup!"
    body = f"{ha} vs {opp}"
    if dt:
        try:
            body = f"{ha} vs {opp} on {timezone.localtime(dt):%a %b %d}"
        except Exception:
            body = f"{ha} vs {opp}"

    try:
        rel = reverse("fixture_detail", args=[fixture.id])
    except Exception:
        rel = ""
    url = _absolute_url(rel) if rel else ""

    # Prepare users and base context
    users = [p.user for p in recipients if getattr(p, "user_id", None)]
    user_player_map: Dict[int, Player] = {p.user_id: p for p in recipients if getattr(p, "user_id", None)}
    base_ctx = {
        "fixture": fixture,
        "season": season,
        "opponent": opp,
        "match_dt": dt,
        "home_away": ha,
        "fixture_url": url,
        "_per_user_ctx": per_user_ctx,
        "_user_player_map": user_player_map,
    }

    # Fire notify
    notification, attempts = notify(
        "LINEUP_PUBLISHED_FOR_PLAYER",
        users=users,
        title=title,
        body=body,
        url=url,
        context=base_ctx,
        html_template="emails/lineup_published.html",
        txt_template="emails/lineup_published.txt",
    )

    logger.info(
        "[lineup_published] notif=%s recipients=%d attempts=%d",
        notification.id, len(users), attempts
    )
    return len(users), attempts


# --- Thin canonical wrapper: send_event() ------------------------------------

def _normalize_event_key(key: str) -> str:
    """Support legacy/alias keys transparently."""
    aliases = {
        "SUBPLAN_CREATED_FOR_PLAYER": "SUBPLAN_CREATED",
    }
    return aliases.get(key, key)


def send_event(event_key: str, *, users: Optional[Iterable] = None, players: Optional[Iterable[Player]] = None,
               season=None, fixture=None, title: str = "", body: str = "", url: Optional[str] = None,
               context: Optional[Dict[str, Any]] = None, per_user_ctx: Optional[Dict[int, Dict[str, Any]]] = None,
               user_player_map: Optional[Dict[int, Player]] = None, subject: Optional[str] = None) -> tuple[Notification, int]:
    """
    One call to do it all: create Notification, create receipts, and
    create/send DeliveryAttempts immediately (email/SMS) using `notify()`.

    Pass either `users` or `players` (we'll resolve users from players).
    You can pass extra context, and optional `_per_user_ctx` / `_user_player_map`.
    Returns (Notification, attempts_created).
    """
    event_key = _normalize_event_key(str(event_key or "").strip())

    # Resolve users from players if needed
    resolved_users: List = []
    if users:
        resolved_users = list(users)
    elif players:
        try:
            for p in players:
                if not p:
                    continue
                if getattr(p, "user_id", None):
                    resolved_users.append(p.user)
        except Exception:
            pass

    # Build base context
    base_ctx = dict(context or {})
    if season is not None:
        base_ctx.setdefault("season", season)
    if fixture is not None:
        base_ctx.setdefault("fixture", fixture)
        # Auto URL if not provided
        try:
            if not url and getattr(fixture, "id", None):
                from django.urls import reverse as _rev
                url = _absolute_url(_rev("fixture_detail", args=[fixture.id]))
        except Exception:
            pass

    if subject:
        base_ctx["_subject_override"] = subject
    else:
        base_ctx.pop("_subject_override", None)
    if per_user_ctx:
        base_ctx.setdefault("_per_user_ctx", per_user_ctx)
    if user_player_map:
        base_ctx.setdefault("_user_player_map", user_player_map)


    return notify(
        event_key,
        users=resolved_users,
        title=title,
        body=body,
        url=url,
        context=base_ctx,
    )