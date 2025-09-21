from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
import uuid


# Shared match day timeslot choices
TIMESLOT_CHOICES = (
    ("0830", "08:30"),
    ("1000", "10:00"),
    ("1130", "11:30"),
)

class Player(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='player_profile', null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    is_captain = models.BooleanField(default=False)
    is_substitute = models.BooleanField(default=False, help_text="Mark this record as the global external substitute.")
    invite_token = models.UUIDField(null=True, blank=True, editable=False, db_index=True)
    invite_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        if getattr(self, "is_substitute", False):
            return "Sub (External)"
        return f"{self.first_name} {self.last_name}"

    def issue_invite(self):
        self.invite_token = uuid.uuid4()
        self.invite_sent_at = timezone.now()
        self.save(update_fields=["invite_token", "invite_sent_at"])
        return str(self.invite_token)

class Season(models.Model):
    name = models.CharField(max_length=50, help_text="e.g., Summer 2026")
    year = models.PositiveIntegerField()
    is_active = models.BooleanField(default=False, help_text="Mark this as the current active season")
    roster_limit = models.PositiveIntegerField(default=22, help_text="Maximum players allowed on this season's roster")

    def __str__(self):
        return f"{self.name}"


# Per-season roster with NTRP and captaincy
class RosterEntry(models.Model):
    class NTRP(models.TextChoices):
        N30 = "3.0", "3.0"
        N35 = "3.5", "3.5"
        N40 = "4.0", "4.0"
        N45 = "4.5", "4.5"
        N50 = "5.0", "5.0"
        N55 = "5.5", "5.5"
        N60 = "6.0", "6.0"
        N65 = "6.5", "6.5"
        N70 = "7.0", "7.0"

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="roster_entries")
    player = models.ForeignKey('Player', on_delete=models.CASCADE, related_name="season_rosters")
    ntrp = models.CharField(max_length=3, choices=NTRP.choices)
    is_captain = models.BooleanField(default=False)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("season", "player")
        ordering = ["player__last_name", "player__first_name"]

    def __str__(self):
        return f"{self.player} — {self.season} ({self.ntrp})"

class Fixture(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="fixtures")
    date = models.DateTimeField()
    opponent = models.CharField(max_length=200)
    home = models.BooleanField(default=True)
    is_bye = models.BooleanField(default=False)
    week_number = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        where = "Home" if self.home else "Away"
        if self.is_bye:
            return f"Week {self.week_number}: BYE on {self.date.date()}"
        return f"Week {self.week_number}: {where} vs {self.opponent} on {self.date.date()}"

    def timeslot_code(self):
        """Return this fixture's canonical timeslot code (0830/1000/1130) based on LOCAL time.
        Picks the nearest slot by absolute minute distance.
        """
        dt = self.date
        # Normalize to local timezone for bucketing
        if timezone.is_aware(dt):
            dt_local = timezone.localtime(dt)
        else:
            dt_local = timezone.make_aware(dt, timezone.get_current_timezone())
        minutes = dt_local.hour * 60 + dt_local.minute
        candidates = [(8 * 60 + 30, "0830"), (10 * 60, "1000"), (11 * 60 + 30, "1130")]
        best = min(candidates, key=lambda x: abs(minutes - x[0]))
        return best[1]

