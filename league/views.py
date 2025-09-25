from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.urls import reverse
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
import json
import csv
from datetime import datetime, date, time
from django.db.models import Sum, Q
from django.core.paginator import Paginator
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.db import connection
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.contrib.auth import get_user_model
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.conf import settings
from django_ratelimit.decorators import ratelimit as _ratelimit
from django.utils.decorators import method_decorator
import logging
import requests
from collections import defaultdict, Counter
from decimal import Decimal
from decimal import ROUND_HALF_UP, InvalidOperation
from django.forms import modelformset_factory
from .forms import LeagueStandingForm
from league.notifications import notify
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.contrib import messages
from .models import LeagueStanding, Season, DeliveryAttempt
from .forms import LeagueStandingFormSet
import uuid
import logging
from league.notifications import send_event
from django.views.decorators.csrf import csrf_exempt

# --- SMS Opt-in flow imports ---
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import random
from datetime import timedelta
from .models import PhoneVerification, NotificationPreference
from .notifications import _send_sms


logger = logging.getLogger(__name__)

def _normalize_phone(phone: str) -> str:
    """Ensure a phone number is in +E.164 form. Defaults to US if no country code present."""
    if not phone:
        return ""
    p = str(phone).strip()
    if p.startswith("00"):
        p = "+" + p[2:]
    if p.startswith("+"):
        return p
    digits = "".join(ch for ch in p if ch.isdigit())
    try:
        default_cc = "1" if getattr(settings, "SMS_DEFAULT_COUNTRY", "US") == "US" else ""
    except Exception:
        default_cc = "1"
    if default_cc and not digits.startswith(default_cc):
        digits = default_cc + digits
    return "+" + digits if digits else ""



 # --- Helpers for active season and team point totals ---

def get_active_season_or_none():
    """Return the single active Season or None."""
    try:
        return Season.objects.filter(is_active=True).first()
    except Exception:
        return None


def get_team_match_points_for_season(season):
    """Sum adjusted home match points across all scored fixtures in a season."""
    if not season:
        return 0
    total = 0
    try:
        for fx in Fixture.objects.filter(season=season):
            h, _ = compute_fixture_match_points(fx)
            try:
                total += h
            except Exception:
                total = float(total) + float(h)
    except Exception:
        pass
    return total


def get_team_sub_points_for_season(season):
    """Sum sub points across all players for fixtures in a season."""
    if not season:
        return 0
    try:
        agg = SubResult.objects.filter(fixture__season=season).aggregate(total=Sum('points_cached'))
        return agg['total'] or 0
    except Exception:
        return 0


from .models import Player, Season, RosterEntry, Fixture, Availability, Lineup, LineupSlot, SlotScore, PlayerMatchPoints, SubPlan, SubResult, SubAvailability, NotificationReceipt
from .forms import AvailabilityForm, LineupForm, LineupSlotFormSet, PlayerForm, FixtureForm, SubPlanForm, SubResultForm, NotificationPreferenceForm, UsernameForm, StyledPasswordChangeForm, InvitePlayerForm, ShareContactPrefsForm

# Notifications helper + constants (authoritative from utils.notifications)
from .utils.notifications import (
    notify,
    SUBPLAN_CREATED_FOR_PLAYER,
    SUBPLAN_UPDATED_FOR_PLAYER,
    SUBPLAN_CANCELLED_FOR_PLAYER,
    RESULT_POSTED_FOR_PLAYER,
    LINEUP_PUBLISHED_FOR_PLAYER,
)

# league/views.py


def compute_royals_points(season: "Season") -> "Decimal":
    # Reuse existing aggregators for team match + sub points
    team_match_pts = Decimal(get_team_match_points_for_season(season))
    team_sub_pts = Decimal(get_team_sub_points_for_season(season))
    return team_match_pts + team_sub_pts

@staff_member_required
def admin_league_standings(request):
    season = get_active_season_or_none()  # reuse your existing helper; else fetch from request if needed
    if not season:
        messages.warning(request, "No active season selected.")
        return redirect("admin_dashboard")

    # Ensure we have a Royals row
    royals, _ = LeagueStanding.objects.get_or_create(
        season=season, team_name="Royals", defaults={"is_royals": True}
    )

    if request.method == "POST":
        action = request.POST.get("action")
        # Always recompute Royals
        royals.points = compute_royals_points(season)
        royals.updated_by = request.user
        royals.save()

        # Other teams editable
        qs = LeagueStanding.objects.filter(season=season, is_royals=False)
        formset = LeagueStandingFormSet(request.POST, queryset=qs)

        if formset.is_valid():
            with transaction.atomic():
                instances = formset.save(commit=False)
                existing_ids = set()
                for inst in instances:
                    inst.season = season
                    inst.updated_by = request.user
                    inst.save()
                    existing_ids.add(inst.id)

                # Create any missing rows for blank slots (optional: not needed if you only use existing)
                # No deletes (can_delete=False)

                if action == "publish":
                    # Publish the season set: mark all rows (including Royals) as published
                    LeagueStanding.objects.filter(season=season).update(published=True)
                    messages.success(request, "Standings published.")
                elif action == "save":
                    # Keep as draft
                    LeagueStanding.objects.filter(season=season).update(published=False)
                    messages.success(request, "Standings saved as draft.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        # GET: recompute & show
        royals.points = compute_royals_points(season)
        royals.updated_by = request.user
        royals.save()

        qs = LeagueStanding.objects.filter(season=season, is_royals=False)
        formset = LeagueStandingFormSet(queryset=qs)

    # Provide data for the widget
    rows = list(LeagueStanding.objects.filter(season=season).order_by("-points", "team_name"))
    context = {
        "season": season,
        "royals": royals,
        "formset": formset,
        "standings_rows": rows,
        "standings_published": any(r.published for r in rows),
    }
    return render(request, "league/admin_panel/standings_widget.html", context)

# define rate limit request response type and message
def ratelimit_429(request, exception):
    # You can return HTML instead if you prefer
    return JsonResponse({"detail": "Too many requests"}, status=429)

def rl_enabled():
    return bool(getattr(settings, "RATELIMIT_ENABLE", False))

def rl_deco(*args, **kwargs):
    base = _ratelimit(*args, **kwargs)
    def _wrap(fn):
        return base(fn) if rl_enabled() else fn
    return _wrap

SLOT_CODES = ["S1", "S2", "S3", "D1", "D2", "D3"]
NTRP_VALUES = {"3.0", "3.5", "4.0", "4.5", "5.0", "5.5", "6.0", "6.5", "7.0"}

# --- Scoring helpers ---
RESULT_POINTS = {
    SlotScore.Result.WIN: (2, 0),
    SlotScore.Result.LOSS: (0, 2),
    SlotScore.Result.TIE: (1, 1),
    SlotScore.Result.WIN_FF: (2, 0),
    SlotScore.Result.LOSS_FF: (0, 2),
}

def is_staff_user(u):  # keep it simple: staff = admin ops
    return u.is_authenticated and u.is_staff

@login_required
@user_passes_test(is_staff_user)
def admin_manage_players(request):
    User = get_user_model()
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "active")

    qs = (
        User.objects
        .select_related("player_profile")
        .only(
            "id", "username", "email", "first_name", "last_name", "is_active", "password",
            "player_profile__id", "player_profile__first_name", "player_profile__last_name",
            "player_profile__email", "player_profile__is_captain"
        )
    )

    if status == "inactive":
        qs = qs.filter(is_active=False)
    else:
        qs = qs.filter(is_active=True)

    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(player_profile__first_name__icontains=q)
            | Q(player_profile__last_name__icontains=q)
        )

    qs = qs.order_by("last_name", "first_name", "username")

    return render(
        request,
        "league/admin_panel/manage_players.html",
        {
            "players": qs,  # each item is a User; access Player via user.player_profile
            "q": q,
            "status": status,
        },
    )


def _send_invite_email(player, request):
    """Send the branded invite email to a Player using HTML + text templates and custom subject."""

    # Build absolute accept URL
    accept_path = reverse("accept_invite", args=[str(player.invite_token)])
    base_url = getattr(settings, "PUBLIC_BASE_URL", None) or f"{request.scheme}://{request.get_host()}"
    accept_url = base_url.rstrip('/') + accept_path

    # Subject (from template, fallback if missing)
    subject = render_to_string("emails/invite_subject.txt", {}).strip()
    if not subject:
        subject = "You're invited! Royals - Industrial League"

    # Render bodies
    ctx = {
        "first_name": getattr(player, "first_name", ""),
        "accept_url": accept_url,
        "now": timezone.now(),
        "public_base_url": base_url,
        "site_domain": base_url,
    }
    text_body = render_to_string("emails/invite_player.txt", ctx)
    html_body = render_to_string("emails/invite_player.html", ctx)

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")
    to = [addr for addr in [getattr(player, "email", None)] if addr]
    if not to:
        return  # no valid email

    msg = EmailMultiAlternatives(subject=subject, body=text_body, from_email=from_email, to=to)
    msg.attach_alternative(html_body, "text/html")
    try:
        msg.send(fail_silently=True)
    except Exception:
        pass


@login_required
@user_passes_test(is_staff_user)
@rl_deco(key='ip', rate='20/h', method='POST', block=True)
def admin_player_invite(request):
    if request.method == "POST":
        form = InvitePlayerForm(request.POST)
        if form.is_valid():
            User = get_user_model()
            email = form.cleaned_data["email"].lower()
            first = form.cleaned_data["first_name"].strip()
            last  = form.cleaned_data["last_name"].strip()
            make_captain = form.cleaned_data["make_captain"]

            # --- Duplicate guards: block invites to existing active accounts ---
            email_lc = email.lower()

            # If a Player exists with this email and is linked to an active user with a usable password → block
            existing_player = Player.objects.select_related("user").filter(email__iexact=email_lc).first()
            if existing_player and getattr(existing_player, "user", None):
                u = existing_player.user
                if u.is_active and u.has_usable_password():
                    form.add_error("email", "A player with this email already has an active account.")
                    return render(request, "league/admin_panel/invite_player.html", {
                        "form": form,
                        "email_error": "A player with this email already has an active account.",
                    })

            # If any active User exists with this email (even if not linked to a Player) → block only if user has usable password
            User = get_user_model()
            existing_user = User.objects.filter(email__iexact=email_lc, is_active=True).first()
            # Only block if the existing user already has a usable password (i.e., truly set up)
            if existing_user and not existing_player and existing_user.has_usable_password():
                form.add_error("email", "A user with this email already exists and has an active account.")
                return render(request, "league/admin_panel/invite_player.html", {
                    "form": form,
                    "email_error": "A user with this email already exists and has an active account.",
                })

            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "username": email,   # simple: username=email
                    "first_name": first,
                    "last_name": last,
                    "is_active": True,   # active so they can set password
                },
            )
            # Ensure invited accounts start with an *unusable* password so accept-invite can set it
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])  # do not set any random usable password here

            # Ensure there's a Player linked and populated with name/email
            profile, p_created = Player.objects.get_or_create(
                user=user,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                },
            )
            if not p_created:
                # Backfill missing fields from the invite if blank on existing profile
                fields_to_update = []
                if not getattr(profile, "first_name", "") and first:
                    profile.first_name = first
                    fields_to_update.append("first_name")
                if not getattr(profile, "last_name", "") and last:
                    profile.last_name = last
                    fields_to_update.append("last_name")
                if not getattr(profile, "email", "") and email:
                    profile.email = email
                    fields_to_update.append("email")
                if fields_to_update:
                    profile.save(update_fields=fields_to_update)

            if make_captain and not getattr(profile, "is_captain", False):
                profile.is_captain = True
                profile.save(update_fields=["is_captain"])

            # Issue an invite token, supporting both a helper method or raw fields
            try:
                token = profile.issue_invite()
            except AttributeError:
                # Gracefully set fields only if they exist on the model
                fields_to_update = []
                if hasattr(profile, "invite_token"):
                    if not getattr(profile, "invite_token", None):
                        profile.invite_token = uuid.uuid4()
                        fields_to_update.append("invite_token")
                if hasattr(profile, "invite_sent_at"):
                    profile.invite_sent_at = timezone.now()
                    fields_to_update.append("invite_sent_at")
                if fields_to_update:
                    profile.save(update_fields=fields_to_update)
                token = str(getattr(profile, "invite_token", uuid.uuid4()))

            _send_invite_email(profile, request)

            messages.success(request, f"Invite sent to {email}.")
            return redirect("admin_manage_players")
    else:
        form = InvitePlayerForm()
    return render(request, "league/admin_panel/invite_player.html", {"form": form})

@login_required
@user_passes_test(is_staff_user)
def admin_player_toggle_active(request, user_id):
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    messages.success(request, f"{'Activated' if user.is_active else 'Deactivated'} {user.get_full_name() or user.username}.")
    return redirect("admin_manage_players")

@login_required
@user_passes_test(is_staff_user)
def admin_player_toggle_captain(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    profile, _ = Player.objects.get_or_create(user=user)
    profile.is_captain = not profile.is_captain
    profile.save(update_fields=["is_captain"])
    messages.success(request, f"{'Granted' if profile.is_captain else 'Removed'} captain role for {user.get_full_name() or user.username}.")
    return redirect("admin_manage_players")


@login_required
@user_passes_test(is_staff_user)
def admin_player_reset_password(request, user_id):
    """Admin-triggered password reset email using branded templates."""
    user = get_object_or_404(get_user_model(), pk=user_id)
    from django.contrib.auth.forms import PasswordResetForm
    form = PasswordResetForm({"email": user.email})
    if form.is_valid() and user.is_active:
        try:
            form.save(
                request=request,
                use_https=request.is_secure(),
                email_template_name="emails/password_reset.html",
                subject_template_name="emails/password_reset_subject.txt",
            )
            messages.success(request, f"Password reset email sent to {user.email}.")
        except Exception:
            messages.error(request, "Could not send password reset email. Check email settings.")
    else:
        messages.error(request, "Cannot send reset: invalid or inactive user email.")
    return redirect("admin_manage_players")


def accept_invite(request, token):
    """One-time invite landing: player sets password. Burns invite token on success.
    If the user already has a usable password, redirect to login.
    """
    profile = get_object_or_404(Player, invite_token=token)
    user = profile.user
    from django.contrib.auth.forms import SetPasswordForm

    # If the account already has a usable password, don't allow reusing the invite link
    if user.has_usable_password():
        messages.info(request, "Your account is already set up. Please sign in.")
        return redirect("league_login")

    if request.method == "POST":
        form = SetPasswordForm(user, request.POST)
        # Ensure glass/Bootstrap styling on password fields
        try:
            form.fields["new_password1"].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "New password",
                "id": "id_new_password1",
            })
            form.fields["new_password2"].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Confirm password",
                "id": "id_new_password2",
            })
        except Exception:
            pass

        if form.is_valid():
            form.save()  # sets a usable password
            # Ensure the user is active and burn the invite token
            if not user.is_active:
                user.is_active = True
                user.save(update_fields=["is_active"])
            # Clear invite fields
            if hasattr(profile, "invite_sent_at"):
                profile.invite_sent_at = None
            profile.invite_token = None
            try:
                profile.save(update_fields=[fld for fld in ["invite_token", "invite_sent_at"] if hasattr(profile, fld)])
            except Exception:
                profile.save()

            # Ensure a NotificationPreference row exists for this user
            try:
                NotificationPreference.objects.get_or_create(user=user)
            except Exception:
                pass

            messages.success(request, "Your account is ready. Please sign in.")
            return redirect("league_login")
    else:
        form = SetPasswordForm(user)
        # Ensure glass/Bootstrap styling on password fields
        try:
            form.fields["new_password1"].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "New password",
                "id": "id_new_password1",
            })
            form.fields["new_password2"].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Confirm password",
                "id": "id_new_password2",
            })
        except Exception:
            pass

    return render(request, "account/accept_invite.html", {"form": form, "user_obj": user})

def compute_fixture_match_points(fixture):
    """Return (home_total, away_total) match points for a fixture.

    Sub (External) logic:
      • Singles: if the home slot uses a Sub, the home team receives 0 for that slot regardless of result.
      • Doubles: if exactly one home player is a Sub, the home team receives half of the slot's home share (Win=1, Tie=0.5). If both are Subs, the home team receives 0.
      • The away team always receives the full away share implied by the slot result.
    """
    def _base_points(result):
        # Returns (home_base, away_base) from a SlotScore.Result
        if result in (SlotScore.Result.WIN, SlotScore.Result.WIN_FF):
            return 2.0, 0.0
        if result in (SlotScore.Result.LOSS, SlotScore.Result.LOSS_FF):
            return 0.0, 2.0
        if result == SlotScore.Result.TIE:
            return 1.0, 1.0
        return 0.0, 0.0

    def _home_share_with_sub(slot_code, p1, p2, base_home):
        if base_home <= 0:
            return 0.0
        is_doubles = str(slot_code).startswith("D")
        sub1 = bool(getattr(p1, "is_substitute", False))
        sub2 = bool(getattr(p2, "is_substitute", False)) if is_doubles else False
        if not is_doubles:
            # Singles: any Sub means home gets 0 from this slot
            return 0.0 if sub1 else base_home
        # Doubles:
        if sub1 and sub2:
            return 0.0
        if sub1 or sub2:
            return base_home / 2.0
        return base_home

    lineup = getattr(fixture, "lineup", None)
    home_total = 0.0
    away_total = 0.0

    # Iterate through scored slots
    for sc in SlotScore.objects.filter(fixture=fixture):
        base_home, base_away = _base_points(sc.result)
        p1 = p2 = None
        if lineup:
            try:
                ls = lineup.slots.get(slot=sc.slot_code)
                p1, p2 = ls.player1, ls.player2
            except LineupSlot.DoesNotExist:
                p1 = p2 = None
        adj_home = _home_share_with_sub(sc.slot_code, p1, p2, base_home)
        home_total += adj_home
        away_total += base_away

    # Normalize to int when clean (e.g., 12.0) else keep .5 etc.
    def _norm(x):
        return int(x) if float(x).is_integer() else x

    return _norm(home_total), _norm(away_total)



def recompute_fixture_player_points(fixture):
    """Rebuild PlayerMatchPoints for a fixture based on SlotScore and Lineup.

    Rules:
      • Singles: Win=2 to the player, Tie=1, Loss=0. If the player is a Sub, award 0.
      • Doubles: split between two players (Win=1 each, Tie=0.5 each, Loss=0). Subs get 0.
    """
    PlayerMatchPoints.objects.filter(fixture=fixture).delete()

    lineup = getattr(fixture, "lineup", None)
    if not lineup:
        return

    scores = {s.slot_code: s for s in SlotScore.objects.filter(fixture=fixture)}

    def credit(player, pts):
        if not player or getattr(player, "is_substitute", False):
            return
        # Only persist non-zero points (optional: create zeros for auditing by removing this guard)
        if pts and pts != 0:
            PlayerMatchPoints.objects.create(fixture=fixture, player=player, points=pts)

    for ls in lineup.slots.all():
        sc = scores.get(ls.slot)
        if not sc:
            continue
        # Determine per-player allocation from the result
        if sc.result in (SlotScore.Result.WIN, SlotScore.Result.WIN_FF):
            if ls.slot.startswith("D"):
                credit(ls.player1, 1)
                credit(ls.player2, 1)
            else:
                credit(ls.player1, 2)
        elif sc.result == SlotScore.Result.TIE:
            if ls.slot.startswith("D"):
                credit(ls.player1, 0.5)
                credit(ls.player2, 0.5)
            else:
                credit(ls.player1, 1)
        else:
            # Loss or loss by forfeit → 0 each
            pass

