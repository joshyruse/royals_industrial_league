# league/services/reset_season.py  (new file)
from contextlib import suppress
from django.db import transaction
from django.db.models import Sum

from league.models import (
    Season, Fixture, Lineup, SlotScore, SubResult, Availability, SubAvailability,
    LeagueStanding, # plus optional models if you have them:
    # SubPlan, PlayerMatchPoints, Notification
)

def reset_season(season: Season, dry_run: bool = False) -> dict:
    """
    If dry_run=True, return counts of what would be deleted (no changes).
    If dry_run=False, perform deletion in an atomic transaction and return counts of what was deleted.
    """
    fixtures_qs = Fixture.objects.filter(season=season)

    # Build a consistent list of (label, queryset) so dry-run and real run share logic
    groups = []

    # Optional models: include only if they exist in your project
    with suppress(Exception):
        from league.models import SubPlan
        groups.append(("Sub plans", SubPlan.objects.filter(fixture__in=fixtures_qs)))
    with suppress(Exception):
        from league.models import PlayerMatchPoints
        groups.append(("Player match points", PlayerMatchPoints.objects.filter(fixture__in=fixtures_qs)))

    groups.extend([
        ("Sub results",        SubResult.objects.filter(fixture__in=fixtures_qs)),
        ("Slot scores",        SlotScore.objects.filter(fixture__in=fixtures_qs)),
        ("Lineups",            Lineup.objects.filter(fixture__in=fixtures_qs)),
        ("Availability",       Availability.objects.filter(fixture__in=fixtures_qs)),
        ("Sub availability",   SubAvailability.objects.filter(fixture__in=fixtures_qs)),
    ])

    # Optionally: season-scoped notifications
    with suppress(Exception):
        from league.models import Notification
        groups.append(("Notifications", Notification.objects.filter(season=season)))

    # Standings and fixtures last
    groups.append(("Fixtures",          fixtures_qs))
    groups.append(("League standings",  LeagueStanding.objects.filter(season=season)))

    counts = {label: qs.count() for (label, qs) in groups}

    if dry_run:
        # No changes—just return the counts preview
        return counts

    # Perform deletions in an FK-safe order
    with transaction.atomic():
        for label, qs in groups:
            # Delete, but skip fixtures until we've removed their dependents above
            qs.delete()

    return counts