from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from league.models import Player, Season, Fixture
from datetime import timedelta

FIRST_NAMES = ["Alex","Blake","Casey","Drew","Elliot","Finley","Gray","Hayden","Indie","Jules","Kai","Logan","Morgan","Noa","Oakley","Parker","Quinn","Riley","Sage","Taylor","Vale"]
LAST_NAMES = ["Smith","Johnson","Lee","Brown","Davis","Miller","Wilson","Moore","Taylor","Anderson","Thomas","Jackson","White","Harris","Martin","Thompson","Garcia","Martinez","Robinson","Clark","Lewis"]

class Command(BaseCommand):
    help = "Seeds demo data: 21 players, a Season, and 6 future fixtures."

    def handle(self, *args, **options):
        if not User.objects.filter(username="captain").exists():
            u = User.objects.create_user("captain", password="changeme123", email="captain@example.com")
            u.is_staff = True
            u.save()
            self.stdout.write(self.style.SUCCESS("Created user 'captain' with password 'changeme123' (CHANGE IT)"))

        players = []
        for i in range(21):
            fn, ln = FIRST_NAMES[i], LAST_NAMES[i]
            email = f"{fn.lower()}.{ln.lower()}@example.com"
            username = f"{fn.lower()}{i}"
            user, _ = User.objects.get_or_create(username=username, defaults={"email": email, "first_name": fn, "last_name": ln})
            user.set_password("changeme123")
            user.save()
            p, _ = Player.objects.get_or_create(first_name=fn, last_name=ln, defaults={"email": email, "user": user})
            if not p.user:
                p.user = user
                p.save()
            players.append(p)

        first = players[0]
        first.is_captain = True
        first.save()

        now = timezone.now()
        season, _ = Season.objects.get_or_create(name=f"Summer {now.year}", year=now.year)

        for w in range(1, 7):
            date = now + timedelta(days=7*w)
            home = (w % 2 == 1)
            opp = f"Rivals {w}"
            Fixture.objects.get_or_create(season=season, week_number=w, defaults={"date": date, "home": home, "opponent": opp})

        self.stdout.write(self.style.SUCCESS("Seeded demo players and fixtures."))