# --- Notifications: lineup published ---
def _notify_lineup_published(fixture):
    """Gather lineup players and send LINEUP_PUBLISHED_FOR_PLAYER via send_event()."""
    try:
        lineup = getattr(fixture, "lineup", None)
        if not lineup:
            logger.info("notify lineup: no lineup on fixture %s", getattr(fixture, "id", None))
            return

        # Collect players and build rich per-user context (slot label, doubles, partner name)
        players = []
        users = []
        per_user_ctx = {}
        user_player_map = {}
        seen_player_ids = set()
        seen_user_ids = set()

        # Helper: safe slot label
        def _slot_label(ls):
            try:
                return ls.get_slot_display()
            except Exception:
                return getattr(ls, "slot", "TBD")

        slots_qs = lineup.slots.select_related("player1__user", "player2__user")
        for ls in slots_qs:
            label = _slot_label(ls)
            is_doubles = str(getattr(ls, "slot", "")).upper().startswith("D")

            for pl in (ls.player1, ls.player2):
                if not pl or not getattr(pl, "id", None):
                    continue
                if pl.id not in seen_player_ids:
                    players.append(pl)
                    seen_player_ids.add(pl.id)

                u = getattr(pl, "user", None)
                if u and getattr(u, "id", None) and u.id not in seen_user_ids:
                    users.append(u)
                    seen_user_ids.add(u.id)

                if u and getattr(u, "id", None):
                    extras = {
                        "slot_label": label,
                        "slot_name": label,
                        "is_doubles": is_doubles,
                        "player_first_name": getattr(u, "first_name", None),
                    }
                    if is_doubles:
                        other = ls.player2 if pl == ls.player1 else ls.player1
                        if other and getattr(other, "user", None):
                            extras["partner_full_name"] = f"{other.user.first_name} {other.user.last_name}".strip()
                    per_user_ctx[u.id] = extras
                    user_player_map[u.id] = pl

        if not players:
            logger.info("notify lineup: no players to notify for fixture %s", getattr(fixture, "id", None))
            return

        # Build base context + relative URL (absolute will be derived in notifications if configured)
        try:
            from django.urls import reverse as _rev
            detail_url = _rev("fixture_detail", args=[fixture.id])
        except Exception:
            detail_url = None

        try:
            from django.utils import timezone as _tz
            when_text = _tz.localtime(fixture.date).strftime("%b %d, %Y") if getattr(fixture, "date", None) else ""
        except Exception:
            when_text = fixture.date.strftime("%b %d, %Y") if getattr(fixture, "date", None) else ""

        base_ctx = {
            "fixture": fixture,
            "match_dt": getattr(fixture, "date", None),
            "opponent": getattr(fixture, "opponent", ""),
            "fixture_url": detail_url,
            "_per_user_ctx": per_user_ctx,
            "_user_player_map": user_player_map,
        }

        title = f"Lineup posted — vs {getattr(fixture, 'opponent', '') or 'Opponent'}"
        body  = f"Match on {when_text}."

        # Use unified inline-sending helper
        notif, attempts = send_event("LINEUP_PUBLISHED_FOR_PLAYER", players=players, season=fixture.season,
                                     fixture=fixture, title=title, body=body, url=detail_url, context=base_ctx,
                                     per_user_ctx=per_user_ctx, user_player_map=user_player_map)
        logger.info(
            "[lineup_published] notif=%s recipients=%s attempts=%s fixture=%s",
            getattr(notif, "id", None), len(players), attempts, getattr(fixture, "id", None)
        )
    except Exception:
        logger.exception("notify lineup failed for fixture %s", getattr(fixture, "id", None))

# Helper to check if a player is on a given season's roster
def player_on_roster(player, season):
    if not player or not season:
        return False
    return RosterEntry.objects.filter(season=season, player=player).exists()

def is_captain(user):
    try:
        return user.is_staff or (hasattr(user, "player_profile") and user.player_profile.is_captain)
    except Exception:
        return user.is_staff

def is_staff_user(user):
    return bool(user and user.is_authenticated and user.is_staff)

@login_required
@user_passes_test(is_staff_user)
def admin_manage_schedule(request):
    from .models import Season, Fixture
    seasons = Season.objects.all().order_by("-start_date") if hasattr(Season, "start_date") else Season.objects.all()

    # Accept both 'season' and 'season_id' from GET/POST to be resilient to template naming
    selected_id = (
        request.GET.get("season")
        or request.GET.get("season_id")
        or request.POST.get("season")
        or request.POST.get("season_id")
    )
    selected = seasons.filter(pk=selected_id).first() if selected_id else seasons.first()

    # Defaults for context
    add_form = FixtureForm(season=selected)
    edit_form = None
    edit_fixture_id = None

    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action in {"create", "update"}:
            if action == "update":
                fx = get_object_or_404(Fixture, pk=request.POST.get("fixture_id"), season=selected)
                form = FixtureForm(request.POST, instance=fx, season=selected)
            else:
                fx = Fixture(season=selected)
                form = FixtureForm(request.POST, instance=fx, season=selected)

            if form.is_valid():
                form.save()
                messages.success(request, "Fixture saved.")
                return redirect(f"{reverse('admin_manage_schedule')}?season={selected.pk}")
            else:
                messages.error(request, "Please fix the errors below.")
                if action == "update":
                    edit_form = form
                    edit_fixture_id = fx.id
                else:
                    add_form = form
        elif action == "create_season":
            from .models import Season
            season_name = (request.POST.get("season_name") or "").strip()
            season_year = (request.POST.get("season_year") or "").strip()

            if not season_name:
                messages.error(request, "Please enter a Season Name.")
            elif not season_year.isdigit():
                messages.error(request, "Please enter a valid Season Year (numbers only).")
            else:
                try:
                    # Create Season, setting fields that exist on your model
                    s = Season()
                    if hasattr(s, "name"):
                        s.name = season_name
                    if hasattr(s, "title") and not getattr(s, "name", None):
                        s.title = season_name
                    if hasattr(s, "year"):
                        s.year = int(season_year)
                    if hasattr(s, "season_year") and not hasattr(s, "year"):
                        s.season_year = int(season_year)
                    # Save the new season
                    s.save()
                    messages.success(request, "Season created.")
                    return redirect(f"{reverse('admin_manage_schedule')}?season={s.pk}")
                except Exception as e:
                    messages.error(request, f"Could not create season: {e}")

        elif action == "bulk_upload":
            bulk_errors = []
            uploaded = request.FILES.get("csv_file")
            if not uploaded:
                bulk_errors.append("Please choose a CSV file to upload.")
            else:
                try:
                    # Read as text
                    content = uploaded.read().decode("utf-8-sig")
                    reader = csv.DictReader(content.splitlines())

                    required_cols = {"week_number", "date", "time", "opponent", "home", "bye"}
                    missing = [c for c in required_cols if c not in reader.fieldnames]
                    if missing:
                        bulk_errors.append(f"Missing required columns: {', '.join(missing)}")
                    else:
                        rows = list(reader)
                        if not rows:
                            bulk_errors.append("The CSV appears to be empty.")
                        else:
                            # Validate and prepare objects
                            seen_weeks = set()
                            to_create = []

                            # Existing weeks in DB for this season
                            existing_weeks = set(
                                Fixture.objects.filter(season=selected).values_list("week_number", flat=True)
                            )

                            for i, row in enumerate(rows, start=2):  # start=2 accounts for header row=1
                                w_raw = (row.get("week_number") or "").strip()
                                d_raw = (row.get("date") or "").strip()
                                t_raw = (row.get("time") or "").strip()
                                opp = (row.get("opponent") or "").strip()
                                h_raw = (row.get("home") or "").strip().lower()
                                b_raw = (row.get("bye") or "").strip().lower()

                                # Week number
                                if not w_raw.isdigit():
                                    bulk_errors.append(f"Row {i}: week_number must be a positive integer.")
                                    continue
                                week_number = int(w_raw)
                                if week_number <= 0:
                                    bulk_errors.append(f"Row {i}: week_number must be > 0.")
                                    continue
                                if week_number in seen_weeks:
                                    bulk_errors.append(f"Row {i}: duplicate week_number {week_number} within the file.")
                                    continue
                                if week_number in existing_weeks:
                                    bulk_errors.append(f"Row {i}: week_number {week_number} conflicts with an existing match in this season.")
                                    continue

                                # Date & Time -> datetime
                                dt = None
                                try:
                                    # Accept HH:MM or HH:MM:SS
                                    time_fmt = "%H:%M:%S" if len(t_raw.split(":")) == 3 else "%H:%M"
                                    dt = datetime.strptime(f"{d_raw} {t_raw}", f"%Y-%m-%d {time_fmt}")
                                except Exception:
                                    bulk_errors.append(f"Row {i}: invalid date/time; expected date=YYYY-MM-DD and time=HH:MM.")
                                    continue

                                # BYE: allow opponent to be blank; ignore home when bye=true
                                is_bye = b_raw in {"true", "t", "yes", "y", "1"}

                                # Opponent required unless it's a bye week
                                if not is_bye and not opp:
                                    bulk_errors.append(f"Row {i}: opponent is required for non-bye matches.")
                                    continue
                                if is_bye:
                                    opp = ""  # normalize

                                # Home boolean (ignored for bye weeks)
                                if is_bye:
                                    home = False
                                else:
                                    if h_raw in {"true", "t", "yes", "y", "1"}:
                                        home = True
                                    elif h_raw in {"false", "f", "no", "n", "0"}:
                                        home = False
                                    else:
                                        bulk_errors.append(f"Row {i}: home must be true/false (or yes/no, 1/0).")
                                        continue

                                # If we got here, row is valid
                                seen_weeks.add(week_number)
                                to_create.append(Fixture(
                                    season=selected,
                                    week_number=week_number,
                                    date=dt,
                                    opponent=opp,
                                    home=home,
                                    is_bye=is_bye,
                                ))

                            if not bulk_errors and to_create:
                                Fixture.objects.bulk_create(to_create)
                                messages.success(request, f"Uploaded {len(to_create)} matches.")
                                return redirect(f"{reverse('admin_manage_schedule')}?season={selected.pk}")
                except UnicodeDecodeError:
                    bulk_errors.append("Could not decode file as UTF-8. Please save as UTF-8 CSV and try again.")
                except Exception as e:
                    bulk_errors.append(f"Unexpected error while reading CSV: {e}")

            # Fall through: show errors in the Bulk Upload modal
            fixtures = Fixture.objects.filter(season=selected).order_by("week_number") if selected else []
            return render(request, "league/admin_panel/manage_schedule.html", {
                "seasons": seasons,
                "selected": selected,
                "fixtures": fixtures,
                "add_form": add_form,
                "edit_form": edit_form,
                "edit_fixture_id": edit_fixture_id,
                "bulk_errors": bulk_errors,
                "current_active": Season.objects.filter(is_active=True).first(),
            })

        elif action == "delete":
            fx = get_object_or_404(Fixture, pk=request.POST.get("fixture_id"), season=selected)
            fx.delete()
            messages.success(request, "Fixture deleted.")
            return redirect(f"{reverse('admin_manage_schedule')}?season={selected.pk}")

        elif action == "delete_all":
            # Delete all fixtures for this season (cascades should remove related data)
            Fixture.objects.filter(season=selected).delete()
            messages.success(request, "All matches for this season were deleted.")
            return redirect(f"{reverse('admin_manage_schedule')}?season={selected.pk}")

        elif action == "set_active":
            # Set the selected season as the single active season
            sid = request.POST.get("season_id")
            target = get_object_or_404(Season, pk=sid)
            # Clear any currently active season and set the target
            Season.objects.filter(is_active=True).update(is_active=False)
            target.is_active = True
            target.save(update_fields=["is_active"])
            messages.success(request, f"{target} is now the active season.")
            return redirect(f"{reverse('admin_manage_schedule')}?season={target.pk}")

    fixtures = Fixture.objects.filter(season=selected).order_by("week_number") if selected else []

    current_active = Season.objects.filter(is_active=True).first()

    return render(request, "league/admin_panel/manage_schedule.html", {
        "seasons": seasons,
        "selected": selected,
        "fixtures": fixtures,
        "add_form": add_form,
        "edit_form": edit_form,
        "edit_fixture_id": edit_fixture_id,
        "current_active": current_active,
    })

@login_required
@user_passes_test(is_staff_user)
def admin_schedule_export_csv(request):
    """
    Download the current season's schedule as a CSV in bulk-upload format.
    Columns: Week, Date (YYYY-MM-DD), Time (HH:MM), Opponent, Home/Away, Is BYE
    """
    import csv
    from django.http import HttpResponse

    # Resolve season: optional ?season=<id>; otherwise active season or newest
    season = None
    sid = request.GET.get("season")
    try:
        if sid:
            season = Season.objects.get(pk=sid)
        else:
            season = (Season.objects.filter(is_active=True).first()
                      or Season.objects.order_by("-year" if hasattr(Season, "year") else "-id").first())
    except Season.DoesNotExist:
        season = None

    if not season:
        messages.error(request, "No season selected or active to export.")
        return redirect("admin_manage_schedule")

    # CSV response
    safe_name = (getattr(season, "name", getattr(season, "title", "")) or "").strip().replace(" ", "_")
    filename = f"schedule_{getattr(season, 'year', '')}_{safe_name or 'season'}.csv"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    # Header to match bulk upload
    writer.writerow(["week_number", "date", "time", "opponent", "home", "bye"])

    # Fixtures
    qs = (Fixture.objects
          .filter(season=season)
          .order_by("week_number", "date", "id"))

    for fx in qs:
        # Local time formatting if tz-aware
        try:
            dt = timezone.localtime(fx.date) if getattr(fx, "date", None) else None
        except Exception:
            dt = fx.date
        date_str = dt.strftime("%Y-%m-%d") if dt else ""
        time_str = dt.strftime("%H:%M") if dt else ""

        week = getattr(fx, "week_number", None)
        try:
            week_val = int(week) if week not in (None, "") else ""
        except Exception:
            week_val = str(week) if week not in (None, "") else ""

        is_bye = bool(getattr(fx, "is_bye", False))
        opponent = "" if is_bye else (fx.opponent or "")
        home_bool = bool(getattr(fx, "home", False)) and not is_bye  # ignore 'home' when bye
        writer.writerow([
            week_val,
            date_str,
            time_str,
            opponent,
            "true" if home_bool else "false",
            "true" if is_bye else "false",
        ])

    return response

@login_required
@user_passes_test(is_staff_user)
def admin_manage_roster(request):
    seasons = Season.objects.all().order_by("-start_date") if hasattr(Season, "start_date") else Season.objects.all()
    selected_id = (
        request.GET.get("season")
        or request.GET.get("season_id")
        or request.POST.get("season")
        or request.POST.get("season_id")
    )
    selected = seasons.filter(pk=selected_id).first() if selected_id else seasons.first()

    # Ensure a default roster limit
    if selected and not getattr(selected, "roster_limit", None):
        selected.roster_limit = 22
        selected.save(update_fields=["roster_limit"]) if hasattr(selected, "pk") else None

    add_errors = []
    copy_errors = []

    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "set_limit":
            try:
                limit = int(request.POST.get("limit", 22))
                if limit < 1 or limit > 40:
                    raise ValueError
                selected.roster_limit = limit
                selected.save(update_fields=["roster_limit"])
                messages.success(request, "Roster size limit updated.")
            except Exception:
                messages.error(request, "Please enter a valid limit between 1 and 40.")
            return redirect(f"{reverse('admin_manage_roster')}?season={selected.pk}")

        elif action == "update_ntrp":
            entry = get_object_or_404(RosterEntry, pk=request.POST.get("entry_id"), season=selected)
            ntrp = (request.POST.get("ntrp") or "").strip()
            if ntrp not in NTRP_VALUES:
                messages.error(request, "Invalid NTRP value.")
            else:
                entry.ntrp = ntrp
                entry.save(update_fields=["ntrp"])
                messages.success(request, "NTRP updated.")
            return redirect(f"{reverse('admin_manage_roster')}?season={selected.pk}")

        elif action == "add":
            # Enforce roster limit
            current_count = RosterEntry.objects.filter(season=selected).count()
            if current_count >= (selected.roster_limit or 22):
                add_errors.append("Roster limit reached for this season.")
            player_id = request.POST.get("player_id")
            ntrp = (request.POST.get("ntrp") or "").strip()
            if not player_id:
                add_errors.append("Please select a player.")
            if ntrp not in NTRP_VALUES:
                add_errors.append("Please choose a valid NTRP value.")

            # Prevent duplicates
            if player_id and not add_errors:
                exists = RosterEntry.objects.filter(season=selected, player_id=player_id).exists()
                if exists:
                    add_errors.append("That player is already on this season's roster.")

            if add_errors:
                # fall through to render with errors and reopen modal
                pass
            else:
                RosterEntry.objects.create(season=selected, player_id=player_id, ntrp=ntrp)
                messages.success(request, "Player added to roster.")
                return redirect(f"{reverse('admin_manage_roster')}?season={selected.pk}")

        elif action == "remove":
            entry = get_object_or_404(RosterEntry, pk=request.POST.get("entry_id"), season=selected)
            entry.delete()
            messages.success(request, "Player removed from roster.")
            return redirect(f"{reverse('admin_manage_roster')}?season={selected.pk}")

        elif action == "copy_from":
            source_id = request.POST.get("source_season_id")
            if not source_id:
                copy_errors.append("Please choose a source season.")
            else:
                try:
                    source = Season.objects.get(pk=source_id)
                except Season.DoesNotExist:
                    copy_errors.append("Selected source season was not found.")
                    source = None

            if source and selected and source.pk == selected.pk:
                copy_errors.append("Cannot copy from the same season.")

            if not copy_errors and source and selected:
                # Gather source entries (players + NTRP + captain flag)
                src_entries = list(
                    RosterEntry.objects.filter(season=source)
                    .select_related("player")
                    .order_by("player__last_name", "player__first_name")
                )
                if not src_entries:
                    copy_errors.append("The selected source season has no roster to copy.")
                else:
                    # Skip players already on target season
                    existing_ids = set(
                        RosterEntry.objects.filter(season=selected).values_list("player_id", flat=True)
                    )
                    to_copy = [e for e in src_entries if e.player_id not in existing_ids]

                    if not to_copy:
                        copy_errors.append("All players from the source season are already on this season's roster.")
                    else:
                        # Enforce roster limit
                        limit = selected.roster_limit or 22
                        current_count = RosterEntry.objects.filter(season=selected).count()
                        slots = max(0, limit - current_count)
                        if slots <= 0:
                            copy_errors.append("Roster limit already reached for this season.")
                        else:
                            chosen = to_copy[:slots]
                            # Create entries, preserving NTRP and per-season captain flag
                            objs = [
                                RosterEntry(
                                    season=selected,
                                    player=e.player,
                                    ntrp=e.ntrp,
                                    is_captain=e.is_captain,
                                ) for e in chosen
                            ]
                            RosterEntry.objects.bulk_create(objs, ignore_conflicts=True)
                            added = len(objs)
                            skipped_dup = len(to_copy) - len(chosen)
                            if skipped_dup > 0:
                                messages.warning(
                                    request,
                                    f"Copied {added} player(s). {skipped_dup} could not be added due to roster limit or duplicates.",
                                )
                            else:
                                messages.success(request, f"Copied {added} player(s) from {source}.")
                            return redirect(f"{reverse('admin_manage_roster')}?season={selected.pk}")
            # Fall-through: show errors in the copy modal

    # Build page context
    roster_entries = (
        RosterEntry.objects
        .filter(season=selected)
        .select_related("player")
        .order_by("player__last_name", "player__first_name")
        if selected else []
    )

    # Players not already on this season's roster
    if selected:
        current_ids = list(roster_entries.values_list("player_id", flat=True))
        available_players = Player.objects.exclude(id__in=current_ids).order_by("last_name", "first_name")
    else:
        available_players = Player.objects.none()

    # Seasons with at least one roster entry (current season will be disabled in the UI)
    if selected:
        copy_source_seasons = (
            Season.objects.filter(roster_entries__isnull=False)
            .distinct()
            .order_by("-year" if hasattr(Season, "year") else "id")
        )
    else:
        copy_source_seasons = Season.objects.none()

    return render(request, "league/admin_panel/manage_roster.html", {
        "seasons": seasons,
        "selected": selected,
        "roster_entries": roster_entries,
        "available_players": available_players,
        "add_errors": add_errors,
        "copy_source_seasons": copy_source_seasons,
        "copy_errors": copy_errors,
    })