class Availability(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "A", "Available"
        MAYBE = "M", "Maybe"
        UNAVAILABLE = "N", "Not Available"

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="availability")
    fixture = models.ForeignKey(Fixture, on_delete=models.CASCADE, related_name="availability")
    status = models.CharField(max_length=1, choices=Status.choices, default=Status.MAYBE)
    note = models.CharField(max_length=255, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("player", "fixture")

    def __str__(self):
        return f"{self.player} for {self.fixture}: {self.get_status_display()}"


# --- NEW: Per-timeslot sub availability toggle ---
class SubAvailability(models.Model):
    """Player indicates they are willing to sub at a specific timeslot for this fixture (week).
    Presence of a row means "ON"; absence means "OFF".
    """
    player = models.ForeignKey('Player', on_delete=models.CASCADE, related_name='sub_availability')
    fixture = models.ForeignKey('Fixture', on_delete=models.CASCADE, related_name='sub_availability')
    timeslot = models.CharField(max_length=4, choices=TIMESLOT_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("player", "fixture", "timeslot")
        ordering = ["fixture__date", "player__last_name", "player__first_name", "timeslot"]

    def __str__(self):
        return f"SubAvail: {self.player} · {self.fixture} · {dict(TIMESLOT_CHOICES).get(self.timeslot, self.timeslot)}"

class Lineup(models.Model):
    fixture = models.OneToOneField(Fixture, on_delete=models.CASCADE, related_name="lineup")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    published = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Lineup for {self.fixture}"

class LineupSlot(models.Model):
    class Slot(models.TextChoices):
        S1 = "S1", "Singles 1"
        S2 = "S2", "Singles 2"
        S3 = "S3", "Singles 3"
        D1 = "D1", "Doubles 1"
        D2 = "D2", "Doubles 2"
        D3 = "D3", "Doubles 3"

    lineup = models.ForeignKey(Lineup, on_delete=models.CASCADE, related_name="slots")
    slot = models.CharField(max_length=2, choices=Slot.choices)
    player1 = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, related_name="slot_player1")
    player2 = models.ForeignKey(Player, on_delete=models.SET_NULL, blank=True, null=True, related_name="slot_player2")

    class Meta:
        unique_together = ("lineup", "slot")

    def __str__(self):
        names = self.player1.__str__() if self.player1 else "TBD"
        if self.slot.startswith("D"):
            names += " / " + (self.player2.__str__() if self.player2 else "TBD")
        return f"{self.get_slot_display()}: {names}"


# --- SCORING AND POINTS MODELS ---

class SlotScore(models.Model):
    class Result(models.TextChoices):
        WIN = "W", "Win"
        LOSS = "L", "Loss"
        TIE = "T", "Tie"
        WIN_FF = "WF", "Win by forfeit"
        LOSS_FF = "LF", "Loss by forfeit"

    fixture = models.ForeignKey(Fixture, on_delete=models.CASCADE, related_name="slot_scores")
    # Slot codes align with LineupSlot.Slot choices (S1..S3, D1..D3)
    slot_code = models.CharField(max_length=2, choices=LineupSlot.Slot.choices)
    home_games = models.PositiveIntegerField(default=0)
    away_games = models.PositiveIntegerField(default=0)
    result = models.CharField(max_length=2, choices=Result.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("fixture", "slot_code")
        ordering = ["fixture__date", "slot_code"]

    def __str__(self):
        return f"{self.fixture} · {self.get_slot_code_display()} — {self.get_result_display()} ({self.home_games}-{self.away_games})"


class PlayerMatchPoints(models.Model):
    fixture = models.ForeignKey(Fixture, on_delete=models.CASCADE, related_name="player_points")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="match_points")
    # store halves cleanly (e.g., 0.5) using Decimal
    points = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("fixture", "player")
        ordering = ["fixture__date", "player__last_name", "player__first_name"]

    def __str__(self):
        return f"{self.player} — {self.fixture}: {self.points} pt(s)"

class SubPlan(models.Model):
    class Target(models.TextChoices):
        AGAINST_US = "AGAINST_US", "Against Us (opponent in this fixture)"
        OTHER_TEAM = "OTHER_TEAM", "Other Team"

    fixture = models.ForeignKey('Fixture', on_delete=models.CASCADE, related_name='sub_plans')
    player = models.ForeignKey('Player', on_delete=models.CASCADE, related_name='sub_plans')
    timeslot = models.CharField(max_length=4, choices=TIMESLOT_CHOICES)
    slot_code = models.CharField(max_length=2, choices=LineupSlot.Slot.choices)
    target_type = models.CharField(max_length=12, choices=Target.choices, default=Target.OTHER_TEAM)
    target_team_name = models.CharField(max_length=200, blank=True, help_text="Name of the team they will sub for")
    published = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("fixture", "player", "timeslot")
        ordering = ["fixture__date", "timeslot", "player__last_name", "player__first_name"]

    def clean(self):
        from django.core.exceptions import ValidationError
        # target_team_name required for OTHER_TEAM
        if self.target_type == self.Target.OTHER_TEAM and not self.target_team_name:
            raise ValidationError({"target_team_name": "Required for 'Other Team'"})
        # One-booking-per-timeslot rule within this fixture (week)
        # 1) Existing SubPlans at same timeslot
        conflict_plan = SubPlan.objects.filter(
            fixture=self.fixture,
            player=self.player,
            timeslot=self.timeslot,
        )
        if self.pk:
            conflict_plan = conflict_plan.exclude(pk=self.pk)
        if conflict_plan.exists():
            raise ValidationError("Player already has a sub plan at this timeslot for this week.")
        # 2) Existing SubResults at same timeslot
        if SubResult.objects.filter(fixture=self.fixture, player=self.player, timeslot=self.timeslot).exists():
            raise ValidationError("Player already has a recorded sub result at this timeslot for this week.")
        # 3) If lineup is published at THIS fixture's timeslot and the player is in it, block creating a plan at that same timeslot
        lineup = getattr(self.fixture, 'lineup', None)
        if lineup and lineup.published and self.timeslot == self.fixture.timeslot_code():
            in_lineup = lineup.slots.filter(models.Q(player1=self.player) | models.Q(player2=self.player)).exists()
            if in_lineup:
                raise ValidationError("Player is already booked in the published lineup at this timeslot.")

    def __str__(self):
        return f"Plan: {self.player} · {self.fixture} · {self.get_timeslot_display()} → {self.get_target_type_display()}"

    @property
    def subresult(self):
        """Convenience: return the first linked SubResult if present, else None.
        There should be at most one per (fixture, player, timeslot) by validation.
        """
        return self.results.first()

    @property
    def has_result(self):
        """True if a SubResult is linked to this plan."""
        return self.results.exists()

class SubResult(models.Model):
    class Kind(models.TextChoices):
        SINGLES = "S", "Singles"
        DOUBLES = "D", "Doubles"

    class Result(models.TextChoices):
        WIN = "W", "Win"
        LOSS = "L", "Loss"
        TIE = "T", "Tie"
        WIN_FF = "WF", "Win by forfeit"
        LOSS_FF = "LF", "Loss by forfeit"

    fixture = models.ForeignKey('Fixture', on_delete=models.CASCADE, related_name='sub_results')
    plan = models.ForeignKey('SubPlan', on_delete=models.SET_NULL, null=True, blank=True, related_name='results')
    player = models.ForeignKey('Player', on_delete=models.CASCADE, related_name='sub_results')
    date = models.DateField(blank=True, null=True)
    timeslot = models.CharField(max_length=4, choices=TIMESLOT_CHOICES)
    kind = models.CharField(max_length=1, choices=Kind.choices)
    slot_code = models.CharField(max_length=2, choices=LineupSlot.Slot.choices)
    target_type = models.CharField(max_length=12, choices=SubPlan.Target.choices)
    target_team_name = models.CharField(max_length=200)
    result = models.CharField(max_length=2, choices=Result.choices)
    home_games = models.PositiveIntegerField(default=0)
    away_games = models.PositiveIntegerField(default=0)
    points_cached = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fixture__date", "timeslot", "player__last_name", "player__first_name"]

    def clean(self):
        from django.core.exceptions import ValidationError
        # Enforce the one-booking-per-timeslot rule within this fixture (week)
        # 1) Other SubResults
        conflict_result = SubResult.objects.filter(
            fixture=self.fixture,
            player=self.player,
            timeslot=self.timeslot,
        )
        if self.pk:
            conflict_result = conflict_result.exclude(pk=self.pk)
        if conflict_result.exists():
            raise ValidationError("Player already has a sub result at this timeslot for this week.")
        # 2) SubPlans
        conflict_plan = SubPlan.objects.filter(fixture=self.fixture, player=self.player, timeslot=self.timeslot)
        # If linked to a plan, allow that same one
        if self.plan:
            conflict_plan = conflict_plan.exclude(pk=self.plan_id)
        if conflict_plan.exists():
            raise ValidationError("Player already has a sub plan at this timeslot for this week.")
        # 3) Published lineup at fixture's timeslot
        lineup = getattr(self.fixture, 'lineup', None)
        if lineup and lineup.published and self.timeslot == self.fixture.timeslot_code():
            in_lineup = lineup.slots.filter(models.Q(player1=self.player) | models.Q(player2=self.player)).exists()
            if in_lineup:
                raise ValidationError("Player is already booked in the published lineup at this timeslot.")

    def compute_points(self):
        # Singles: Win=2, Tie=1, Loss=0; Doubles: Win=1, Tie=0.5, Loss=0
        if self.result in (self.Result.WIN, self.Result.WIN_FF):
            return 2 if self.kind == self.Kind.SINGLES else 1
        if self.result == self.Result.TIE:
            return 1 if self.kind == self.Kind.SINGLES else 0.5
        return 0

    def save(self, *args, **kwargs):
        # Default date from fixture if missing
        if not self.date and self.fixture and self.fixture.date:
            self.date = self.fixture.date.date()
        self.points_cached = self.compute_points()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Sub: {self.player} · {self.fixture} · {self.get_timeslot_display()} — {self.get_result_display()} ({self.home_games}-{self.away_games})"

# --- Notifications core ---
class Notification(models.Model):
    class Event(models.TextChoices):
        LINEUP_OVERDUE = "LINEUP_OVERDUE", "Lineup overdue"
        SCORES_OVERDUE = "SCORES_OVERDUE", "Scores overdue"
        LINEUP_PUBLISHED_FOR_PLAYER = "LINEUP_PUBLISHED_FOR_PLAYER", "Lineup published (player)"
        SUBPLAN_CREATED_FOR_PLAYER = "SUBPLAN_CREATED_FOR_PLAYER", "Sub match created (player)"
        RESULT_POSTED_FOR_PLAYER = "RESULT_POSTED_FOR_PLAYER", "Result posted (player)"
        MATCH_REMINDER_24H = "MATCH_REMINDER_24H", "Match reminder (24h)"
        AVAILABILITY_REMINDER_5D = "AVAILABILITY_REMINDER_5D", "Availability reminder (5d)"

    event = models.CharField(max_length=64, choices=Event.choices)
    season = models.ForeignKey(Season, null=True, blank=True, on_delete=models.SET_NULL)
    fixture = models.ForeignKey(Fixture, null=True, blank=True, on_delete=models.SET_NULL)
    player = models.ForeignKey(Player, null=True, blank=True, on_delete=models.SET_NULL)  # for player-specific
    title = models.CharField(max_length=140)
    body = models.TextField(blank=True, default="")
    url = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # optional

    def __str__(self):
        return f"{self.get_event_display()} — {self.title}" if self.title else self.get_event_display()

    class Meta:
        indexes = [
            models.Index(fields=["event", "created_at"]),
        ]

class NotificationReceipt(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="receipts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_receipts")
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

# (For later SMS/email)

class DeliveryAttempt(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        SMS = "SMS", "SMS"
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=8, choices=Channel.choices)
    to = models.CharField(max_length=255)  # email or E.164 phone
    provider_message_id = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=32,
        choices=[("PENDING", "PENDING"), ("SENT", "SENT"), ("FAILED", "FAILED"), ("SUPPRESSED", "SUPPRESSED")],
        default="PENDING",
    )
    retry_count = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f"DeliveryAttempt({self.channel} → {self.to}, {self.status})"

    class Meta:
        indexes = [
            models.Index(fields=["channel", "status", "created_at"]),
            models.Index(fields=["notification", "created_at"]),
        ]


