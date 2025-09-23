# league/management/commands/send_availability_reminders.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.urls import reverse
from datetime import timedelta
import logging
from django.contrib.auth import get_user_model
User = get_user_model()
from league.models import Fixture  # adjust imports as needed
from league.notifications import send_event
from league.notifications import AVAILABILITY_REMINDER_5D
from urllib.parse import urljoin
from django.conf import settings

logger = logging.getLogger("league")

class Command(BaseCommand):
    help = "Send availability reminders for the next upcoming match to rostered players who haven't responded."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=5,
            help="How many days ahead to consider 'upcoming' (default: 5). "
                 "If not found in that window, falls back to the next future fixture.",
        )

    def handle(self, *args, **options):
        now = timezone.localtime()
        today = now.date()
        days = options["days"]

        # 1) Pick the next upcoming fixture
        upcoming_qs = (
            Fixture.objects
            .filter(date__date__gte=today, is_bye=False)
            .select_related("season")
            .order_by("date")
        )

        if days:
            upper = today + timedelta(days=days)
            window_qs = upcoming_qs.filter(date__date__lte=upper)
            fixture = window_qs.first() or upcoming_qs.first()
        else:
            fixture = upcoming_qs.first()

        if not fixture:
            self.stdout.write(self.style.WARNING("No upcoming fixtures found; nothing to do."))
            return

        # 2) Identify rostered players who haven't set availability for this fixture
        players_missing = self._players_missing_availability(fixture)
        if not players_missing:
            logger.info("AVAILABILITY_REMINDER: everyone has responded for fixture=%s; nothing to do", fixture.id)
            self.stdout.write(self.style.SUCCESS("All players have set availability."))
            return

        # 3) Build context & recipients
        detail_url = self._abs_url(reverse("availability_update", args=[fixture.id]))
        when_text = timezone.localtime(fixture.date).strftime("%a %b %d, %I:%M %p")

        # per-user ctx is minimal here; the email/text is uniform with personalized greeting
        per_user_ctx = {}               # keyed by user.id if you want greet name; optional
        user_player_map = {}            # useful if your templates reference map or if send_event expects it
        users_list = []

        for player in players_missing:
            u = getattr(player, "user", None)
            if not u:
                continue
            users_list.append(u)
            per_user_ctx[u.id] = {
                "player_first_name": (u.first_name or "").strip() or None
            }
            user_player_map[u.id] = player

        if not users_list:
            self.stdout.write(self.style.WARNING("No users with accounts among players missing availability."))
            return

        base_ctx = {
            "fixture": fixture,
            "match_dt": fixture.date,
            "opponent": getattr(fixture, "opponent", ""),
            "fixture_url": detail_url,     # CTA should land on availability page for that fixture
        }

        # 4) (Optional) duplicate prevention: skip if we already sent *today*
        if self._already_sent_today(fixture):
            logger.info("AVAILABILITY_REMINDER: already sent today for fixture=%s; skipping", fixture.id)
            self.stdout.write(self.style.WARNING("Reminder already sent today; skipping."))
            return

        # 5) Send via your unified pipeline (preferences, ENABLE flags handled there)
        notif, attempts = send_event(
            AVAILABILITY_REMINDER_5D,
            users=users_list,
            season=fixture.season,
            fixture=fixture,
            title=f"Availability needed — vs {fixture.opponent or 'opponent'}",
            body=f"Please set your availability for {when_text}.",
            url=detail_url,
            context=base_ctx,
            per_user_ctx=per_user_ctx,
            user_player_map=user_player_map,
        )

        attempts_count = attempts if isinstance(attempts, int) else (len(attempts) if attempts is not None else None)
        logger.info(
            "AVAILABILITY_REMINDER: fixture=%s sent notif=%s attempts=%s recipients=%s",
            fixture.id, getattr(notif, "id", None), attempts_count, len(users_list)
        )
        self.stdout.write(self.style.SUCCESS(
            f"Availability reminders done. recipients={len(users_list)} for fixture={fixture.id}"
        ))

    # ---------- helpers ----------

    def _players_missing_availability(self, fixture):
        """
        Return iterable of Players on the roster for `fixture.season` who have NOT submitted availability.
        Assumes an Availability model or equivalent; adjust to your schema.
        Criteria:
          - No Availability row for (fixture, player), or
          - Availability.status in ('', None, '?') i.e., not explicitly 'A' or 'N'
        """
        from league.models import Player  # import here to avoid cycles; adjust as needed

        season = fixture.season

        # (A) Start from rostered players for this season
        # If you have a concrete Roster/RosterEntry model, use that instead of all Players:
        #   rostered = Player.objects.filter(roster_entries__season=season, roster_entries__active=True)
        # For now, assume a helper exists; otherwise fallback to all players linked to season/team.
        try:
            rostered = Player.objects.filter(rosters__season=season, rosters__active=True)
            if not rostered.exists():
                # fallback: all players with a profile on this season's team (adapt to your models)
                rostered = Player.objects.filter(team=season.team)  # adjust if you have season.team
        except Exception:
            # ultimate fallback: all Players (you can tighten this)
            rostered = Player.objects.all()

        # (B) Exclude players who have set availability for this fixture
        # Adapt this block to your actual Availability schema.
        try:
            from league.models import Availability  # expected fields: fixture, player, status
            # grab responses for this fixture
            responses = Availability.objects.filter(fixture=fixture).values_list("player_id", "status")
            answered = set()
            for pid, status in responses:
                s = (status or "").strip().upper()
                if s in ("A", "N"):   # treat '?' or '' as no-answer
                    answered.add(pid)
            missing = rostered.exclude(id__in=answered)
        except Exception:
            # If you don’t have an Availability model, fall back to your existing helper:
            #   - maybe fixture.user_status map or a method on fixture?
            missing = rostered  # as a safe default, everyone gets reminded

        return list(missing)

    def _already_sent_today(self, fixture):
        """Return True if we already sent this reminder today for this fixture."""
        try:
            from django.utils import timezone
            from league.models import Notification
            today = timezone.localdate()
            return Notification.objects.filter(
                event_key=AVAILABILITY_REMINDER_5D,
                fixture=fixture,
                created_at__date=today,
            ).exists()
        except Exception:
            return False

    def _abs_url(self, path: str) -> str:
        base = getattr(settings, "SITE_BASE_URL", None) or "http://localhost:8000"

        if not path:
            return ""

        # if it’s already absolute, leave it alone
        if path.startswith("http://") or path.startswith("https://"):
            return path

        # urljoin handles slashes cleanly
        return urljoin(base.rstrip("/") + "/", path.lstrip("/"))