@login_required
@user_passes_test(is_staff_user)
def admin_manage_scores(request):
    # Seasons list for admin: all seasons, newest first
    seasons = Season.objects.all().order_by("-year" if hasattr(Season, "year") else "-id")

    sel_id = request.GET.get("season")
    selected = seasons.filter(pk=sel_id).first() if sel_id else None
    if not selected and hasattr(Season, "is_active"):
        selected = seasons.filter(is_active=True).first()
    if not selected:
        selected = seasons.first()

    fixtures = Fixture.objects.filter(season=selected).order_by("week_number") if selected else []

    # Annotate fixtures with scoring state and sub points
    now = timezone.now()
    fixtures = list(fixtures)  # materialize for reuse

    # Precompute sub points per fixture in one query
    sub_totals = (
        SubResult.objects
        .filter(fixture__in=fixtures)
        .values('fixture_id')
        .annotate(total=Sum('points_cached'))
    )
    sub_map = {row['fixture_id']: (row['total'] or 0) for row in sub_totals}

    for f in fixtures:
        f.can_score = (not getattr(f, "is_bye", False)) and (f.date <= now)
        # Calculate match score display like "12-0" if any SlotScores exist
        h, a = compute_fixture_match_points(f)
        f.match_score_display = f"{h}-{a}" if SlotScore.objects.filter(fixture=f).exists() else ""
        # Attach sub points for this week (do not affect match total)
        f.sub_points = sub_map.get(f.id, 0)

    return render(request, "league/admin_panel/manage_scores.html", {
        "seasons": seasons,
        "selected": selected,
        "fixtures": fixtures,
    })


# --- Score entry view ---
@login_required
@user_passes_test(is_staff_user)
@rl_deco(key='ip', rate='30/m', method='POST', block=True)
def admin_enter_scores(request, fixture_id):
    fixture = get_object_or_404(Fixture, pk=fixture_id)

    # Guard: cannot score BYE or future matches
    if fixture.date > timezone.now():
        messages.info(request, "This match is in the future — scores can be entered after it ends.")
        return redirect("admin_manage_scores")

    # Ensure lineup slots exist (so we can show player names)
    lineup, _ = Lineup.objects.get_or_create(fixture=fixture, defaults={"created_by": request.user})
    for code in SLOT_CODES:
        LineupSlot.objects.get_or_create(lineup=lineup, slot=code)

    # Load existing slot scores into a dict keyed by slot code
    existing = {s.slot_code: s for s in SlotScore.objects.filter(fixture=fixture)}

    if request.method == "POST":
        # Expect fields like: score-S1-home, score-S1-away, score-S1-result
        errors = []
        to_save = []
        for code in SLOT_CODES:
            home_val = request.POST.get(f"score-{code}-home")
            away_val = request.POST.get(f"score-{code}-away")
            result_val = request.POST.get(f"score-{code}-result")

            # Allow leaving an entire row blank (skip saving)
            if not any([home_val, away_val, result_val]):
                continue

            # Validate result choice first
            valid_results = {c[0] for c in SlotScore.Result.choices}
            if result_val not in valid_results:
                errors.append(f"{code}: Invalid result.")
                continue

            # For forfeits, allow 0–0 and even blank inputs (we'll coerce to 0)
            is_forfeit = result_val in {SlotScore.Result.WIN_FF, SlotScore.Result.LOSS_FF}
            try:
                if is_forfeit:
                    home_games = int(home_val) if (home_val is not None and home_val != "") else 0
                    away_games = int(away_val) if (away_val is not None and away_val != "") else 0
                    if home_games < 0 or away_games < 0:
                        raise ValueError
                else:
                    # Non-forfeit results require explicit non-negative integers
                    if home_val in (None, "") or away_val in (None, ""):
                        raise ValueError
                    home_games = int(home_val)
                    away_games = int(away_val)
                    if home_games < 0 or away_games < 0:
                        raise ValueError
            except Exception:
                errors.append(f"{code}: Home/Away games must be non-negative integers.")
                continue

            obj = existing.get(code) or SlotScore(fixture=fixture, slot_code=code)
            obj.home_games = home_games
            obj.away_games = away_games
            obj.result = result_val
            to_save.append(obj)

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            # Save all slot scores
            for obj in to_save:
                obj.save()
            # Recompute per-player points
            recompute_fixture_player_points(fixture)

            # Notify lineup participants and sub-result players
            # (consolidated notify ensures DeliveryAttempts + rich in-app content)
            try:
                # Overall match score text
                h, a = compute_fixture_match_points(fixture)
                score_text = f"{h}-{a}"
                try:
                    from django.utils import timezone as _tz
                    when_text = _tz.localtime(fixture.date).strftime("%b %d, %Y") if getattr(fixture, "date", None) else ""
                except Exception:
                    when_text = fixture.date.strftime("%b %d, %Y") if getattr(fixture, "date", None) else ""

                # Map per-slot scores for this fixture by slot code (e.g., 'S1', 'D2')
                scores_by_slot = {s.slot_code: s for s in SlotScore.objects.filter(fixture=fixture)}

                def _slot_score_text(slot_code: str) -> str:
                    s = scores_by_slot.get(slot_code)
                    if not s:
                        return ""
                    try:
                        hg = s.home_games if s.home_games is not None else ""
                        ag = s.away_games if s.away_games is not None else ""
                        if hg == "" and ag == "":
                            return ""
                        return f"{hg}-{ag}"
                    except Exception:
                        return ""

                if lineup:
                    logger.info("RESULT_NOTIFY: lineup players fixture=%s", getattr(fixture, "id", None))

                    users = []
                    per_user_ctx = {}
                    seen_user_ids = set()

                    # Helper for slot label
                    def _slot_label(slot_obj):
                        try:
                            return slot_obj.get_slot_display()
                        except Exception:
                            return getattr(slot_obj, "slot", "TBD")

                    slots_qs = lineup.slots.select_related("player1__user", "player2__user")
                    for ls in slots_qs:
                        label = _slot_label(ls)
                        is_doubles = str(getattr(ls, "slot", "")).upper().startswith("D")

                        for pl in (ls.player1, ls.player2):
                            if pl and getattr(pl, "user_id", None):
                                u = pl.user
                                if u.id not in seen_user_ids:
                                    users.append(u)
                                    seen_user_ids.add(u.id)
                                extras = {
                                    "slot_label": label,
                                    "slot_name": label,  # alias for templates
                                    "is_doubles": is_doubles,
                                    "player_first_name": getattr(u, "first_name", None),
                                }
                                if is_doubles:
                                    # partner is the other player in this ls
                                    other = ls.player2 if pl == ls.player1 else ls.player1
                                    if other and getattr(other, "user", None):
                                        extras["partner_full_name"] = f"{other.user.first_name} {other.user.last_name}".strip()
                                per_user_ctx[u.id] = extras

                                extras["result_text"] = _slot_score_text(getattr(ls, "slot", None))
                                per_user_ctx[u.id] = extras

                    if users:
                        detail_url = request.build_absolute_uri(reverse("fixture_detail", args=[fixture.id]))
                        base_ctx = {
                            "fixture": fixture,
                            "match_dt": getattr(fixture, "date", None),
                            "opponent": getattr(fixture, "opponent", ""),
                            "fixture_url": detail_url,
                            "result_text": score_text,
                            "_per_user_ctx": per_user_ctx,
                            "_user_player_map": {u.id: getattr(u, "player_profile", None) for u in users},
                        }
                        logger.info("RESULT_NOTIFY: users=%s", [getattr(u, "id", None) for u in users])
                        notif, attempts = send_event("RESULT_POSTED_FOR_PLAYER", users=users, season=fixture.season,
                                                     fixture=fixture,
                                                     title=f"Results posted — vs {fixture.opponent or 'Opponent'}",
                                                     body=f"Final: {score_text} on {when_text}.", url=detail_url,
                                                     context=base_ctx, per_user_ctx=per_user_ctx,
                                                     user_player_map=base_ctx.get("_user_player_map"))
                        attempts_count = attempts if isinstance(attempts, int) else (len(attempts) if attempts is not None else None)
                        logger.info("RESULT_NOTIFY: created notif=%s attempts=%s", getattr(notif, 'id', None),attempts_count)
                else:
                    logger.info("RESULT_NOTIFY: no lineup on fixture=%s", getattr(fixture, "id", None))

                # Sub results notifications (one per sub player)
                try:
                    subs = list(SubResult.objects.filter(fixture=fixture).select_related("player__user"))
                except Exception:
                    subs = []
                if subs:
                    detail_url = request.build_absolute_uri(reverse("fixture_detail", args=[fixture.id]))
                for sr in subs:
                    u = getattr(getattr(sr, "player", None), "user", None)
                    if not u:
                        continue
                    label = sr.get_slot_code_display() if hasattr(sr, "get_slot_code_display") else getattr(sr, "slot_code", "TBD")
                    extras = {
                        "slot_label": label,
                        "slot_name": label,
                        "is_doubles": str(getattr(sr, "kind", "")).upper().startswith("D"),
                        "player_first_name": getattr(u, "first_name", None),
                    }

                    # Prefer explicit sub team name on SubResult; fall back to linked SubPlan.target_team_name if available
                    sub_team_name = getattr(sr, "target_team_name", None)
                    if not sub_team_name:
                        try:
                            plan = getattr(sr, "plan", None)
                            if plan is not None:
                                sub_team_name = getattr(plan, "target_team_name", None)
                        except Exception:
                            sub_team_name = None
                    if sub_team_name:
                        extras["sub_team_name"] = sub_team_name

                    # Prefer SubResult’s own games if available; else look up SlotScore
                    sr_hg = getattr(sr, "home_games", None)
                    sr_ag = getattr(sr, "away_games", None)
                    if sr_hg is not None and sr_ag is not None:
                        extras["result_text"] = f"{sr_hg}-{sr_ag}"
                    else:
                        extras["result_text"] = _slot_score_text(getattr(sr, "slot_code", None))

                    base_ctx = {
                        "fixture": fixture,
                        "match_dt": getattr(fixture, "date", None),
                        "opponent": getattr(fixture, "opponent", ""),
                        "fixture_url": detail_url,
                        "result_text": score_text,
                        "_per_user_ctx": {u.id: extras},
                        "_user_player_map": {u.id: getattr(sr, "player", None)},
                    }
                    logger.info("RESULT_NOTIFY_SUB: user=%s fixture=%s label=%s", getattr(u, "id", None), getattr(fixture, "id", None), label)
                    notif, attempts = send_event("RESULT_POSTED_FOR_PLAYER", users=[u], season=fixture.season,
                                                 fixture=fixture,
                                                 title=f"Result posted (sub) — vs {sub_team_name or 'Opponent'}",
                                                 subject="Royals: Your sub match result is posted",
                                                 body=f"Final: {score_text} on {when_text}.", url=detail_url,
                                                 context=base_ctx, per_user_ctx=base_ctx.get("_per_user_ctx"),
                                                 user_player_map=base_ctx.get("_user_player_map"))
                    attempts_count = attempts if isinstance(attempts, int) else (len(attempts) if attempts is not None else None)
                    logger.info("RESULT_NOTIFY_SUB: created notif=%s attempts=%s for user=%s",getattr(notif, "id", None), attempts_count, getattr(u, "id", None))
            except Exception as e:
                logger.exception("RESULT_NOTIFY: error fixture=%s: %s", getattr(fixture, "id", None), e)

            messages.success(request, "Scores saved.")
            return redirect("admin_enter_scores", fixture_id=fixture.id)

    # Build context for template: slot rows with lineup names and any existing scores
    slots = list(LineupSlot.objects.filter(lineup=lineup).order_by("slot"))
    rows = []
    for ls in slots:
        score = existing.get(ls.slot)
        rows.append({
            "slot": ls.slot,
            "slot_label": ls.get_slot_display(),
            "p1": ls.player1,
            "p2": ls.player2,
            "home_games": getattr(score, "home_games", ""),
            "away_games": getattr(score, "away_games", ""),
            "result": getattr(score, "result", ""),
        })

    # Compute current totals for the info panel
    match_home_total, match_away_total = compute_fixture_match_points(fixture)

    # Sub Results panel data
    sub_results = SubResult.objects.filter(fixture=fixture).order_by("timeslot", "player__last_name", "player__first_name")
    sub_plans_unrecorded = (
        SubPlan.objects.filter(fixture=fixture)
        .exclude(results__isnull=False)  # plans that do NOT have any linked result
        .order_by("timeslot", "player__last_name", "player__first_name")
    )

    return render(request, "league/admin_panel/enter_scores.html", {
        "fixture": fixture,
        "rows": rows,
        "result_choices": SlotScore.Result.choices,
        "match_home_total": match_home_total,
        "match_away_total": match_away_total,
        "sub_results": sub_results,
        "sub_plans_unrecorded": sub_plans_unrecorded,
    })


@login_required
def dashboard(request):
    player = getattr(request.user, "player_profile", None)
    now = timezone.now()

    # Prefer the active season if the player is rostered on it; otherwise fall back
    active_season = Season.objects.filter(is_active=True).first()
    season_for_cards = None
    if player and active_season and RosterEntry.objects.filter(season=active_season, player=player).exists():
        season_for_cards = active_season
    elif player:
        # Fall back to the most recent season this player is rostered on
        season_for_cards = (
            Season.objects
            .filter(roster_entries__player=player)
            .order_by("-year" if hasattr(Season, "year") else "-id")
            .first()
        )

    upcoming = (
        Fixture.objects
        .filter(date__gte=now, season=season_for_cards)
        .order_by("date")
        .first()
        if (player and season_for_cards) else None
    )

    previous = (
        Fixture.objects
        .filter(date__lt=now, season=season_for_cards)
        .order_by("-date")
        .first()
        if (player and season_for_cards) else None
    )

    # Do NOT auto-create availability; just show current status if it exists
    player_avail = None
    if player and upcoming:
        player_avail = Availability.objects.filter(player=player, fixture=upcoming).first()

    # Build previous result text/class if any slot scores exist
    previous_result_text = ""
    previous_result_class = ""
    previous_sub_points = None
    if previous and SlotScore.objects.filter(fixture=previous).exists():
        h, a = compute_fixture_match_points(previous)
        if h > a:
            previous_result_text = f"Win ({h}-{a})"
            previous_result_class = "text-success fw-bold"
        elif h < a:
            previous_result_text = f"Loss ({h}-{a})"
            previous_result_class = "text-warning"  # orange-ish
        else:
            previous_result_text = f"Tie ({h}-{a})"
            previous_result_class = "text-warning"  # per request, show tie in orange
    # Compute previous_sub_points for the previous fixture
    if previous:
        agg = SubResult.objects.filter(fixture=previous).aggregate(total=Sum('points_cached'))
        previous_sub_points = agg['total'] or 0
        try:
            previous_sub_points = int(previous_sub_points) if float(previous_sub_points).is_integer() else previous_sub_points
        except Exception:
            pass

    # --- Points tiles (active season only; show only if player is rostered on active season) ---
    # (active_season already computed above; reuse it)
    show_points_tiles = False

    # Helpers to be Decimal-safe
    def _D(x):
        try:
            return x if isinstance(x, Decimal) else Decimal(str(x))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    def _norm_display(d: Decimal):
        # Return int when whole number; else float for .5 etc.
        f = float(d)
        return int(f) if f.is_integer() else f

    my_points_total = 0  # display value
    team_points_total = 0  # display value

    if player and active_season and RosterEntry.objects.filter(season=active_season, player=player).exists():
        show_points_tiles = True

        # Player lineup points (Decimal)
        pmp_agg = PlayerMatchPoints.objects.filter(
            fixture__season=active_season, player=player
        ).aggregate(total=Sum("points"))
        my_points_dec = _D(pmp_agg["total"] or 0)

        # Add sub points earned by this player in this season (Decimal)
        sub_me_agg = SubResult.objects.filter(
            fixture__season=active_season, player=player
        ).aggregate(total=Sum("points_cached"))
        my_points_dec += _D(sub_me_agg["total"] or 0)

        # Team match points from fixture results (sum home totals as Decimal)
        team_match_dec = Decimal("0")
        fixtures_as_list = list(Fixture.objects.filter(season=active_season))
        for fx in fixtures_as_list:
            h, _a = compute_fixture_match_points(fx)  # h can be int/float
            team_match_dec += _D(h)

        # Team sub points (Decimal)
        sub_agg = SubResult.objects.filter(fixture__season=active_season).aggregate(total=Sum("points_cached"))
        team_sub_dec = _D(sub_agg["total"] or 0)

        # Final display-friendly numbers
        my_points_total = _norm_display(my_points_dec)
        team_points_total = _norm_display(team_match_dec + team_sub_dec)

    # --- My Record doughnut counts ---
    record_wins = record_losses = record_ties = 0
    if player:
        season_for_record = None

        # Helper: does this season have any recorded results for this player?
        def season_has_results(season):
            if not season:
                return False
            has_lineup_scores = SlotScore.objects.filter(
                fixture__season=season,
                fixture__lineup__slots__in=LineupSlot.objects.filter(
                    lineup__fixture__season=season
                ).filter(Q(player1=player) | Q(player2=player))
            ).exists()
            has_sub_results = SubResult.objects.filter(
                fixture__season=season, player=player
            ).exists()
            return has_lineup_scores or has_sub_results

        # Prefer active season if rostered AND it has results
        if active_season and RosterEntry.objects.filter(season=active_season, player=player).exists() and season_has_results(active_season):
            season_for_record = active_season
        else:
            # Fall back: pick the most recent season (by fixture date) where the player has results
            from django.db.models import Max
            latest_lineup = (
                SlotScore.objects
                .filter(
                    fixture__lineup__slots__in=LineupSlot.objects.filter(Q(player1=player) | Q(player2=player))
                )
                .aggregate(latest=Max('fixture__date'))['latest']
            )
            latest_sub = (
                SubResult.objects
                .filter(player=player)
                .aggregate(latest=Max('fixture__date'))['latest']
            )

            # Decide which timestamp is newer
            chosen_dt = None
            if latest_lineup and latest_sub:
                chosen_dt = latest_lineup if latest_lineup >= latest_sub else latest_sub
            else:
                chosen_dt = latest_lineup or latest_sub

            if chosen_dt:
                # Fetch that fixture and its season
                fx = Fixture.objects.filter(date=chosen_dt).order_by('-id').first()
                if fx:
                    season_for_record = fx.season

        if season_for_record:
            # Build a lookup of SlotScore by fixture_id -> slot_code
            scores_by_fixture = {}
            for s in SlotScore.objects.filter(fixture__season=season_for_record):
                bucket = scores_by_fixture.setdefault(s.fixture_id, {})
                bucket[s.slot_code] = s

            # Count lineup results for this player in that season
            player_slots_qs = (
                LineupSlot.objects
                .filter(lineup__fixture__season=season_for_record)
                .filter(Q(player1=player) | Q(player2=player))
                .select_related('lineup__fixture')
            )
            for ls in player_slots_qs:
                sc = scores_by_fixture.get(ls.lineup.fixture_id, {}).get(ls.slot)
                if not sc:
                    continue
                if sc.result in (SlotScore.Result.WIN, SlotScore.Result.WIN_FF, 'W', 'WF'):
                    record_wins += 1
                elif sc.result in (SlotScore.Result.LOSS, SlotScore.Result.LOSS_FF, 'L', 'LF'):
                    record_losses += 1
                elif sc.result in (SlotScore.Result.TIE, 'T'):
                    record_ties += 1

            # Count sub results for this player in that season
            sub_qs = SubResult.objects.filter(fixture__season=season_for_record, player=player)
            for sr in sub_qs:
                if sr.result in (SlotScore.Result.WIN, SlotScore.Result.WIN_FF, 'W', 'WF'):
                    record_wins += 1
                elif sr.result in (SlotScore.Result.LOSS, SlotScore.Result.LOSS_FF, 'L', 'LF'):
                    record_losses += 1
                elif sr.result in (SlotScore.Result.TIE, 'T'):
                    record_ties += 1

    # Add to context
    extra_record_ctx = {
        "record_wins": record_wins,
        "record_losses": record_losses,
        "record_ties": record_ties,
    }

    # Ensure NotificationPreference is available and fresh for templates
    try:
        from .models import NotificationPreference
        prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)
        try:
            prefs.refresh_from_db()
        except Exception:
            pass
        try:
            # Bind onto the user so templates using request.user.notificationpreference see THIS instance
            setattr(request.user, "notificationpreference", prefs)
        except Exception:
            pass
    except Exception:
        prefs = None

    # --- League standings (published) ---
    standings = []
    if active_season:
        try:
            from .models import LeagueStanding
            standings = LeagueStanding.objects.filter(
                season=active_season,
                published=True
            ).order_by("-points", "team_name")
        except Exception:
            standings = []

    return render(request, "league/dashboard.html", {
        "player": player,
        "upcoming": upcoming,
        "player_avail": player_avail,
        "previous": previous,
        "previous_result_text": previous_result_text,
        "previous_result_class": previous_result_class,
        "previous_sub_points": previous_sub_points,
        "active_season": active_season,
        "show_points_tiles": show_points_tiles,
        "my_points_total": my_points_total,
        "team_points_total": team_points_total,
        "prefs": prefs,
        "league_standings": standings,
        **extra_record_ctx,
    })

