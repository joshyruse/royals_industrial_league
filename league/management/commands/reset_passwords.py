from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Reset all user passwords to 'changeme123' (for dev/test only)."

    def handle(self, *args, **options):
        # Safety guard: only run in DEBUG mode
        if not settings.DEBUG:
            raise CommandError("This command can only be run when DEBUG=True")

        # Clear Axes lockouts if django-axes is installed in this settings module
        if "axes" in settings.INSTALLED_APPS:
            try:
                from axes.helpers import reset
                reset(ip=None, username=None)
                self.stdout.write(self.style.SUCCESS("✅ Cleared Axes lockouts"))
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"⚠️  Axes reset skipped: {e}"))
        else:
            self.stdout.write("(axes not in INSTALLED_APPS for this settings; skipping lockout reset)")

        User = get_user_model()
        users = User.objects.exclude(username="joshyruse")
        for user in users:
            user.set_password("changeme123")
            user.save()

        self.stdout.write(
            self.style.SUCCESS(f"✅ Reset {users.count()} user passwords to 'changeme123' (skipped 'joshyruse')")
        )

        # Clear Axes lockouts if installed
        if reset:
            reset(ip=None, username=None)
            self.stdout.write(self.style.SUCCESS("✅ Cleared Axes lockouts"))