# league/management/commands/send_match_reminders.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.urls import reverse
from datetime import timedelta
import logging
from league.models import Fixture, Lineup, LineupSlot  # adjust paths if different
from league.notifications import send_event
from league.notifications import MATCH_REMINDER_24H
from urllib.parse import urljoin
from django.conf import settings

logger = logging.getLogger("league")

class Command(BaseCommand):
    help = "Send match reminders for fixtures occurring tomorrow (published lineups only)."

    def handle(self, *args, **options):
        now = timezone.localtime()
        tomorrow = (now + timedelta(days=1)).date()
        # Grab fixtures tomorrow with a published lineup
        fixtures = (
            Fixture.objects.filter(date__date=tomorrow, is_bye=False)
            .select_related("season")
        )

        total_fixtures = 0
        total_players = 0

        for fx in fixtures:
            lineup = (
                Lineup.objects.filter(fixture=fx, published=True)
                .prefetch_related("slots__player1__user", "slots__player2__user")
                .first()
            )
            if not lineup:
                logger.info("MATCH_REMINDER: no published lineup for fixture=%s; skipping", fx.id)
                continue

            total_fixtures += 1
            detail_url = self._abs_url(reverse("fixture_detail", args=[fx.id]))
            when_text = timezone.localtime(fx.date).strftime("%a %b %d, %I:%M %p")

            # Build per-user ctx like lineup_published
            per_user_ctx = {}
            user_player_map = {}

            # Each slot -> one or two recipients
            for ls in lineup.slots.all():
                label = ls.get_slot_display() if hasattr(ls, "get_slot_display") else getattr(ls, "slot", "TBD")
                is_doubles = str(getattr(ls, "slot", "")).upper().startswith("D")

                def add_user(player, partner):
                    nonlocal total_players
                    if not player: return
                    u = getattr(player, "user", None)
                    if not u: return
                    extras = {
                        "slot_label": label,
                        "slot_name": label,
                        "is_doubles": is_doubles,
                        "player_first_name": getattr(u, "first_name", None),
                    }
                    if is_doubles and partner:
                        # Prefer partner's User names
                        partner_name = None
                        if getattr(partner, "user", None):
                            fn = (getattr(partner.user, "first_name", "") or "").strip()
                            ln = (getattr(partner.user, "last_name", "") or "").strip()
                            partner_name = (f"{fn} {ln}".strip()) or (fn or ln)
                        # fallback to Player names
                        if not partner_name:
                            fnp = (getattr(partner, "first_name", "") or "").strip()
                            lnp = (getattr(partner, "last_name", "") or "").strip()
                            partner_name = (f"{fnp} {lnp}".strip()) or (fnp or lnp)
                        if partner_name:
                            extras["partner_full_name"] = partner_name

                    per_user_ctx[u.id] = extras
                    user_player_map[u.id] = player
                    total_players += 1

                add_user(getattr(ls, "player1", None), getattr(ls, "player2", None))
                if is_doubles:
                    add_user(getattr(ls, "player2", None), getattr(ls, "player1", None))

            if not per_user_ctx:
                logger.info("MATCH_REMINDER: no users in lineup for fixture=%s; skipping", fx.id)
                continue

            base_ctx = {
                "fixture": fx,
                "match_dt": fx.date,
                "opponent": getattr(fx, "opponent", ""),
                "fixture_url": detail_url,
                # Optional: if you compute team record or anything else, add here
            }

            # Build a list of actual User objects (NotificationReceipt.user expects a User FK)
            users_list = []
            for p in user_player_map.values():
                u = getattr(p, "user", None)
                if u:
                    users_list.append(u)

            notif, attempts = send_event(
                MATCH_REMINDER_24H,
                users=users_list,   # list of User objects or IDs (match your impl)
                season=fx.season,
                fixture=fx,
                title=f"Match tomorrow — vs {fx.opponent or 'Opponent'}",
                body=f"{when_text}.",
                url=detail_url,
                context=base_ctx,
                per_user_ctx=per_user_ctx,
                user_player_map=user_player_map,
            )
            attempts_count = attempts if isinstance(attempts, int) else (len(attempts) if attempts is not None else None)
            logger.info("MATCH_REMINDER: fixture=%s sent notif=%s attempts=%s recipients=%s",
                        fx.id, getattr(notif, "id", None), attempts_count, len(per_user_ctx))

        self.stdout.write(self.style.SUCCESS(
            f"Match reminders done. fixtures={total_fixtures} recipients={total_players}"
        ))

    def _abs_url(self, path: str) -> str:
        base = getattr(settings, "PUBLIC_BASE_URL", None) or "http://localhost:8000"

        if not path:
            return ""

        # if it’s already absolute, leave it alone
        if path.startswith("http://") or path.startswith("https://"):
            return path

        # urljoin handles slashes cleanly
        return urljoin(base.rstrip("/") + "/", path.lstrip("/"))