@login_required
def schedule_list(request):
    player = getattr(request.user, "player_profile", None)

    # Captains/staff can view all seasons; players see only seasons they're rostered on
    if is_captain(request.user) or is_staff_user(request.user):
        seasons_qs = Season.objects.all()
    else:
        seasons_qs = (
            Season.objects.filter(roster_entries__player=player).distinct()
            if player else Season.objects.none()
        )

    # Determine selected season: URL param > active season (if on roster) > most recent rostered season
    sel_id = request.GET.get("season")
    selected = None
    if sel_id:
        selected = seasons_qs.filter(pk=sel_id).first()
    if not selected and player:
        selected = seasons_qs.filter(is_active=True).first()
    if not selected:
        # Fall back to most recently created/defined
        order_field = "-year" if hasattr(Season, "year") else "-id"
        selected = seasons_qs.order_by(order_field).first()

    if not selected:
        fixtures = Fixture.objects.none()
    # Fixtures limited to selected season
    else:
        fixtures = Fixture.objects.filter(season=selected).order_by("date")

    # Build a map of availability for the current user
    avail_map = {}
    if player and selected:
        qs = Availability.objects.filter(player=player, fixture__in=fixtures).values_list("fixture_id", "status")
        avail_map = {fid: status for fid, status in qs}

    # Attach user_status to each fixture (None if no response)
    for f in fixtures:
        f.user_status = avail_map.get(f.id)

    # Attach result text like "Win (7-5)" / "Loss (5-7)" / "Tie (6-6)"
    if fixtures:
        from django.db.models import Count
        score_counts = dict(
            SlotScore.objects.filter(fixture__in=fixtures)
            .values_list("fixture_id")
            .annotate(n=Count("id"))
        )
        for f in fixtures:
            if score_counts.get(f.id):
                h, a = compute_fixture_match_points(f)
                if h > a:
                    f.result_text = f"Win ({h}-{a})"
                elif h < a:
                    f.result_text = f"Loss ({h}-{a})"
                else:
                    f.result_text = f"Tie ({h}-{a})"
            else:
                f.result_text = ""

    # Attach per-timeslot sub availability for the current player (set of codes per fixture)
    if player and selected and fixtures:
        rows = SubAvailability.objects.filter(
            player=player, fixture__in=fixtures
        ).values_list("fixture_id", "timeslot")

        from collections import defaultdict
        smap = defaultdict(set)
        for fid, ts in rows:
            smap[fid].add(ts)

        for f in fixtures:
            f.sub_avail_timeslots = smap.get(f.id, set())

    return render(request, "league/schedule_list.html", {
        "fixtures": fixtures,
        "seasons": seasons_qs.order_by("-year" if hasattr(Season, "year") else "-id"),
        "selected": selected,
    })


# --- My Results View ---
@login_required
def my_results(request):
    player = getattr(request.user, "player_profile", None)
    if not player:
        messages.error(request, "No player profile linked to your account. Ask the captain to link you.")
        return redirect("dashboard")

    # Seasons where this player has activity (either appeared in lineup or has points recorded)
    seasons_qs = (
        Season.objects.filter(
            Q(fixtures__lineup__slots__player1=player) |
            Q(fixtures__lineup__slots__player2=player) |
            Q(fixtures__player_points__player=player)  # <-- correct related_name
        )
        .distinct()
        .order_by("-year" if hasattr(Season, "year") else "-id")
    )

    # Default season: active if the player is rostered there; else most recent season with activity
    sel_id = request.GET.get("season")
    selected = None

    if sel_id:
        selected = seasons_qs.filter(pk=sel_id).first()

    if not selected:
        active = Season.objects.filter(is_active=True).first()
        if active and RosterEntry.objects.filter(season=active, player=player).exists():
            selected = active

    if not selected:
        selected = seasons_qs.first()

    # Build rows for the selected season
    rows = []
    fixtures = []
    if selected:
        fixtures = (
            Fixture.objects.filter(season=selected)
            .order_by("date")
        )
        # Find the player's slot per fixture (if any)
        player_slots = {
            ls.lineup.fixture_id: ls for ls in (
                LineupSlot.objects
                .filter(lineup__fixture__in=fixtures)
                .filter(Q(player1=player) | Q(player2=player))
                .select_related("lineup__fixture", "player1", "player2")
            )
        }
        # Points per fixture for this player
        ppoints = {
            pmp.fixture_id: pmp.points for pmp in PlayerMatchPoints.objects.filter(
                fixture__in=fixtures, player=player
            )
        }
        for f in fixtures:
            ls = player_slots.get(f.id)
            if not ls:
                # Skip fixtures the player did not play in (shows only matches played)
                continue
            # Slot result (if scored)
            ss = SlotScore.objects.filter(fixture=f, slot_code=ls.slot).first()
            result_text = ""
            games_text = ""
            if ss:
                # Overall match result label for the slot
                if ss.result in (SlotScore.Result.WIN, SlotScore.Result.WIN_FF):
                    result_text = "Win"
                elif ss.result in (SlotScore.Result.LOSS, SlotScore.Result.LOSS_FF):
                    result_text = "Loss"
                elif ss.result == SlotScore.Result.TIE:
                    result_text = "Tie"
                games_text = f"({ss.home_games}-{ss.away_games})"

            # Points credited to this player for the fixture
            pts = ppoints.get(f.id, 0)

            # Determine teammate (for doubles slots only)
            teammate = None
            if ls.slot.startswith("D"):
                if ls.player1_id == player.id:
                    teammate = ls.player2
                elif ls.player2_id == player.id:
                    teammate = ls.player1

            rows.append({
                "fixture": f,
                "date": f.date,
                "opponent": f.opponent,
                "home": f.home,
                "slot": ls.get_slot_display(),
                "is_doubles": ls.slot.startswith("D"),
                "teammate": teammate,
                "result_text": result_text,
                "games_text": games_text,
                "points": pts,
            })

        # --- Also include SUB RESULTS for this player in this season ---
        sub_qs = (
            SubResult.objects
            .filter(fixture__in=fixtures, player=player)
            .select_related("fixture")
            .order_by("fixture__date", "timeslot")
        )
        for sr in sub_qs:
            # Result label
            if sr.result in (SlotScore.Result.WIN, SlotScore.Result.WIN_FF):
                rlabel = "Win"
            elif sr.result in (SlotScore.Result.LOSS, SlotScore.Result.LOSS_FF):
                rlabel = "Loss"
            elif sr.result == SlotScore.Result.TIE:
                rlabel = "Tie"
            else:
                rlabel = ""
            games_text = f"({sr.home_games}-{sr.away_games})" if sr.home_games is not None and sr.away_games is not None else ""

            # Resolve opponent label for sub results
            opp_label = sr.fixture.opponent
            try:
                tt = getattr(sr, "target_type", None)
                other_team_val = getattr(getattr(SubResult, "Target", None), "OTHER_TEAM", "OTHER_TEAM")
                if tt and (str(tt).upper() == str(other_team_val).upper()):
                    if getattr(sr, "target_team_name", ""):
                        opp_label = sr.target_team_name
            except Exception:
                pass

            rows.append({
                "fixture": sr.fixture,
                "date": sr.fixture.date,
                "opponent": opp_label,
                "home": sr.fixture.home,
                "slot": sr.get_slot_code_display(),
                "is_doubles": sr.kind == SubResult.Kind.DOUBLES if hasattr(SubResult, "Kind") else (str(sr.kind).upper().startswith("D")),
                "teammate": None,  # subs are recorded per player
                "result_text": rlabel + " (Sub)",
                "games_text": games_text,
                "points": sr.points_cached or 0,
                "is_sub": True,
            })

        # Sort all rows by date ascending
        rows.sort(key=lambda r: r["date"]) if rows else None
    # Aggregate total points for the selected season (player only + sub points)
    total_points = 0
    if selected:
        agg = PlayerMatchPoints.objects.filter(
            fixture__season=selected,
            player=player
        ).aggregate(total=Sum('points'))
        total_points = agg['total'] or 0
        sub_agg = SubResult.objects.filter(
            fixture__season=selected,
            player=player
        ).aggregate(total=Sum('points_cached'))
        total_points += sub_agg['total'] or 0

    context = {
        "seasons": seasons_qs,
        "selected": selected,
        "rows": rows,
        "total_points": total_points,
        "has_sub_rows": any(getattr(r, "get", lambda k, d=None: r.get(k, d))("is_sub", False) if isinstance(r, dict) else False for r in rows),
    }
    return render(request, "league/my_results.html", context)

@login_required
def fixture_detail(request, pk):
    fixture = (
        Fixture.objects
        .select_related("season")
        .prefetch_related("sub_plans__results")  # prefetch sub plan → results relation
        .get(pk=pk)
    )
    player = getattr(request.user, "player_profile", None)
    if player and not player_on_roster(player, fixture.season):
        messages.info(request, "You’re not on this season’s roster, so this match isn’t available to you.")
        return redirect("schedule_list")
    lineup = getattr(fixture, "lineup", None)
    avail = Availability.objects.filter(player=player, fixture=fixture).first() if player else None

    # --- Captain UX: SubPlan conflict highlighting ---
    # A conflict occurs when a player is in the published lineup AND has a SubPlan at the SAME timeslot as the fixture.
    from .models import SubPlan, LineupSlot
    sub_plans = SubPlan.objects.filter(fixture=fixture).select_related("player").order_by("timeslot", "player__last_name", "player__first_name")

    # Collect lineup players if lineup exists and is published
    lineup_players = set()
    if lineup and getattr(lineup, "published", False):
        for ls in LineupSlot.objects.filter(lineup=lineup):
            if ls.player1_id:
                lineup_players.add(ls.player1_id)
            if ls.player2_id:
                lineup_players.add(ls.player2_id)

    fx_timeslot = fixture.timeslot_code() if hasattr(fixture, "timeslot_code") else None
    # Annotate each plan instance in-memory
    for sp in sub_plans:
        sp.conflict = bool(
            fx_timeslot and sp.timeslot == fx_timeslot and sp.player_id in lineup_players
        )

    return render(request, "league/fixture_detail.html", {
        "fixture": fixture,
        "lineup": lineup,
        "availability": avail,
        "sub_plans": sub_plans,
    })

@login_required
@rl_deco(key='ip', rate='30/m', method='POST', block=True)
def availability_update(request, fixture_id):
    fixture = get_object_or_404(Fixture, pk=fixture_id)

    player = getattr(request.user, "player_profile", None)
    if not player:
        messages.error(request, "No player profile linked to your account. Ask the captain to link you.")
        return redirect("dashboard")
    if not player_on_roster(player, fixture.season):
        messages.error(request, "You’re not on this season’s roster for this match.")
        return redirect("fixture_detail", pk=fixture_id)

    # ⛔ Server-side guard for BYE weeks
    if getattr(fixture, "is_bye", False):
        messages.info(request, "This is a bye week — availability isn’t needed.")
        return redirect("fixture_detail", pk=fixture_id)

    # ⛔ Server-side guard: block availability changes once any scores exist
    if SlotScore.objects.filter(fixture=fixture).exists():
        messages.info(request, "Availability is closed for this match.")
        return redirect("fixture_detail", pk=fixture_id)

    availability = Availability.objects.filter(player=player, fixture=fixture).first()
    if request.method == "POST":
        form = AvailabilityForm(request.POST, instance=availability)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.pk is None:
                obj.player = player
                obj.fixture = fixture
            obj.save()
            messages.success(request, "Availability updated.")
            return redirect("fixture_detail", pk=fixture_id)
    else:
        form = AvailabilityForm(instance=availability)
    return render(request, "league/availability_form.html", {"form": form, "fixture": fixture})

@login_required
@user_passes_test(is_captain)
def admin_availability_matrix(request, fixture_id):
    fixture = get_object_or_404(Fixture, pk=fixture_id)

    # ⛔ Server-side guard for BYE weeks
    # commenting out to allow for sub availability to be maintained
    ##if getattr(fixture, "is_bye", False):
    ##    messages.info(request, "Bye week — captain availability matrix is not applicable.")
    ##    return redirect("fixture_detail", pk=fixture_id)

    # Only show submitted availability — do NOT auto-create rows
    rows = (
        Availability.objects
        .filter(fixture=fixture)
        .select_related("player")
        .order_by("player__last_name", "player__first_name")
    )

    # --- Sub Availability matrix data ---
    from collections import defaultdict

    # Raw sub availability (who said yes for which timeslots)
    sub_qs = (
        SubAvailability.objects
        .filter(fixture=fixture)
        .select_related("player")
        .order_by("player__last_name", "player__first_name")
    )

    # Build maps: player_id -> set(timeslot), and player_id -> Player
    sub_map = defaultdict(set)
    players_map = {}
    for sa in sub_qs:
        sub_map[sa.player_id].add(sa.timeslot)
        players_map[sa.player_id] = sa.player

    # Slot counters (how many players available per timeslot)
    sub_counts = {"0830": 0, "1000": 0, "1130": 0}
    for codes in sub_map.values():
        for ts in ("0830", "1000", "1130"):
            if ts in codes:
                sub_counts[ts] += 1

    # Determine the fixture's single timeslot code (e.g., "0830")
    fx_ts = fixture.timeslot_code() if hasattr(fixture, "timeslot_code") else None

    # Players already in the published lineup for THIS fixture (busy at fx_ts)
    lineup_players = set()
    lineup = getattr(fixture, "lineup", None)
    if lineup and getattr(lineup, "published", False):
        for ls in LineupSlot.objects.filter(lineup=lineup):
            if ls.player1_id:
                lineup_players.add(ls.player1_id)
            if ls.player2_id:
                lineup_players.add(ls.player2_id)

    # Sub plans already created for this fixture (mark as planned for that timeslot)
    planned_pairs = set()  # {(timeslot, player_id)}
    for sp in SubPlan.objects.filter(fixture=fixture).only("timeslot", "player_id"):
        planned_pairs.add((sp.timeslot, sp.player_id))

    # Rows for the Sub Availability matrix, with conflict/planned/busy flags per timeslot
    sub_matrix_rows = []
    for pid, codes in sub_map.items():
        p = players_map.get(pid)
        row = {
            "player": p,
            # available flags
            "a0830": ("0830" in codes),
            "a1000": ("1000" in codes),
            "a1130": ("1130" in codes),
            # already planned flags
            "p0830": (("0830", pid) in planned_pairs),
            "p1000": (("1000", pid) in planned_pairs),
            "p1130": (("1130", pid) in planned_pairs),
            # busy-at-fixture-timeslot flag (only for the fixture's own timeslot)
            "b0830": (fx_ts == "0830" and pid in lineup_players),
            "b1000": (fx_ts == "1000" and pid in lineup_players),
            "b1130": (fx_ts == "1130" and pid in lineup_players),
        }
        sub_matrix_rows.append(row)

    # Sort rows by name for stable display
    sub_matrix_rows.sort(key=lambda r: ((r["player"].last_name or "").lower(), (r["player"].first_name or "").lower()))

    # Base URL used by inline "Plan sub" actions (JS will append params)
    # Ensure reverse is imported at the top if not already
    subplan_create_url = reverse("subplan_create", args=[fixture.id])

    return render(request, "league/captain/availability_matrix.html", {
        "fixture": fixture,
        "rows": rows,
        # Sub availability section
        "sub_matrix_rows": sub_matrix_rows,
        "sub_counts": sub_counts,
        "fx_ts": fx_ts,
        "subplan_create_url": subplan_create_url,
    })

@login_required
@user_passes_test(is_captain)
@rl_deco(key='ip', rate='30/m', method='POST', block=True)
def admin_lineup_builder(request, fixture_id):
    fixture = get_object_or_404(Fixture, pk=fixture_id)

    # ⛔ Server-side guard for BYE weeks
    if getattr(fixture, "is_bye", False):
        messages.info(request, "Bye week — no lineup needed.")
        return redirect("fixture_detail", pk=fixture_id)

    lineup, _ = Lineup.objects.get_or_create(fixture=fixture, defaults={"created_by": request.user})

    # Ensure exactly these six slots exist for every lineup
    for code in SLOT_CODES:
        LineupSlot.objects.get_or_create(lineup=lineup, slot=code)

    if request.method == "POST":
        form = LineupForm(request.POST, instance=lineup)
        formset = LineupSlotFormSet(request.POST, instance=lineup)

        form_valid = form.is_valid()
        formset_valid = formset.is_valid()
        conflicts_found = False

        if form_valid and formset_valid:
            # --- Publish guard: block publishing if any lineup player is also booked to sub at this fixture's timeslot ---
            target_published = bool(form.cleaned_data.get("published"))
            if target_published:
                from .models import SubPlan
                fx_timeslot = fixture.timeslot_code() if hasattr(fixture, "timeslot_code") else None

                # Collect player ids from the submitted formset (reflects current edits)
                assigned_ids = set()
                for sf in formset.forms:
                    cd = getattr(sf, "cleaned_data", {}) or {}
                    p1 = cd.get("player1")
                    p2 = cd.get("player2")
                    if p1:
                        assigned_ids.add(getattr(p1, "id", getattr(p1, "pk", None)))
                    if p2:
                        assigned_ids.add(getattr(p2, "id", getattr(p2, "pk", None)))
                assigned_ids.discard(None)

                conflicts = []
                if fx_timeslot and assigned_ids:
                    conflicts = list(
                        SubPlan.objects
                        .filter(fixture=fixture, timeslot=fx_timeslot, player_id__in=assigned_ids)
                        .select_related("player")
                        .order_by("player__last_name", "player__first_name")
                    )

                if conflicts:
                    names = ", ".join(f"{sp.player.first_name} {sp.player.last_name}" for sp in conflicts)
                    form.add_error(None, f"Cannot publish lineup: conflict with sub plans at this timeslot for: {names}.")
                    conflicts_found = True
                else:
                    # Save lineup meta and slots
                    lineup_obj = form.save(commit=False)
                    lineup_obj.published = True
                    lineup_obj.save()
                    formset.save()

                    # Notify players in the lineup (single consolidated call)
                    # Notify players in the lineup (single consolidated call)
                    # Collect all players in the lineup and notify in one go
                    from league.notifications import lineup_published

                    slots_now = lineup_obj.slots.select_related("player1", "player2").all()
                    players = []
                    for ls in slots_now:
                        if ls.player1:
                            players.append(ls.player1)
                        if ls.player2:
                            players.append(ls.player2)

                    notified, attempts = lineup_published(players, fixture, fixture.season)
                    logger.info("[admin_lineup_builder] lineup_published: notified=%s attempts=%s fixture=%s",
                                notified, attempts, getattr(fixture, "id", None))

                    messages.success(request, "Lineup saved.")
                    return redirect("admin_lineup_builder", fixture_id=fixture.id)
            else:
                # Not publishing: just save lineup meta and slots
                lineup_obj = form.save(commit=False)
                lineup_obj.save()
                formset.save()
                messages.success(request, "Lineup saved.")
                return redirect("admin_lineup_builder", fixture_id=fixture.id)

        # If we reach here, either validation failed or conflicts were found; re-render with a single banner
        if not (form_valid and formset_valid) or conflicts_found:
            messages.error(request, "There were errors:")
            # Do not enumerate per-field/per-form errors in messages; the form template will render them inline.

        # fall through to render the page with bound forms + errors
    else:
        form = LineupForm(instance=lineup)
        formset = LineupSlotFormSet(instance=lineup)

    # Build left/right columns explicitly: (S1,D1), (S2,D2), (S3,D3)

    forms_by_slot = {f.instance.slot: f for f in formset.forms}
    ordered_singles = [forms_by_slot.get(code) for code in ["S1", "S2", "S3"]]
    ordered_doubles = [forms_by_slot.get(code) for code in ["D1", "D2", "D3"]]
    form_pairs = list(zip(ordered_singles, ordered_doubles))

    return render(request, "league/captain/lineup_builder.html", {
        "fixture": fixture,
        "form": form,
        "formset": formset,
        "form_pairs": form_pairs,
    })

