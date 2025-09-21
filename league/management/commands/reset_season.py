# league/management/commands/reset_season.py
from django.core.management.base import BaseCommand, CommandError
from league.models import Season
from league.services.reset_season import reset_season

class Command(BaseCommand):
    help = "Reset a season by clearing fixtures, lineups, scores, standings, etc."

    def add_arguments(self, parser):
        parser.add_argument("--season-id", type=int, help="Season ID to reset")
        parser.add_argument("--season-year", type=int, help="Season year (alternative to --season-id)")
        parser.add_argument("--dry-run", action="store_true", help="Preview what would be deleted (no changes)")
        parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    def handle(self, *args, **opts):
        sid = opts.get("season_id")
        syear = opts.get("season_year")
        if sid:
            qs = Season.objects.filter(pk=sid)
        elif syear:
            qs = Season.objects.filter(year=syear).order_by("-id")
        else:
            raise CommandError("Provide --season-id or --season-year")

        season = qs.first()
        if not season:
            raise CommandError("Season not found.")

        dry_run = opts.get("dry_run", False)

        self.stdout.write(self.style.NOTICE(
            f"{'Dry run for' if dry_run else 'About to reset'} season: {season} (id={season.id}, year={getattr(season, 'year', 'n/a')})"
        ))

        counts = reset_season(season, dry_run=True)  # always compute counts first

        # Pretty print counts
        width = max(len(k) for k in counts.keys())
        self.stdout.write("\nPlanned deletions:")
        for label, count in counts.items():
            self.stdout.write(f"  {label.ljust(width)} : {count}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("\nDry run complete. No changes made."))
            return

        if not opts.get("yes"):
            confirm = input("\nType 'RESET' to confirm deletion: ").strip()
            if confirm != "RESET":
                self.stdout.write(self.style.WARNING("Aborted. No changes made."))
                return

        # Real delete
        reset_season(season, dry_run=False)
        self.stdout.write(self.style.SUCCESS("Season reset complete."))