# --- Per-user notification preferences ---
class NotificationPreference(models.Model):
    """Per-user notification preferences for in-app (implicit), email, and SMS.
    In-app notifications are always created (via NotificationReceipt).
    Email/SMS are opt-in and controlled here per event.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs")

    # Global channel enables
    email_enabled = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=32, blank=True, default="")  # E.164 recommended
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    # --- Optional enhancements for SMS control ---
    timezone = models.CharField(max_length=64, default="America/New_York")
    sms_opt_in = models.BooleanField(default=False, help_text="User explicitly consented to receive SMS.")
    phone_e164 = models.CharField(max_length=20, blank=True, default="",
                                  help_text="Normalized E.164 phone (e.g., +13125551212)")
    share_email_with_team = models.BooleanField(default=False)
    share_mobile_with_team = models.BooleanField(default=False)

    @property
    def has_usable_phone(self) -> bool:
        """Whether SMS can be sent (enabled, consented, verified, and normalized phone present)."""
        return bool(
            getattr(self, "sms_enabled", False)
            and getattr(self, "sms_opt_in", False)
            and getattr(self, "phone_verified_at", None)
            and (self.phone_e164 or "").strip()
        )

    # Staff/admin events (email only by default)
    lineup_overdue_staff_email = models.BooleanField(default=False)
    scores_overdue_staff_email = models.BooleanField(default=False)

    # Player-facing events
    lineup_published_email = models.BooleanField(default=False)
    lineup_published_sms = models.BooleanField(default=False)

    subplan_created_email = models.BooleanField(default=False)
    subplan_created_sms = models.BooleanField(default=False)

    result_posted_email = models.BooleanField(default=False)
    result_posted_sms = models.BooleanField(default=False)

    match_reminder_24h_email = models.BooleanField(default=False)
    match_reminder_24h_sms = models.BooleanField(default=False)

    availability_reminder_5d_email = models.BooleanField(default=False)
    availability_reminder_5d_sms = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Prefs for {getattr(self.user, 'username', self.user_id)}"


from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_notification_prefs(sender, instance, created, **kwargs):
    if created:
        NotificationPreference.objects.get_or_create(user=instance)


# --- BEGIN PhoneVerification model ---
class PhoneVerification(models.Model):
    """One-time phone verification codes for SMS signup.
    We keep a short-lived record to validate ownership of the number.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="phone_verifications")
    phone_e164 = models.CharField(max_length=20)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "phone_e164", "created_at"]),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        # Auto-populate expires_at on first save if not provided
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def __str__(self):
        state = "used" if self.consumed_at else "active"
        return f"OTP for {self.phone_e164} ({state})"
# --- END PhoneVerification model ---


# --- Notifications core ---

@receiver(pre_save, sender=NotificationPreference)
def revoke_sms_on_phone_change(sender, instance: NotificationPreference, **kwargs):
    """If the normalized phone changes, revoke verification and consent flags.
    This forces the user to re-verify and re-consent when updating their number.
    """
    if not instance.pk:
        return
    try:
        prev = NotificationPreference.objects.get(pk=instance.pk)
    except NotificationPreference.DoesNotExist:
        return
    old = (prev.phone_e164 or "").strip()
    new = (instance.phone_e164 or "").strip()
    if old != new:
        # Clear verification/consent and disable SMS until re-verified
        instance.phone_verified_at = None
        instance.sms_opt_in = False
        instance.sms_enabled = False

# league/models.py
class LeagueStanding(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="standings")
    team_name = models.CharField(max_length=100)
    points = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    is_royals = models.BooleanField(default=False)  # our team row
    published = models.BooleanField(default=False)  # season-level flag (we’ll enforce via grouping)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = [("season", "team_name")]
        ordering = ["-points", "team_name"]

    def __str__(self):
        return f"{self.season} - {self.team_name} ({self.points})"