@login_required
@user_passes_test(is_captain)
def captain_dashboard(request):
    # All seasons for captain; default to active, else most recent
    seasons = Season.objects.all().order_by("-year" if hasattr(Season, "year") else "-id")

    sel_id = request.GET.get("season")
    selected = seasons.filter(pk=sel_id).first() if sel_id else None
    if not selected and hasattr(Season, "is_active"):
        selected = seasons.filter(is_active=True).first()
    if not selected:
        selected = seasons.first()  # most recent by ordering above

    if selected:
        fixtures = Fixture.objects.filter(season=selected).order_by("date")
    else:
        fixtures = Fixture.objects.none()

    now = timezone.now()
    upcoming = fixtures.filter(date__gte=now)
    past = fixtures.filter(date__lt=now).order_by("-date")

    return render(request, "league/captain/dashboard.html", {
        "seasons": seasons,
        "selected": selected,
        "upcoming": upcoming,
        "past": past,
    })

@login_required
def profile_edit(request):
    # Ensure the user has a Player profile; create/link one if missing
    player = getattr(request.user, "player_profile", None)
    if player is None:
        player = Player.objects.create(
            user=request.user,
            first_name=request.user.first_name or request.user.username,
            last_name=request.user.last_name or "",
            email=request.user.email or "",
        )

    # Get or create the per-user notification preferences
    from .models import NotificationPreference
    prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)

    # 🔒 Ensure we use a fresh instance and bind it to the user for template reverse access
    try:
        prefs.refresh_from_db()
    except Exception:
        pass
    try:
        # Make sure templates using request.user.notificationpreference see THIS instance
        setattr(request.user, "notificationpreference", prefs)
    except Exception:
        pass

    # Instantiate all forms (unbound by default)
    form = PlayerForm(instance=player)
    prefs_form = NotificationPreferenceForm(instance=prefs)
    username_form = UsernameForm(instance=request.user)
    pwd_form = StyledPasswordChangeForm(request.user)

    if request.method == "POST":
        action = (request.POST.get("save") or "").strip()

        if action == "profile":
            form = PlayerForm(request.POST, instance=player)
            prefs_form = NotificationPreferenceForm(instance=prefs)  # keep others unbound
            username_form = UsernameForm(instance=request.user)
            pwd_form = StyledPasswordChangeForm(request.user)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile saved.")
                return redirect("profile_edit")
            else:
                messages.error(request, "Please fix the errors below.")

        elif action == "notifications":
            form = PlayerForm(instance=player)
            prefs_form = NotificationPreferenceForm(request.POST, instance=prefs)
            username_form = UsernameForm(instance=request.user)
            pwd_form = StyledPasswordChangeForm(request.user)
            if prefs_form.is_valid():
                prefs_form.save()
                messages.success(request, "Notification settings saved.")
                return redirect("profile_edit")
            else:
                messages.error(request, "Please fix the errors below.")

        elif action == "security_username":
            form = PlayerForm(instance=player)
            prefs_form = NotificationPreferenceForm(instance=prefs)
            username_form = UsernameForm(request.POST, instance=request.user)
            pwd_form = StyledPasswordChangeForm(request.user)
            if username_form.is_valid():
                username_form.save()
                messages.success(request, "Username updated.")
                return redirect("profile_edit")
            else:
                messages.error(request, "Please fix the errors below.")

        elif action == "security_password":
            form = PlayerForm(instance=player)
            prefs_form = NotificationPreferenceForm(instance=prefs)
            username_form = UsernameForm(instance=request.user)
            pwd_form = StyledPasswordChangeForm(request.user, request.POST)
            if pwd_form.is_valid():
                user = pwd_form.save()
                # Keep the user logged in after password change
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated.")
                return redirect("profile_edit")
            else:
                messages.error(request, "Please fix the errors below.")

        else:
            # Fallback: try to save both profile + prefs together (legacy behavior)
            form = PlayerForm(request.POST, instance=player)
            prefs_form = NotificationPreferenceForm(request.POST, instance=prefs)
            username_form = UsernameForm(instance=request.user)
            pwd_form = StyledPasswordChangeForm(request.user)
            if form.is_valid() and prefs_form.is_valid():
                form.save()
                prefs_form.save()
                messages.success(request, "Profile and Notification Settings saved.")
                return redirect("profile_edit")
            else:
                messages.error(request, "Please fix the errors below.")

    return render(request, "league/player_profile_form.html", {
        "form": form,
        "prefs_form": prefs_form,
        "username_form": username_form,
        "pwd_form": pwd_form,
        "prefs": prefs,
    })
@login_required
@rl_deco(key='ip', rate='60/m', method='POST', block=False)
def availability_set_ajax(request):
    if getattr(request, "limited", False):
        return JsonResponse({"detail": "Too many requests"}, status=429)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    fixture_id = data.get("fixture_id")
    status = data.get("status")

    if status not in {"A", "N"}:
        return HttpResponseBadRequest("Invalid status")

    fixture = get_object_or_404(Fixture, pk=fixture_id)

    # Block for bye weeks
    if getattr(fixture, "is_bye", False):
        return HttpResponseBadRequest("Bye week — availability not applicable")

    # Block changes once results are posted
    if SlotScore.objects.filter(fixture=fixture).exists():
        return HttpResponseBadRequest("Results posted — availability is closed")

    player = getattr(request.user, "player_profile", None)
    if not player:
        return HttpResponseBadRequest("No player profile linked")

    if not player_on_roster(player, fixture.season):
        return HttpResponseBadRequest("Not on this season's roster")

    availability = Availability.objects.filter(player=player, fixture=fixture).first()
    if availability is None:
        availability = Availability(player=player, fixture=fixture)

    availability.status = status
    availability.save()

    return JsonResponse({"ok": True, "fixture_id": fixture.id, "status": availability.status})

@login_required
@rl_deco(key='ip', rate='60/m', method='POST', block=False)
def sub_availability_set_ajax(request):
    if getattr(request, "limited", False):
        return JsonResponse({"detail": "Too many requests"}, status=429)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    fixture_id = data.get("fixture_id")
    timeslot = (data.get("timeslot") or "").strip()   # "0830" | "1000" | "1130"
    on = bool(data.get("on"))

    # Validate input
    if timeslot not in {"0830", "1000", "1130"}:
        return HttpResponseBadRequest("Invalid timeslot")

    fixture = get_object_or_404(Fixture, pk=fixture_id)

    player = getattr(request.user, "player_profile", None)
    if not player:
        return HttpResponseBadRequest("No player profile linked")

    if not player_on_roster(player, fixture.season):
        return HttpResponseBadRequest("Not on this season's roster")

    # Optional guard: if lineup is published and player is in it at the SAME timeslot, block “on”
    lineup = getattr(fixture, "lineup", None)
    if on and lineup and getattr(lineup, "published", False):
        in_lineup = LineupSlot.objects.filter(lineup=lineup)\
                                      .filter(Q(player1=player) | Q(player2=player))\
                                      .exists()
        fx_ts = fixture.timeslot_code() if hasattr(fixture, "timeslot_code") else None
        if in_lineup and fx_ts and fx_ts == timeslot:
            return HttpResponseBadRequest("You're in the published lineup at this time")

    # Toggle
    if on:
        SubAvailability.objects.get_or_create(player=player, fixture=fixture, timeslot=timeslot)
    else:
        SubAvailability.objects.filter(player=player, fixture=fixture, timeslot=timeslot).delete()

    return JsonResponse({"ok": True, "fixture_id": fixture.id, "timeslot": timeslot, "on": on})
# --- SubPlan CRUD views ---

@login_required
@user_passes_test(is_captain)
@rl_deco(key='ip', rate='60/m', method='POST', block=True)
def subplan_create(request, fixture_id):
    fixture = get_object_or_404(Fixture, pk=fixture_id)

    # Lightweight AJAX endpoint used by the Availability Matrix "Plan sub" modal
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    accepts_json = "application/json" in (request.headers.get("accept", "").lower())
    if request.method == "POST" and (is_ajax or accepts_json or request.POST.get("ajax") == "1"):
        from django.http import JsonResponse
        try:
            player_id = request.POST.get("player_id") or request.POST.get("player")
            timeslot = (request.POST.get("timeslot") or "").strip()   # "0830" | "1000" | "1130"
            kind = (request.POST.get("kind") or "").strip().upper()   # may be absent on model
            notes = (request.POST.get("notes") or "").strip()
            slot_code = (request.POST.get("slot_code") or "").strip().upper()  # e.g., S1,S2,S3,D1,D2,D3
            target_type = (request.POST.get("target_type") or "").strip()
            target_team_name = (request.POST.get("target_team_name") or "").strip()

            if not player_id or not timeslot:
                return JsonResponse({"error": "Missing player or timeslot."}, status=400)

            # Introspect model fields to decide what we can/should set
            try:
                field_names = {f.name for f in SubPlan._meta.get_fields()}
            except Exception:
                field_names = set()

            # Validate kind only if present on model
            if "kind" in field_names:
                if kind not in {"SINGLES", "DOUBLES"}:
                    return JsonResponse({"error": "Missing or invalid kind."}, status=400)
            else:
                kind = None

            # Validate slot_code only if present on model
            if "slot_code" in field_names:
                valid_slots = {"S1", "S2", "S3", "D1", "D2", "D3"}
                if slot_code and slot_code not in valid_slots:
                    return JsonResponse({"error": "Invalid slot."}, status=400)

            try:
                player = Player.objects.get(pk=player_id)
            except Player.DoesNotExist:
                return JsonResponse({"error": "Player not found."}, status=404)

            if timeslot not in {"0830", "1000", "1130"}:
                return JsonResponse({"error": "Invalid timeslot."}, status=400)

            # Prevent duplicate plan for same player+timeslot on this fixture
            if SubPlan.objects.filter(fixture=fixture, player=player, timeslot=timeslot).exists():
                return JsonResponse({"error": "A sub plan already exists for this player at this timeslot."},
                                    status=400)

            # Resolve a safe default for target_type
            default_target = getattr(getattr(SubPlan, 'Target', None), 'OTHER_TEAM', None) or 'OTHER_TEAM'
            if "target_type" in field_names:
                # Normalize to enum value if needed
                if target_type:
                    t_norm = target_type.upper()
                    if t_norm in {"OTHER_TEAM", "AGAINST_US"}:
                        target_type = t_norm
                else:
                    target_type = default_target

            # AGAINST_US auto-fill team name if empty
            if "target_type" in field_names and str(target_type).upper() in {
                "AGAINST_US", str(getattr(SubPlan.Target, "AGAINST_US", "AGAINST_US"))
            }:
                if not target_team_name:
                    target_team_name = fixture.opponent or "Opponent"

            sp_kwargs = {}
            # Required/common fields
            if 'fixture' in field_names:
                sp_kwargs['fixture'] = fixture
            else:  # fixture FK should exist; if not, bail early
                return JsonResponse({"error": "Model missing 'fixture' field."}, status=400)
            if 'player' in field_names: sp_kwargs['player'] = player
            if 'timeslot' in field_names: sp_kwargs['timeslot'] = timeslot
            if 'notes' in field_names: sp_kwargs['notes'] = notes
            if 'published' in field_names: sp_kwargs['published'] = False
            if 'target_type' in field_names: sp_kwargs['target_type'] = target_type or default_target
            if 'target_team_name' in field_names: sp_kwargs['target_team_name'] = target_team_name
            if 'slot_code' in field_names and slot_code:
                sp_kwargs['slot_code'] = slot_code
            if 'kind' in field_names and kind:
                sp_kwargs['kind'] = kind

            # created_by optional
            try:
                has_created_by = any(getattr(f, 'name', '') == 'created_by' for f in SubPlan._meta.get_fields())
            except Exception:
                has_created_by = False
            if has_created_by:
                sp_kwargs['created_by'] = request.user

            plan = SubPlan(**sp_kwargs)
            plan.save()
            # Notify the player if this plan is published and the player has a user
            try:
                if getattr(plan, "published", False) and plan.player and getattr(plan.player, "user_id", None):
                    fx = fixture
                    try:
                        detail_url = request.build_absolute_uri(reverse("fixture_detail", args=[fx.id]))
                    except Exception:
                        detail_url = ""
                    # Derive display values
                    try:
                        timeslot_disp = getattr(plan, "get_timeslot_display", lambda: plan.timeslot)()
                    except Exception:
                        timeslot_disp = getattr(plan, "timeslot", "")
                    try:
                        slot_disp = getattr(plan, "get_slot_code_display", lambda: getattr(plan, "slot_code", "TBD"))()
                    except Exception:
                        slot_disp = getattr(plan, "slot_code", "TBD")
                    is_doubles = str(getattr(plan, "slot_code", "")).upper().startswith("D") or str(getattr(plan, "kind", "")).upper().startswith("DOUB")
                    # Compose date_txt safely
                    from django.utils import timezone as _tz
                    try:
                        date_txt = _tz.localtime(fx.date).strftime("%b %-d") if getattr(fx, "date", None) else ""
                    except Exception:
                        date_txt = ""
                    u = plan.player.user
                    per_user_ctx = {
                        u.id: {
                            "slot_label": slot_disp or "TBD",
                            "is_doubles": is_doubles,
                            "player_first_name": getattr(u, "first_name", None),
                            "slot_name": slot_disp or "TBD",
                        }
                    }
                    base_ctx = {
                        "fixture": fx,
                        "match_dt": getattr(fx, "date", None),
                        "opponent": getattr(fx, "opponent", ""),
                        "fixture_url": detail_url,
                        "_per_user_ctx": per_user_ctx,
                        "_user_player_map": {u.id: plan.player},
                        "timeslot": getattr(plan, "timeslot", "") or None,
                        "slot_code": getattr(plan, "slot_code", "") or None,
                        "target_team_name": getattr(plan, "target_team_name", "") or None,
                        "sub_team_name": getattr(plan, "target_team_name", "") or None, # alias for templates
                        "notes": getattr(plan,"notes","") or None,
                    }
                    title = f"Sub match added — {date_txt} {timeslot_disp} {slot_disp}".strip()
                    body  = f"Target: {getattr(plan, 'get_target_type_display', lambda: str(getattr(plan, 'target_type', '')) )()} {base_ctx.get('sub_team_name') or ''}".strip()
                    logger.info(
                        "SUBPLAN_NOTIFY: ajax path → published=%s player_user=%s",
                        getattr(plan, "published", None),
                        getattr(getattr(plan, "player", None), "user_id", None),
                    )

                    # Use the unified inline-sending helper (creates receipts + attempts + sends)
                    from league.notifications import send_event

                    notif, attempts = send_event("SUBPLAN_CREATED", players=[plan.player], season=fx.season, fixture=fx,
                                                 title=title, body=body, url=detail_url, context=base_ctx,
                                                 per_user_ctx=per_user_ctx, user_player_map={u.id: plan.player})
                    logger.info(
                        "SUBPLAN_NOTIFY: ajax sent SUBPLAN_CREATED notif=%s attempts=%s",
                        getattr(notif, "id", None), attempts,
                    )
            except Exception:
                # Never break AJAX on notification issues
                pass
            return JsonResponse({"ok": True, "id": plan.id})
        except Exception as e:
            # Catch-all to avoid raw 500s; surface the message to the modal
            return JsonResponse({"error": str(e)}, status=400)

    # Fallback: original HTML form flow for full sub plan creation/edit
    form = SubPlanForm(request.POST or None, fixture=fixture)
    if request.method == "POST":
        if form.is_valid():
            plan = form.save(commit=False)
            plan.fixture = fixture
            if plan.target_type == SubPlan.Target.AGAINST_US and not plan.target_team_name:
                plan.target_team_name = fixture.opponent or "Opponent"
            try:
                plan.full_clean()
                plan.save()
                try:
                    if plan.published and plan.player and getattr(plan.player, "user_id", None):
                        detail_url = request.build_absolute_uri(reverse("fixture_detail", args=[fixture.id]))
                        u = plan.player.user
                        try:
                            timeslot_disp = getattr(plan, "get_timeslot_display", lambda: plan.timeslot)()
                        except Exception:
                            timeslot_disp = getattr(plan, "timeslot", "")
                        try:
                            slot_disp = getattr(plan, "get_slot_code_display", lambda: getattr(plan, "slot_code", "TBD"))()
                        except Exception:
                            slot_disp = getattr(plan, "slot_code", "TBD")
                        is_doubles = str(getattr(plan, "slot_code", "")).upper().startswith("D") or str(getattr(plan, "kind", "")).upper().startswith("DOUB")
                        # Compose date_txt safely
                        from django.utils import timezone as _tz
                        try:
                            date_txt = _tz.localtime(fixture.date).strftime("%b %-d") if getattr(fixture, "date", None) else ""
                        except Exception:
                            date_txt = ""
                        per_user_ctx = {
                            u.id: {
                                "slot_label": slot_disp or "TBD",
                                "is_doubles": is_doubles,
                                "player_first_name": getattr(u, "first_name", None),
                                "slot_name": slot_disp or "TBD",
                            }
                        }
                        base_ctx = {
                            "fixture": fixture,
                            "match_dt": getattr(fixture, "date", None),
                            "opponent": getattr(fixture, "opponent", ""),
                            "fixture_url": detail_url,
                            "_per_user_ctx": per_user_ctx,
                            "_user_player_map": {u.id: plan.player},
                            "timeslot": getattr(plan, "timeslot", "") or None,
                            "slot_code": getattr(plan, "slot_code", "") or None,
                            "target_team_name": getattr(plan, "target_team_name", "") or None,
                            "sub_team_name": getattr(plan, "target_team_name", "") or None,  # alias for templates
                        }
                        title = f"Sub match added — {date_txt} {timeslot_disp} {slot_disp}".strip()
                        body  = f"Target: {getattr(plan, 'get_target_type_display', lambda: str(getattr(plan, 'target_type', '')) )()} {base_ctx.get('sub_team_name') or ''}".strip()
                        from league.notifications import send_event
                        notif, attempts = send_event("SUBPLAN_CREATED", players=[plan.player], season=fixture.season,
                                                     fixture=fixture, title=title, body=body, url=detail_url,
                                                     context=base_ctx, per_user_ctx=per_user_ctx,
                                                     user_player_map={u.id: plan.player})
                        logger.info(
                            "SUBPLAN_CREATE(HTML): sent SUBPLAN_CREATED notif=%s attempts=%s",
                            getattr(notif, "id", None), attempts,
                        )
                except Exception:
                    pass
                messages.success(request, "Sub match added.")
                return redirect("fixture_detail", pk=fixture.id)
            except Exception as e:
                messages.error(request, f"Could not save sub match: {e}")
    return render(request, "league/captain/subplan_form.html", {"form": form, "fixture": fixture})


@login_required
@user_passes_test(is_captain)
def subplan_edit(request, plan_id):
    plan = get_object_or_404(SubPlan, pk=plan_id)
    fixture = plan.fixture
    form = SubPlanForm(request.POST or None, instance=plan, fixture=fixture)

    if request.method == "POST":
        if form.is_valid():
            plan = form.save(commit=False)
            # Auto-fill target team for AGAINST_US if blank
            if plan.target_type == SubPlan.Target.AGAINST_US and not plan.target_team_name:
                plan.target_team_name = fixture.opponent or "Opponent"
            try:
                plan.full_clean()
                plan.save()
                # Notify player if published (updated event)
                try:
                    if plan.published and plan.player and getattr(plan.player, "user_id", None):
                        date_txt = ""
                        try:
                            date_txt = timezone.localtime(fixture.date).strftime("%b %-d") if getattr(fixture, "date", None) else ""
                        except Exception:
                            date_txt = ""
                        timeslot_disp = getattr(plan, "get_timeslot_display", lambda: plan.timeslot)()
                        slot_disp = getattr(plan, "get_slot_code_display", lambda: getattr(plan, "slot_code", ""))()
                        target_txt = getattr(plan, "get_target_type_display", lambda: str(getattr(plan, "target_type", "")))()
                        opp = plan.target_team_name or (fixture.opponent or "Opponent")
                        title = f"Sub match updated — {date_txt} {timeslot_disp} {slot_disp}".strip()
                        body = f"Target: {target_txt} {opp}".strip()
                        from league.notifications import send_event
                        try:
                            detail_url = request.build_absolute_uri(reverse("fixture_detail", args=[fixture.id]))
                        except Exception:
                            detail_url = reverse("fixture_detail", args=[fixture.id])

                        u = plan.player.user if getattr(plan.player, "user_id", None) else None
                        per_user_ctx = {}
                        user_player_map = {}
                        if u and getattr(u, "id", None):
                            is_doubles = str(getattr(plan, "slot_code", "")).upper().startswith("D") or str(getattr(plan, "kind", "")).upper().startswith("DOUB")
                            per_user_ctx[u.id] = {
                                "slot_label": slot_disp or "TBD",
                                "slot_name":  slot_disp or "TBD",
                                "is_doubles": is_doubles,
                                "player_first_name": getattr(u, "first_name", None),
                                "timeslot": getattr(plan, "timeslot", "") or None,
                                "slot_code": getattr(plan, "slot_code", "") or None,
                                "target_team_name": getattr(plan, "target_team_name", "") or None,
                                "sub_team_name": getattr(plan, "target_team_name", "") or None,
                                "notes": getattr(plan, "notes","") or None,
                            }
                            user_player_map[u.id] = plan.player

                        base_ctx = {
                            "fixture": fixture,
                            "match_dt": getattr(fixture, "date", None),
                            "opponent": getattr(fixture, "opponent", ""),
                            "fixture_url": detail_url,
                            "timeslot": getattr(plan, "timeslot", "") or None,
                            "slot_code": getattr(plan, "slot_code", "") or None,
                            "target_team_name": getattr(plan, "target_team_name", "") or None,
                            "sub_team_name": getattr(plan, "target_team_name", "") or None,  # alias for templates
                        }
                        if per_user_ctx:
                            base_ctx["_per_user_ctx"] = per_user_ctx
                        if user_player_map:
                            base_ctx["_user_player_map"] = user_player_map

                        notif, attempts = send_event("SUBPLAN_UPDATED_FOR_PLAYER", players=[plan.player],
                                                     season=fixture.season, fixture=fixture, title=title, body=body,
                                                     url=detail_url, context=base_ctx,
                                                     per_user_ctx=per_user_ctx or None,
                                                     user_player_map=user_player_map or None)
                        logger.info(
                            "SUBPLAN_EDIT: sent SUBPLAN_UPDATED_FOR_PLAYER notif=%s attempts=%s",
                            getattr(notif, "id", None), attempts,
                        )
                except Exception:
                    pass
                messages.success(request, "Sub match updated.")
                return redirect("fixture_detail", pk=fixture.id)
            except Exception as e:
                messages.error(request, f"Could not save sub match: {e}")
    return render(request, "league/captain/subplan_form.html", {"form": form, "fixture": fixture, "plan": plan})


@login_required
@user_passes_test(is_captain)
def subplan_toggle(request, plan_id):
    plan = get_object_or_404(SubPlan, pk=plan_id)
    was_published = bool(plan.published)
    plan.published = not plan.published
    try:
        plan.full_clean()
        plan.save(update_fields=["published", "updated_at"])

        # --- Notifications (best-effort; never block) ---
        try:
            fixture = plan.fixture
            date_txt = timezone.localtime(fixture.date).strftime("%b %-d") if getattr(fixture, "date", None) else ""
            timeslot_disp = getattr(plan, "get_timeslot_display", lambda: plan.timeslot)()
            slot_disp = getattr(plan, "get_slot_code_display", lambda: getattr(plan, "slot_code", ""))()
            target_txt = getattr(plan, "get_target_type_display", lambda: str(getattr(plan, "target_type", "")))()
            opp = plan.target_team_name or (fixture.opponent or "Opponent")

            logger.info(
                "SUBPLAN_TOGGLE: plan_id=%s was_published=%s now_published=%s player_user=%s",
                getattr(plan, "id", None), was_published, getattr(plan, "published", None), getattr(getattr(plan, "player", None), "user_id", None),
            )
            logger.info("SUBPLAN_TOGGLE: entering context build for plan_id=%s", getattr(plan, "id", None))

            logger.info("SUBPLAN_TOGGLE: entering context build for plan_id=%s", getattr(plan, "id", None))

            # Common bits used by both publish/unpublish
            try:
                detail_url = request.build_absolute_uri(reverse("fixture_detail", args=[fixture.id]))
            except Exception:
                detail_url = ""
            title = f"Sub match added — {date_txt} {timeslot_disp} {slot_disp}".strip()
            body = f"Target: {target_txt} {opp}".strip()

            if plan.published and plan.player and getattr(plan.player, "user_id", None):
                # Build per-user context for templates
                u = plan.player.user
                per_user_ctx = {
                    u.id: {
                        "slot_label": slot_disp or "TBD",
                        "slot_name": slot_disp or "TBD",
                        "is_doubles": str(getattr(plan, "slot_code", "")).upper().startswith("D")
                                      or str(getattr(plan, "kind", "")).upper().startswith("DOUB"),
                        "player_first_name": getattr(u, "first_name", None),
                        "timeslot": getattr(plan, "timeslot", "") or None,
                        "slot_code": getattr(plan, "slot_code", "") or None,
                        "target_team_name": getattr(plan, "target_team_name", "") or None,
                        "sub_team_name": getattr(plan, "target_team_name", "") or None,  # alias for templates
                    }
                }
                user_player_map = {u.id: plan.player}

                # Send inline (creates receipts + attempts + sends)
                notif, attempts = send_event("SUBPLAN_CREATED", players=[plan.player], season=fixture.season,
                                             fixture=fixture, title=title, body=body, url=detail_url, context={
                        "opponent": getattr(fixture, "opponent", ""),
                        "match_dt": getattr(fixture, "date", None),
                        "fixture_url": detail_url,
                        "timeslot": getattr(plan, "timeslot", "") or None,
                        "slot_code": getattr(plan, "slot_code", "") or None,
                        "target_team_name": getattr(plan, "target_team_name", "") or None,
                        "sub_team_name": getattr(plan, "target_team_name", "") or None,
                        "notes": getattr(plan, "notes", "") or None,  # alias for templates
                    }, per_user_ctx=per_user_ctx, user_player_map=user_player_map)
                logger.info(
                    "SUBPLAN_TOGGLE: sent SUBPLAN_CREATED notif=%s attempts=%s",
                    getattr(notif, "id", None), attempts,
                )

            elif was_published and not plan.published and plan.player and getattr(plan.player, "user_id", None):
                # Unpublish: soft signal as an update
                unpub_title = f"Sub match unpublished — {date_txt} {timeslot_disp} {slot_disp}".strip()
                unpub_body = f"Target: {target_txt} {opp}".strip()
                detail_url_unpub = detail_url

                notif, attempts = send_event(
                    "SUBPLAN_CANCELLED_FOR_PLAYER",
                    players=[plan.player],
                    season=fixture.season,
                    fixture=fixture,
                    title=unpub_title,
                    body=unpub_body,
                    url=detail_url_unpub,
                    subject="Royals: Your sub match was cancelled",
                    context={
                        "opponent": getattr(fixture, "opponent", ""),
                        "match_dt": getattr(fixture, "date", None),
                        "fixture_url": detail_url_unpub,
                        # subplan-specific keys needed by templates
                        "timeslot": getattr(plan, "timeslot", "") or None,
                        "slot_code": getattr(plan, "slot_code", "") or None,
                        # provide both labels so SMS/HTML can use either
                        "slot_label": (getattr(plan, "get_slot_code_display", lambda: getattr(plan, "slot_code", "TBD"))() or "TBD"),
                        "slot_name":  (getattr(plan, "get_slot_code_display", lambda: getattr(plan, "slot_code", "TBD"))() or "TBD"),
                        "target_team_name": getattr(plan, "target_team_name", "") or None,
                        "sub_team_name": getattr(plan, "target_team_name", "") or None,
                        "notes": getattr(plan, "notes", "") or None,
                    },
                )
                logger.info(
                    "SUBPLAN_TOGGLE: sent SUBPLAN_UPDATED_FOR_PLAYER notif=%s attempts=%s",
                    getattr(notif, "id", None), attempts,
                )
        except Exception:
            # Never block toggling on notification errors
            pass

        messages.success(request, ("Published" if plan.published else "Unpublished") + " sub match.")
    except Exception as e:
        # Revert flip on error so UI reflects actual state
        plan.published = was_published
        messages.error(request, f"Could not toggle publish: {e}")
    return redirect("fixture_detail", pk=plan.fixture_id)


@login_required
@user_passes_test(is_captain)
@rl_deco(key='ip', rate='20/m', method='POST', block=True)
def subplan_delete(request, plan_id):
    plan = get_object_or_404(SubPlan, id=plan_id)
    fixture = plan.fixture
    player = plan.player

    # --- Capture everything we need BEFORE delete ---
    was_published = bool(getattr(plan, "published", False))
    u = player.user if getattr(player, "user_id", None) else None
    timeslot_val = getattr(plan, "timeslot", None)
    slot_code_val = getattr(plan, "slot_code", None)
    try:
        slot_label = plan.get_slot_code_display()
    except Exception:
        slot_label = slot_code_val or "TBD"
    target_name = getattr(plan, "target_team_name", "") or None
    notes_val = getattr(plan, "notes", "") or None

    # Display helpers (don’t use plan after delete)
    timeslot_disp = f"{timeslot_val[:2]}:{timeslot_val[2:]}" if timeslot_val and len(timeslot_val) == 4 else None
    slot_disp = slot_label
    opp = target_name

    logger.info("SUBPLAN_DELETE: entered plan_id=%s was_published=%s user_id=%s",
                plan_id, was_published, getattr(u, "id", None))

    # Actually delete the plan
    plan.delete()
    logger.info("SUBPLAN_DELETE: deleted plan_id=%s", plan_id)

    # --- Notify cancellation if it had been published ---
    try:
        if was_published and player and getattr(player, "user_id", None):
            title = f"Sub match cancelled — {timeslot_disp or ''} {slot_disp}".strip()
            body_bits = []
            if opp: body_bits.append(f"Sub team: {opp}")
            if fixture and fixture.opponent: body_bits.append(f"Opponent: {fixture.opponent}")
            body = " | ".join(body_bits) or "Sub assignment cancelled."

            try:
                detail_url = request.build_absolute_uri(reverse("fixture_detail", args=[fixture.id]))
            except Exception:
                detail_url = reverse("fixture_detail", args=[fixture.id])

            # per-user ctx for templating
            per_user_ctx = {}
            user_player_map = {}
            if u and getattr(u, "id", None):
                is_doubles = str(slot_code_val or "").upper().startswith("D")
                per_user_ctx[u.id] = {
                    "slot_label": slot_disp,
                    "slot_name": slot_disp,
                    "is_doubles": is_doubles,
                    "player_first_name": getattr(u, "first_name", None),
                }
                user_player_map[u.id] = player

            base_ctx = {
                "fixture": fixture,
                "match_dt": getattr(fixture, "date", None),
                "opponent": getattr(fixture, "opponent", ""),
                "fixture_url": detail_url,
                # subplan specifics captured before delete
                "timeslot": timeslot_val or None,
                "slot_code": slot_code_val or None,
                "slot_label": slot_disp,
                "slot_name": slot_disp,
                "target_team_name": opp,
                "sub_team_name": opp,  # alias used by templates
                "notes": notes_val,
            }
            if per_user_ctx:
                base_ctx["_per_user_ctx"] = per_user_ctx
            if user_player_map:
                base_ctx["_user_player_map"] = user_player_map

            from league.notifications import send_event
            notif, attempts = send_event("SUBPLAN_CANCELLED_FOR_PLAYER", players=[player],
                                         season=fixture.season if fixture else None, fixture=fixture, title=title,
                                         body=body, url=detail_url, context=base_ctx, per_user_ctx=per_user_ctx or None,
                                         user_player_map=user_player_map or None)
            logger.info("SUBPLAN_DELETE: sent SUBPLAN_CANCELLED_FOR_PLAYER notif=%s attempts=%s",
                        getattr(notif, "id", None), attempts)
        else:
            logger.info("SUBPLAN_DELETE: skip notify — was_published=%s player_user=%s",
                        was_published, bool(getattr(player, "user_id", None)))
    except Exception:
        logger.exception("SUBPLAN_DELETE: failed to send cancellation notification plan_id=%s", plan_id)

    messages.success(request, "Sub match deleted.")
    return redirect("fixture_detail", pk=fixture.id)


# --- SubResult CRUD views ---

# imports already present at top:
# from .models import SubPlan, SubResult

@login_required
@user_passes_test(lambda u: u.is_staff)
@rl_deco(key='ip', rate='30/m', method='POST', block=True)
def subresult_create(request, fixture_id):
    fixture = get_object_or_404(Fixture, pk=fixture_id)

    # Accept ?plan=<id> (or a hidden field named 'plan')
    plan_id = request.GET.get("plan") or request.POST.get("plan")
    plan = None
    if plan_id:
        plan = get_object_or_404(SubPlan, pk=plan_id, fixture=fixture)

    if request.method == "POST":
        # If a plan exists, build a prefilled instance so form/clean sees locked fields
        if plan:
            instance = SubResult(
                fixture=fixture,
                plan=plan,
                player=plan.player,
                timeslot=plan.timeslot,
                slot_code=plan.slot_code,
                target_type=plan.target_type,
                target_team_name=plan.target_team_name or (fixture.opponent or "Opponent"),
            )
            form = SubResultForm(request.POST, instance=instance, fixture=fixture)
        else:
            # No plan: still bind fixture so form-level validation has context
            instance = SubResult(fixture=fixture)
            form = SubResultForm(request.POST, instance=instance, fixture=fixture)

        if form.is_valid():
            form.save()
            messages.success(request, "Sub result recorded.")
            return redirect("admin_enter_scores", fixture_id=fixture.id)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        initial = {}
        if plan:
            initial.update({
                "player": plan.player_id,
                "timeslot": plan.timeslot,
                "slot_code": plan.slot_code,
                "target_type": plan.target_type,
                "target_team_name": plan.target_team_name or (fixture.opponent or "Opponent"),
            })
        form = SubResultForm(initial=initial, fixture=fixture)

    return render(request, "league/captain/subresult_form.html", {
        "fixture": fixture,
        "form": form,
        "plan": plan,
    })



@login_required
@user_passes_test(is_captain)
def subresult_from_plan(request, plan_id):
    plan = get_object_or_404(SubPlan, pk=plan_id)
    fixture = plan.fixture

    if request.method == "POST":
        # Build a prefilled instance linked to the plan so validation sees the SAME plan
        instance = SubResult(
            fixture=fixture,
            plan=plan,
            player=plan.player,
            timeslot=plan.timeslot,
            slot_code=plan.slot_code,
            target_type=plan.target_type,
            target_team_name=plan.target_team_name or (fixture.opponent or "Opponent"),
        )
        try:
            form = SubResultForm(request.POST, instance=instance, fixture=fixture)
        except TypeError:
            form = SubResultForm(request.POST, instance=instance)

        if form.is_valid():
            obj = form.save(commit=False)
            # Ensure linkage is intact (defensive)
            obj.fixture = fixture
            obj.plan = plan
            obj.player = plan.player
            obj.timeslot = plan.timeslot
            obj.slot_code = plan.slot_code
            obj.target_type = plan.target_type
            if plan.target_type == SubPlan.Target.AGAINST_US and not obj.target_team_name:
                obj.target_team_name = fixture.opponent or "Opponent"
            # Model-level validation (will allow because obj.plan == plan)
            obj.full_clean()
            obj.save()
            messages.success(request, "Sub result recorded.")
            return redirect("admin_enter_scores", fixture_id=fixture.id)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        initial = {
            "player": plan.player_id,
            "timeslot": plan.timeslot,
            "slot_code": plan.slot_code,
            "target_type": plan.target_type,
            "target_team_name": plan.target_team_name or (fixture.opponent or "Opponent"),
        }
        try:
            form = SubResultForm(initial=initial, fixture=fixture)
        except TypeError:
            form = SubResultForm(initial=initial)

    return render(request, "league/captain/subresult_form.html", {
        "fixture": fixture,
        "form": form,
        "plan": plan,
    })


@login_required
@user_passes_test(lambda u: u.is_staff)
@rl_deco(key='ip', rate='30/m', method='POST', block=True)
def subresult_edit(request, fixture_id=None, subresult_id=None, sr_id=None):
    # Support routes that pass either (fixture_id, subresult_id) or just (sr_id)
    sid = subresult_id or sr_id
    if fixture_id is not None:
        fixture = get_object_or_404(Fixture, pk=fixture_id)
        sr = get_object_or_404(SubResult, pk=sid, fixture=fixture)
    else:
        sr = get_object_or_404(SubResult, pk=sid)
        fixture = sr.fixture

    if request.method == "POST":
        form = SubResultForm(request.POST, instance=sr, fixture=fixture)
        form.instance.fixture = fixture
        if sr.plan_id:
            form.instance.player_id = sr.plan.player_id
            form.instance.timeslot = sr.plan.timeslot
            form.instance.slot_code = sr.plan.slot_code
            form.instance.target_type = sr.plan.target_type
            if sr.plan.target_type == SubPlan.Target.OTHER_TEAM:
                form.instance.target_team_name = sr.plan.target_team_name

        if form.is_valid():
            form.save()
            messages.success(request, "Sub result updated.")
            return redirect("admin_enter_scores", fixture_id=fixture.id)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = SubResultForm(instance=sr, fixture=fixture)

    return render(request, "league/captain/subresult_form.html", {
        "fixture": fixture,
        "form": form,
        "plan": sr.plan,
        "subresult": sr,
    })


@login_required
@user_passes_test(is_captain)
def subresult_delete(request, sr_id):
    sr = get_object_or_404(SubResult, pk=sr_id)
    fixture_id = sr.fixture_id
    sr.delete()
    messages.success(request, "Sub result deleted.")
    return redirect("admin_enter_scores", fixture_id=fixture_id)

@login_required
@user_passes_test(is_staff_user)
def admin_dashboard(request):
    # Seasons (newest first by year if present)
    seasons = Season.objects.all().order_by("-year" if hasattr(Season, "year") else "-id")

    # Active season (or fallback to newest)
    active = seasons.filter(is_active=True).first() or seasons.first()

    # Allow switching active season from the dashboard
    action = request.POST.get("action") if request.method == "POST" else None
    if request.method == "POST" and action == "set_active" and request.POST.get("season_id"):
        try:
            target = Season.objects.get(pk=request.POST["season_id"])
            Season.objects.filter(is_active=True).update(is_active=False)
            target.is_active = True
            target.save(update_fields=["is_active"])
            messages.success(request, f"{target} is now the active season.")
            return redirect("admin_dashboard")
        except Season.DoesNotExist:
            messages.error(request, "Selected season not found.")
        except Exception as e:
            messages.error(request, f"Could not set active season: {e}")
        # fall through to render with messages
    # --- Danger zone: Reset Season ---
    if request.method == "POST" and action == "reset_season" and request.POST.get("season_id"):
        season_id = request.POST.get("season_id")
        try:
            season = Season.objects.get(pk=season_id)
        except Season.DoesNotExist:
            messages.error(request, "Selected season not found.")
            return redirect("admin_dashboard")

        try:
            with transaction.atomic():
                # Import optional models inline so missing ones don't break reset
                try:
                    from .models import SubPlan as _SubPlan
                except Exception:
                    _SubPlan = None
                try:
                    from .models import PlayerMatchPoints as _PMP
                except Exception:
                    _PMP = None
                try:
                    from .models import Notification as _Notification
                except Exception:
                    _Notification = None

                fixtures_qs = Fixture.objects.filter(season=season)

                # --- Delete dependent season data first (FK-friendly order) ---
                # Sub results
                try:
                    SubResult.objects.filter(fixture__in=fixtures_qs).delete()
                except Exception:
                    pass
                # Slot/match results
                try:
                    SlotScore.objects.filter(fixture__in=fixtures_qs).delete()
                except Exception:
                    pass
                # Player match points (lineup-earned points)
                if _PMP is not None:
                    try:
                        _PMP.objects.filter(fixture__in=fixtures_qs).delete()
                    except Exception:
                        pass
                # Sub plans (planned subs for fixtures)
                if _SubPlan is not None:
                    try:
                        _SubPlan.objects.filter(fixture__in=fixtures_qs).delete()
                    except Exception:
                        pass
                # Lineups (slots should cascade)
                try:
                    Lineup.objects.filter(fixture__in=fixtures_qs).delete()
                except Exception:
                    pass
                # Availability and sub-availability
                try:
                    Availability.objects.filter(fixture__in=fixtures_qs).delete()
                except Exception:
                    pass
                try:
                    SubAvailability.objects.filter(fixture__in=fixtures_qs).delete()
                except Exception:
                    pass

                # Optional: season-scoped notifications (and their receipts via cascade)
                if _Notification is not None:
                    try:
                        _Notification.objects.filter(season=season).delete()
                    except Exception:
                        pass

                # --- Finally, delete fixtures (the schedule) ---
                fixtures_qs.delete()

                # Clear league standings for this season
                try:
                    LeagueStanding.objects.filter(season=season).delete()
                except Exception:
                    pass

            messages.success(
                request,
                f"Season '{season}' has been reset: schedule, lineups, results, and standings cleared."
            )
        except Exception as e:
            messages.error(request, f"Failed to reset season: {e}")
        return redirect("admin_dashboard")

    now = timezone.now()

    # Upcoming matches (next 5 overall)
    upcoming_qs = (
        Fixture.objects
        .filter(date__gte=now)
        .order_by("date")[:5]
    )
    upcoming = list(upcoming_qs)
    for f in upcoming:
        lineup = getattr(f, "lineup", None)
        f.lineup_published = bool(lineup and getattr(lineup, "published", False))
        f.scores_entered = SlotScore.objects.filter(fixture=f).exists()

    # Roster snapshot (for active season)
    roster_count = 0
    roster_limit = None
    captains = []
    if active:
        roster_qs = RosterEntry.objects.filter(season=active).select_related("player")
        roster_count = roster_qs.count()
        roster_limit = getattr(active, "roster_limit", None) or 22
        if "is_captain" in [f.name for f in RosterEntry._meta.get_fields()]:
            c_qs = roster_qs.filter(is_captain=True)
        else:
            c_qs = roster_qs.filter(player__is_captain=True)
        captains = [re.player for re in c_qs.order_by("player__last_name", "player__first_name")]

    # Points & results summary for active season
    team_match_points = 0
    team_sub_points = 0
    wins = losses = ties = 0
    if active:
        season_fixtures = list(Fixture.objects.filter(season=active).order_by("week_number"))
        sub_totals = (
            SubResult.objects
            .filter(fixture__in=season_fixtures)
            .values("fixture_id")
            .annotate(total=Sum("points_cached"))
        )
        sub_map = {row["fixture_id"]: (row["total"] or 0) for row in sub_totals}

        for fx in season_fixtures:
            h, a = compute_fixture_match_points(fx)
            if SlotScore.objects.filter(fixture=fx).exists():
                if h > a:
                    wins += 1
                elif h < a:
                    losses += 1
                else:
                    ties += 1
            team_match_points += h
            team_sub_points += sub_map.get(fx.id, 0)

    # --- League Standings widget (admin-only, embedded) ---
    royals = None
    formset = None
    standings_rows = []
    standings_published = False

    try:
        # Ensure the Royals row exists for the active season
        if active:
            royals, _ = LeagueStanding.objects.get_or_create(
                season=active,
                team_name="Royals",
                defaults={"is_royals": True}
            )

            # Compute Royals total from the summary above
            try:
                royals_total = Decimal(team_match_points) + Decimal(team_sub_points)
            except Exception:
                royals_total = Decimal(str(team_match_points)) + Decimal(str(team_sub_points))

            # Non-Royals queryset
            qs = LeagueStanding.objects.filter(season=active, is_royals=False).order_by("team_name")

            if request.method == "POST" and action in {"save", "publish"}:
                mgmt_key = "standings-TOTAL_FORMS"
                has_mgmt = mgmt_key in request.POST
                FormSetCls = modelformset_factory(LeagueStanding, form=LeagueStandingForm, extra=6, can_delete=False)

                # Persist Royals auto points first
                try:
                    royals.points = royals_total
                    royals.updated_by = request.user
                    royals.save()
                except Exception:
                    pass

                created_or_updated = 0
                if has_mgmt:
                    # Manually read posted rows (works even if formset binding is quirky)
                    try:
                        total_forms = int(request.POST.get("standings-TOTAL_FORMS", "0"))
                    except ValueError:
                        total_forms = 0

                    with transaction.atomic():
                        for i in range(total_forms):
                            name = (request.POST.get(f"standings-{i}-team_name", "") or "").strip()
                            if not name:
                                continue
                            raw_pts = request.POST.get(f"standings-{i}-points", "")
                            try:
                                points_val = Decimal(str(raw_pts)) if str(raw_pts).strip() != "" else Decimal("0")
                                if points_val < 0:
                                    points_val = Decimal("0")
                            except InvalidOperation:
                                points_val = Decimal("0")

                            inst, _ = LeagueStanding.objects.get_or_create(
                                season=active,
                                team_name=name,
                                defaults={"is_royals": False}
                            )
                            inst.points = points_val
                            inst.is_royals = False
                            inst.updated_by = request.user
                            inst.save()
                            created_or_updated += 1

                    if action == "publish":
                        LeagueStanding.objects.filter(season=active).update(published=True)
                        messages.success(request, f"Standings published. ({created_or_updated} row(s) saved)\n")
                    else:
                        LeagueStanding.objects.filter(season=active).update(published=False)
                        messages.success(request, f"Standings saved as draft. ({created_or_updated} row(s) saved)")

                    # Rebuild unbound formset for display
                    formset = FormSetCls(queryset=qs, prefix="standings")
                else:
                    # Wrong <form> submitted
                    formset = FormSetCls(queryset=qs, prefix="standings")
                    messages.error(request, "Standings form was not submitted. Please use the Save/Publish buttons inside the Standings card.")
            else:
                # GET (or non-standings POST): refresh Royals auto points and build formset with six blanks
                try:
                    royals.points = royals_total
                    royals.updated_by = request.user
                    if hasattr(royals, "updated_at"):
                        royals.save(update_fields=["points", "updated_by", "updated_at"])
                    else:
                        royals.save()
                except Exception:
                    pass
                # Only build a fresh (unbound) formset if we don't already have one from the POST path
                if formset is None:
                    FormSetCls = modelformset_factory(LeagueStanding, form=LeagueStandingForm, extra=6, can_delete=False)
                    formset = FormSetCls(queryset=qs, prefix="standings")

            standings_rows = list(LeagueStanding.objects.filter(season=active).order_by("-points", "team_name"))
            standings_published = any(getattr(r, "published", False) for r in standings_rows)
    except Exception as e:
        # Do not break the dashboard if standings fail; just log and continue
        logger.exception("Admin standings widget failed: %s", e)

    context = {
        "seasons": seasons,
        "active": active,
        "upcoming": upcoming,
        "roster_count": roster_count,
        "roster_limit": roster_limit,
        "captains": captains,
        "team_match_points": int(team_match_points) if float(team_match_points).is_integer() else team_match_points,
        "team_sub_points": int(team_sub_points) if float(team_sub_points).is_integer() else team_sub_points,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        # Standings widget context
        "royals": royals,
        "formset": formset,
        "standings_rows": standings_rows,
        "standings_published": standings_published,
    }
    return render(request, "league/admin_panel/dashboard.html", context)


# --- Standalone League Standings Admin View ---
@login_required
@user_passes_test(is_staff_user)
def admin_league_standings(request):
    """Standalone page to edit & publish league standings without dashboard form conflicts."""

    # Seasons (newest first)
    seasons = Season.objects.all().order_by("-year" if hasattr(Season, "year") else "-id")
    active = seasons.filter(is_active=True).first() or seasons.first()

    # Compute Royals auto points (match + sub points) for active season
    team_match_points = 0
    team_sub_points = 0
    if active:
        season_fixtures = list(Fixture.objects.filter(season=active).order_by("week_number"))
        sub_totals = (
            SubResult.objects
            .filter(fixture__in=season_fixtures)
            .values("fixture_id")
            .annotate(total=Sum("points_cached"))
        )
        sub_map = {row["fixture_id"]: (row["total"] or 0) for row in sub_totals}
        for fx in season_fixtures:
            h, _ = compute_fixture_match_points(fx)
            team_match_points += h
            team_sub_points += sub_map.get(fx.id, 0)
    try:
        royals_total = Decimal(team_match_points) + Decimal(team_sub_points)
    except Exception:
        royals_total = Decimal(str(team_match_points)) + Decimal(str(team_sub_points))

    # Ensure Royals row exists and is up-to-date
    royals = None
    if active:
        royals, _ = LeagueStanding.objects.get_or_create(
            season=active, team_name="Royals", defaults={"is_royals": True}
        )
        try:
            royals.points = royals_total
            royals.updated_by = request.user
            if hasattr(royals, "updated_at"):
                royals.save(update_fields=["points", "updated_by", "updated_at"])
            else:
                royals.save()
        except Exception:
            pass

    action = request.POST.get("action") if request.method == "POST" else None

    if request.method == "POST" and action in {"save", "publish"} and active:
        # Manual parse of six rows (standings-0..5)
        created_or_updated = 0
        with transaction.atomic():
            for i in range(6):
                name = (request.POST.get(f"standings-{i}-team_name", "") or "").strip()
                if not name:
                    continue
                raw_pts = request.POST.get(f"standings-{i}-points", "")
                try:
                    points_val = Decimal(str(raw_pts)) if str(raw_pts).strip() != "" else Decimal("0")
                    if points_val < 0:
                        points_val = Decimal("0")
                except InvalidOperation:
                    points_val = Decimal("0")

                inst, _ = LeagueStanding.objects.get_or_create(
                    season=active,
                    team_name=name,
                    defaults={"is_royals": False}
                )
                inst.points = points_val
                inst.is_royals = False
                inst.updated_by = request.user
                inst.save()
                created_or_updated += 1

            # Flip publish state across the season standings
            if action == "publish":
                LeagueStanding.objects.filter(season=active).update(published=True)
                messages.success(request, f"Standings published. ({created_or_updated} row(s) saved)")
            else:
                LeagueStanding.objects.filter(season=active).update(published=False)
                messages.success(request, f"Standings saved as draft. ({created_or_updated} row(s) saved)")

        return redirect("admin_league_standings")

    # Prefill six input rows from existing non-Royals rows (sorted by team name)
    existing = list(LeagueStanding.objects.filter(season=active, is_royals=False).order_by("team_name")) if active else []
    initial_rows = []
    for i in range(6):
        if i < len(existing):
            initial_rows.append({
                "name": existing[i].team_name,
                "points": existing[i].points,
            })
        else:
            initial_rows.append({"name": "", "points": ""})

    # Preview standings for the right-hand card
    standings_rows = list(LeagueStanding.objects.filter(season=active).order_by("-points", "team_name")) if active else []
    standings_published = any(getattr(r, "published", False) for r in standings_rows)

    context = {
        "seasons": seasons,
        "active": active,
        "royals": royals,
        "initial_rows": initial_rows,
        "standings_rows": standings_rows,
        "standings_published": standings_published,
    }
    return render(request, "league/admin_panel/standings.html", context)

@login_required
@rl_deco(key='ip', rate='60/m', method='POST', block=True)
def notifications_mark_all_read(request):
    NotificationReceipt.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    messages.success(request, "All notifications marked as read.")
    return redirect(request.META.get("HTTP_REFERER", "schedule_list"))

@login_required
def notification_go(request, receipt_id):
    """
    Mark a single notification receipt as read, then redirect to its target URL.
    Falls back to dashboard if no URL present.
    """
    rec = get_object_or_404(NotificationReceipt, pk=receipt_id, user=request.user)
    if rec.read_at is None:
        rec.read_at = timezone.now()
        rec.save(update_fields=["read_at"])

    target = (rec.notification.url or "").strip()
    if not target:
        # sensible fallback
        return redirect("dashboard")
    return redirect(target)

@login_required
def notifications_list(request):
    """
    List notifications (read/unread/all) with pagination and bulk mark-as-read/unread.
    """
    status = request.GET.get("status", "unread")  # unread | read | all

    qs = NotificationReceipt.objects.filter(user=request.user).select_related("notification").order_by("-created_at")
    if status == "unread":
        qs = qs.filter(read_at__isnull=True)
    elif status == "read":
        qs = qs.filter(read_at__isnull=False)
    # else "all" → no extra filter

    # Bulk actions
    if request.method == "POST":
        action = request.POST.get("action")
        ids = request.POST.getlist("ids")
        if ids:
            recs = NotificationReceipt.objects.filter(user=request.user, id__in=ids)
            if action == "mark_read":
                from django.utils import timezone as _tz
                recs.filter(read_at__isnull=True).update(read_at=_tz.now())
                messages.success(request, "Marked selected as read.")
            elif action == "mark_unread":
                recs.update(read_at=None)
                messages.success(request, "Marked selected as unread.")
            return redirect(f"{reverse('notifications_list')}?status={status}")

    paginator = Paginator(qs, 10)  # 10 per page
    page = request.GET.get("page") or 1
    page_obj = paginator.get_page(page)

    # Counts for tabs/badges
    unread_count = NotificationReceipt.objects.filter(user=request.user, read_at__isnull=True).count()
    read_count = NotificationReceipt.objects.filter(user=request.user, read_at__isnull=False).count()
    all_count = unread_count + read_count

    return render(request, "league/notifications_list.html", {
        "page_obj": page_obj,
        "status": status,
        "unread_count": unread_count,
        "read_count": read_count,
        "all_count": all_count,
    })

@rl_deco(key='ip', rate='5/m', method='GET', block=False)
def healthz(request):
    if getattr(request, "limited", False):
        return JsonResponse({"detail": "Too many requests"}, status=429)
    return JsonResponse({"status": "ok", "db": "ok"})
    """Lightweight health endpoint: returns 200 and DB ping status."""
    db = "ok"
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1;")
            c.fetchone()
    except Exception as e:
        db = f"error: {e.__class__.__name__}"
    return JsonResponse({"status": "ok", "db": db})
# ... Do not modify anything else above ...

# Themed password reset confirm view for custom widget styling
@method_decorator(rl_deco(key='ip', rate='20/h', method='POST', block=True), name='dispatch')
class ThemedPasswordResetConfirmView(PasswordResetConfirmView):
    """Use our glass/Bootstrap widget attrs on the reset-confirm form."""
    template_name = "account/password_reset_confirm.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        try:
            form.fields["new_password1"].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "New password",
                "id": "id_new_password1",
            })
            form.fields["new_password2"].widget.attrs.update({
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Confirm password",
                "id": "id_new_password2",
            })
        except Exception:
            # If the form/fields differ, don't break the page
            pass
        return form

from django.contrib.auth.forms import PasswordResetForm
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site

class ThemedPasswordResetForm(PasswordResetForm):
    def save(self, domain_override=None,
             subject_template_name='registration/password_reset_subject.txt',
             email_template_name='registration/password_reset_email.html',
             use_https=False, token_generator=default_token_generator,
             from_email=None, request=None, html_email_template_name=None,
             extra_email_context=None):
        """
        Same as Django's default, but adds a single `reset_url` into the email context
        so templates can just use {{ reset_url }} (like our invite {{ accept_url }}).
        """
        for user in self.get_users(self.cleaned_data["email"]):
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = token_generator.make_token(user)

            if domain_override:
                domain = domain_override
                site_name = domain
            else:
                current_site = get_current_site(request)
                site_name = current_site.name
                domain = current_site.domain

            protocol = 'https' if use_https else 'http'
            reset_path = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
            reset_url = f"{protocol}://{domain}{reset_path}"

            context = {
                'email': user.email,
                'domain': domain,
                'site_name': site_name,
                'uid': uid,
                'user': user,
                'token': token,
                'protocol': protocol,
                'reset_url': reset_url,
            }
            if extra_email_context:
                context.update(extra_email_context)

            self.send_mail(
                subject_template_name, email_template_name, context, from_email,
                user.email, html_email_template_name=html_email_template_name,
            )

@method_decorator(rl_deco(key='ip', rate='10/h', method='POST', block=True), name='dispatch')
@method_decorator(rl_deco(key='post:email', rate='5/h', method='POST', block=True), name='dispatch')
class ThemedPasswordResetView(PasswordResetView):
    form_class = ThemedPasswordResetForm
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"  # HTML part
    subject_template_name = "emails/password_reset_subject.txt"
    template_name = "account/password_reset.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        try:
            form.fields["email"].widget.attrs.update({
                "class": "form-control",
                "placeholder": "Enter your email",
                "autocomplete": "email",
                "id": "id_email",
            })
        except Exception:
            pass
        return form

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
@rl_deco(key='ip', rate='20/h', method='POST', block=True)
def admin_player_resend_invite(request, player_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    player = get_object_or_404(Player, pk=player_id)

    # --- Align guard with template logic ---
    # Allow resend if: (A) a pending invite exists, OR (B) the linked user has no real password yet
    user = getattr(player, "user", None)
    pwd = getattr(user, "password", "") if user else ""
    invite_pending = bool(getattr(player, "invite_token", None))
    no_password = (not pwd) or str(pwd).startswith("!")

    # Block ONLY when there is NO pending invite and the user clearly has a real password
    if (not invite_pending) and (not no_password):
        messages.info(request, "This player already has an active account. Use Reset PW instead.")
        return redirect("admin_manage_players")

    # (Re)issue an invite token
    try:
        player.issue_invite()
    except Exception:
        player.invite_token = uuid.uuid4()
        player.invite_sent_at = timezone.now()
        player.save(update_fields=["invite_token", "invite_sent_at"])

    # Send the branded invite email
    try:
        _send_invite_email(player, request)
        messages.success(request, f"Invitation re-sent to {player.email}.")
    except Exception:
        messages.error(request, "Could not send invite email. Please check email settings.")

    return redirect("admin_manage_players")
# --- SMS Opt-in API endpoints ---

from django.contrib.auth.decorators import login_required

@login_required
@require_POST
def sms_start(request):
    logger.info("sms_start: begin")
    user = request.user

    # 1) Presence check (clear error message)
    phone_raw = request.POST.get("phone", "").strip()
    if not phone_raw:
        logger.warning("sms_start: missing phone")
        return JsonResponse({"error": "Missing phone"}, status=400)

    # 2) Normalize & validate format
    phone = _normalize_phone(phone_raw)
    if not phone:
        logger.warning("sms_start: invalid phone input=%r", phone_raw)
        return JsonResponse({"error": "Invalid phone"}, status=400)

    # 3) Cooldown: block resends within 30 seconds for this user+phone
    try:
        recent_cutoff = timezone.now() - timedelta(seconds=30)
        recent_exists = PhoneVerification.objects.filter(
            user=user,
            phone_e164=phone,
            created_at__gte=recent_cutoff,
            consumed_at__isnull=True,
        ).exists()
    except Exception:
        recent_exists = False
    if recent_exists:
        logger.info("sms_start: resend blocked by cooldown for %s", phone)
        return JsonResponse({"ok": True, "message": "OTP already sent. Please wait before resending."}, status=200)

    # 4) Invalidate any previous unconsumed codes for this user+phone to prevent race/confusion
    try:
        PhoneVerification.objects.filter(
            user=user,
            phone_e164=phone,
            consumed_at__isnull=True,
        ).update(consumed_at=timezone.now())
    except Exception:
        pass

    # 5) Generate and persist a single active OTP
    code = f"{random.randint(0, 999999):06d}"
    pv = PhoneVerification.objects.create(
        user=user,
        phone_e164=phone,
        code=code,
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    logger.info("sms_start: issued code id=%s for=%s", pv.id, phone)

    # 4) Render SMS body from template
    sms_text = render_to_string("sms/otp_verify.txt", {"code": code}).strip()

    # 5) Send via Brevo directly
    api_key = getattr(settings, "BREVO_API_KEY", "") or getattr(settings, "BREVO_SMS_API_KEY", "")
    sender = getattr(settings, "BREVO_SMS_SENDER", "ROYALS")
    if not api_key:
        logger.error("sms_start: missing BREVO API key in settings")
        return JsonResponse({"error": "SMS provider is not configured"}, status=500)

    headers = {
        "api-key": api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }
    payload = {
        "sender": sender,
        "recipient": phone,
        "content": sms_text,
        "type": "transactional",
    }
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/transactionalSMS/send",
            headers=headers,
            data=json.dumps(payload),
            timeout=10,
        )
        if resp.status_code // 100 != 2:
            logger.warning("sms_start: Brevo send failed status=%s body=%s", resp.status_code, resp.text[:500])
            return JsonResponse({"error": "Failed to send code"}, status=502)
    except Exception as e:
        logger.exception("sms_start: exception during Brevo send: %s", e)
        return JsonResponse({"error": "Failed to send code"}, status=502)

    logger.info("sms_start: success for %s", phone)
    return JsonResponse({"ok": True, "message": "OTP sent"})


@login_required
@require_POST
def sms_verify(request):
    """Verify an OTP code and mark phone as verified."""
    user = request.user
    phone = _normalize_phone(request.POST.get("phone", "").strip())
    code = request.POST.get("code", "").strip()

    # Look at a few recent unconsumed codes (in case of delivery delays), newest first
    codes_qs = PhoneVerification.objects.filter(
        user=user,
        phone_e164=phone,
        consumed_at__isnull=True,
    ).order_by("-created_at")

    if not codes_qs.exists():
        return JsonResponse({"error": "No active verification"}, status=400)

    now_ts = timezone.now()
    matched = None
    expired_match = False

    # Accept the first non-expired code that matches the submitted value
    for cand in codes_qs[:5]:  # defensive limit
        if cand.code == code:
            if now_ts > cand.expires_at:
                expired_match = True
                continue
            matched = cand
            break

    if matched is None:
        # If user typed a correct-but-expired code, tell them explicitly
        if expired_match:
            return JsonResponse({"error": "Code expired"}, status=400)
        else:
            # Increment attempts on the newest record for telemetry
            newest = codes_qs.first()
            try:
                newest.attempts += 1
                newest.save(update_fields=["attempts"])
            except Exception:
                pass
            return JsonResponse({"error": "Invalid code"}, status=400)

    # success: consume the matched code and invalidate siblings
    matched.consumed_at = now_ts
    matched.save(update_fields=["consumed_at"])
    try:
        PhoneVerification.objects.filter(
            user=user,
            phone_e164=phone,
            consumed_at__isnull=True,
        ).exclude(id=matched.id).update(consumed_at=now_ts)
    except Exception:
        pass

    # Persist verified phone on the user's notification preferences
    from .models import NotificationPreference
    now_ts = timezone.now()
    prefs, _ = NotificationPreference.objects.update_or_create(
        user=user,
        defaults={
            "phone_e164": matched.phone_e164,
            "phone_verified_at": now_ts,
        },
    )

    # Session latch so the immediately-following consent in the same session can't race the DB
    try:
        request.session["sms_verified_phone"] = prefs.phone_e164
        request.session["sms_verified_at"] = now_ts.isoformat()
    except Exception:
        pass

    logger.info("sms_verify: verified user_id=%s phone=%s", getattr(user, "id", None), prefs.phone_e164)

    logger.info("sms_verify: verified user_id=%s phone=%s", getattr(user, "id", None), prefs.phone_e164)
    return JsonResponse({"ok": True, "message": "Phone verified", "phone_e164": prefs.phone_e164})


@login_required
@require_POST
def sms_consent(request):
    """Record user consent for SMS notifications."""
    user = request.user
    consent = request.POST.get("consent") == "true"
    consent_text = request.POST.get("consent_text", "")

    logger.info("sms_consent: user_id=%s consent=%s", getattr(user, "id", None), consent)

    # Honor a session latch set by sms_verify to avoid DB read races
    session_ok = bool(request.session.get("sms_verified_phone"))

    prefs, _ = NotificationPreference.objects.get_or_create(user=user)

    # Ensure we’re reading the latest value set by sms_verify
    try:
        prefs.refresh_from_db(fields=["phone_verified_at", "phone_e164"])  # pulls most recent values
    except Exception:
        pass

    # Require either DB-verified phone or a same-session verify latch
    if not (prefs.phone_verified_at or session_ok):
        logger.info(
            "sms_consent: user_id=%s attempted consent without verified phone (e164=%s verified_at=%s)",
            getattr(user, "id", None), getattr(prefs, "phone_e164", None), getattr(prefs, "phone_verified_at", None)
        )
        return JsonResponse({"error": "Phone not verified"}, status=400)

    if consent:
        prefs.sms_opt_in = True
        prefs.sms_consent_text = consent_text
        prefs.sms_consent_ip = request.META.get("REMOTE_ADDR")
        prefs.sms_consent_user_agent = request.META.get("HTTP_USER_AGENT", "")
        prefs.sms_consent_at = timezone.now()
        prefs.save()
        # Clear session latch after successful consent
        try:
            request.session.pop("sms_verified_phone", None)
            request.session.pop("sms_verified_at", None)
        except Exception:
            pass
        return JsonResponse({"ok": True, "message": "Consent recorded"})
    else:
        prefs.sms_opt_in = False
        prefs.sms_enabled = False
        prefs.save()
        # Clear session latch as well when explicitly withdrawing
        try:
            request.session.pop("sms_verified_phone", None)
            request.session.pop("sms_verified_at", None)
        except Exception:
            pass
        return JsonResponse({"ok": True, "message": "Consent withdrawn"})

@login_required
def my_team_view(request):
    """My Team: season-scoped roster view with per-user share toggles.
    Uses RosterEntry (no Team model) and gates contact display by teammate opt-ins.
    """
    # Resolve the logged-in player's profile
    player = getattr(request.user, "player_profile", None)

    # Seasons where this user is rostered (matches My Results behavior)
    if player:
        seasons_qs = (
            Season.objects
            .filter(roster_entries__player=player)
            .distinct()
            .order_by("-year" if hasattr(Season, "year") else "-id")
        )
    else:
        seasons_qs = Season.objects.none()

    # Determine selected season: ?season=<id> > active (if rostered) > most recent rostered
    sel_id = request.GET.get("season")
    selected_season = None
    if sel_id:
        selected_season = seasons_qs.filter(pk=sel_id).first()
    if not selected_season and player:
        selected_season = seasons_qs.filter(is_active=True).first()
    if not selected_season:
        selected_season = seasons_qs.first()

    # Build roster for the selected season (season-level roster; no Team model)
    roster_entries = RosterEntry.objects.none()
    if player and selected_season:
        if RosterEntry.objects.filter(season=selected_season, player=player).exists():
            roster_entries = (
                RosterEntry.objects
                .filter(season=selected_season)
                .select_related("player", "player__user")
                .select_related("player__user__notification_prefs")
                .order_by("player__last_name", "player__first_name")
            )
        else:
            messages.info(request, "You’re not on this season’s roster.")

    # Materialize and attach each player's NotificationPreference as `_prefs` for template use
    if hasattr(roster_entries, "__iter__"):
        entries = []
        for e in roster_entries:
            u = getattr(getattr(e, "player", None), "user", None)
            pref = None
            if u is not None:
                pref = (
                    getattr(u, "notification_prefs", None)
                    or getattr(u, "notificationpreference", None)
                    or getattr(u, "notification_preference", None)
                )
                if pref is None:
                    try:
                        from .models import NotificationPreference as _NP
                        pref, _ = _NP.objects.get_or_create(user=u)
                    except Exception:
                        pref = None
            e.prefs = pref
            entries.append(e)
        roster_entries = entries

    # Load/create user notification prefs and share toggles form
    from .models import NotificationPreference
    prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)

    # Import the form lazily to avoid hard import errors if not yet created
    try:
        from .forms import ShareContactPrefsForm
    except Exception:
        # Minimal inline fallback if the form class isn't present yet
        from django import forms
        class ShareContactPrefsForm(forms.ModelForm):
            class Meta:
                model = NotificationPreference
                fields = ["share_email_with_team", "share_mobile_with_team"]
                widgets = {
                    "share_email_with_team": forms.CheckboxInput(attrs={"class": "form-check-input"}),
                    "share_mobile_with_team": forms.CheckboxInput(attrs={"class": "form-check-input"}),
                }

    if request.method == "POST":
        form = ShareContactPrefsForm(request.POST, instance=prefs)
        if form.is_valid():
            form.save()
            messages.success(request, "Contact sharing preferences updated.")
            # Preserve the selected season on redirect
            q = f"?season={selected_season.pk}" if selected_season else ""
            return redirect(f"{reverse('my_team')}{q}")
    else:
        form = ShareContactPrefsForm(instance=prefs)

    return render(request, "league/my_team.html", {
        "player": player,
        "seasons": seasons_qs,
        "selected_season": selected_season,
        "roster_entries": roster_entries,
        "form": form,
    })

@login_required
@user_passes_test(is_staff_user)
def admin_playoff_eligibility(request):
    # Seasons list (newest first)
    seasons = Season.objects.all().order_by("-year" if hasattr(Season, "year") else "-id")
    sel_id = request.GET.get("season")
    selected = seasons.filter(pk=sel_id).first() if sel_id else seasons.filter(is_active=True).first() or seasons.first()

    # Roster for selected season
    roster_entries = RosterEntry.objects.filter(season=selected).select_related("player", "player__user").order_by("player__last_name", "player__first_name") if selected else []

    # Early out
    if not selected:
        return render(request, "league/admin_panel/playoff_eligibility.html", {
            "seasons": seasons,
            "selected": None,
            "rows": [],
        })

    # ---- Gather all needed season data in bulk ----

    # 1) Lineup appearances by player & slot (S1..D3)
    # Map: fixture_id -> {slot_code -> SlotScore} for W/L calc
    scores_by_fixture_slot = defaultdict(dict)
    for s in SlotScore.objects.filter(fixture__season=selected).only("fixture_id", "slot_code", "result", "home_games", "away_games"):
        scores_by_fixture_slot[s.fixture_id][s.slot_code] = s

    # Map: player_id -> Counter({slot_code: count})
    lineup_counts = defaultdict(Counter)
    # Map: player_id -> {'wins': x, 'losses': y}
    lineup_wl = defaultdict(lambda: {"wins": 0, "losses": 0})

    # Grab all lineup slots for this season (with players assigned)
    slots_qs = (
        LineupSlot.objects
        .filter(lineup__fixture__season=selected)
        .select_related("lineup__fixture", "player1", "player2")
    )

    for ls in slots_qs:
        slot_code = ls.slot  # e.g., 'S1', 'D2'
        sc = scores_by_fixture_slot.get(ls.lineup.fixture_id, {}).get(ls.slot)

        for p in (ls.player1, ls.player2):
            if not p:
                continue
            lineup_counts[p.id][slot_code] += 1
            # W/L from slot score (if present)
            if sc:
                r = sc.result
                if r in (SlotScore.Result.WIN, SlotScore.Result.WIN_FF, 'W', 'WF'):
                    lineup_wl[p.id]["wins"] += 1
                elif r in (SlotScore.Result.LOSS, SlotScore.Result.LOSS_FF, 'L', 'LF'):
                    lineup_wl[p.id]["losses"] += 1
                elif r in (SlotScore.Result.TIE, 'T'):
                    # ties don't affect W-L, but you could track if desired
                    pass

    # 2) Sub results by player (counts per slot, W/L, sub points)
    sub_counts = defaultdict(Counter)
    sub_wl = defaultdict(lambda: {"wins": 0, "losses": 0})
    sub_points = defaultdict(lambda: Decimal("0"))

    sub_qs = SubResult.objects.filter(fixture__season=selected).select_related("player", "fixture")
    for sr in sub_qs:
        p = sr.player
        if not p:
            continue
        # slot_code resolution (defensive)
        slot_code = getattr(sr, "slot_code", None)
        if not slot_code:
            # Try reading a display like "S2" from get_slot_code_display(); else infer from kind (fallback)
            try:
                slot_code = sr.get_slot_code_display() or ""
            except Exception:
                slot_code = ""
            if slot_code and " " in slot_code:
                slot_code = slot_code.split()[0]  # e.g., "S2 — ..." -> "S2"
            if not slot_code:
                # crude fallback from kind: Singles -> S?, Doubles -> D?
                slot_code = "S?" if str(getattr(sr, "kind", "")).upper().startswith("S") else "D?"
        sub_counts[p.id][slot_code] += 1

        r = sr.result
        if r in (SlotScore.Result.WIN, SlotScore.Result.WIN_FF, 'W', 'WF'):
            sub_wl[p.id]["wins"] += 1
        elif r in (SlotScore.Result.LOSS, SlotScore.Result.LOSS_FF, 'L', 'LF'):
            sub_wl[p.id]["losses"] += 1

        sub_points[p.id] += (sr.points_cached if sr.points_cached is not None else Decimal("0"))

    # 3) Lineup points (PlayerMatchPoints) + add sub points
    player_points = defaultdict(lambda: Decimal("0"))
    pmp = PlayerMatchPoints.objects.filter(fixture__season=selected).values("player_id").annotate(total=Sum("points"))
    for row in pmp:
        player_points[row["player_id"]] += (row["total"] if row["total"] is not None else Decimal("0"))
    for pid, sp in sub_points.items():
        player_points[pid] += sp

    # ---- Build rows ----
    def number_bucket_counts(counter: Counter, prefix: str) -> dict:
        # returns counts for S1..S3 (if prefix='S') or D1..D3 (if 'D'), ignoring unknowns like 'S?'
        out = {"1": 0, "2": 0, "3": 0}
        for k, v in counter.items():
            if isinstance(k, str) and k.startswith(prefix) and len(k) >= 2 and k[1] in ("1", "2", "3"):
                out[k[1]] += v
        return out

    rows = []
    for re in roster_entries:
        p = re.player
        pid = p.id

        # Per-slot counts (lineup + sub)
        lineup_c = lineup_counts[pid]
        sub_c = sub_counts[pid]
        def total_slot(slot):
            return lineup_c.get(slot, 0) + sub_c.get(slot, 0)

        s1 = total_slot("S1"); s2 = total_slot("S2"); s3 = total_slot("S3")
        d1 = total_slot("D1"); d2 = total_slot("D2"); d3 = total_slot("D3")

        # Number buckets (combined singles + doubles)
        singles_by_num = number_bucket_counts(lineup_c + sub_c, "S")
        doubles_by_num = number_bucket_counts(lineup_c + sub_c, "D")
        num1 = singles_by_num["1"] + doubles_by_num["1"]
        num2 = singles_by_num["2"] + doubles_by_num["2"]
        num3 = singles_by_num["3"] + doubles_by_num["3"]

        # Eligibility by number
        elig1 = num1 >= 3
        elig2 = num2 >= 3
        elig3 = num3 >= 3

        # Overall totals
        total_matches = s1 + s2 + s3 + d1 + d2 + d3
        overall_eligible = total_matches >= 5

        # W/L (lineup + sub)
        wins = lineup_wl[pid]["wins"] + sub_wl[pid]["wins"]
        losses = lineup_wl[pid]["losses"] + sub_wl[pid]["losses"]
        win_pct = (wins / (wins + losses)) * 100 if (wins + losses) else 0.0

        # Prepare points for display: int if whole number, else 2 decimals
        _pts = player_points[pid]
        try:
            points_val = int(_pts) if _pts == _pts.to_integral_value() else _pts.quantize(Decimal("0.01"),
                                                                                          rounding=ROUND_HALF_UP)
        except Exception:
            points_val = float(_pts)

        rows.append({
            "player": p,
            "S1": s1, "S2": s2, "S3": s3, "D1": d1, "D2": d2, "D3": d3,
            "total_matches": total_matches,
            "points": points_val,
            "wins": wins, "losses": losses, "win_pct": round(win_pct, 1),
            "elig1": elig1, "elig2": elig2, "elig3": elig3,
            "overall_eligible": overall_eligible,
        })

    return render(request, "league/admin_panel/playoff_eligibility.html", {
        "seasons": seasons,
        "selected": selected,
        "rows": rows,
    })
# Twilio Status Callbacks
@csrf_exempt
def twilio_sms_status(request):
    # Optionally verify X-Twilio-Signature
    sid = request.POST.get("MessageSid")
    status = request.POST.get("MessageStatus")  # queued, sent, delivered, undelivered, failed
    if not sid or not status:
        return HttpResponseBadRequest("missing fields")
    try:
        attempt = DeliveryAttempt.objects.get(provider_message_id=sid, provider="twilio")
        mapping = {
            "queued": "QUEUED",
            "accepted": "QUEUED",
            "sending": "SENDING",
            "sent": "SENT",
            "delivered": "DELIVERED",
            "undelivered": "FAILED",
            "failed": "FAILED",
        }
        attempt.status = mapping.get(status, attempt.status)
        attempt.save(update_fields=["status"])
    except DeliveryAttempt.DoesNotExist:
        pass
    return HttpResponse("ok")