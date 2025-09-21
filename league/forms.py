from django import forms
from django.forms import BaseInlineFormSet
from django.db.models import Q
from .models import Availability, Lineup, LineupSlot, Player, Fixture, SubPlan, SubResult, TIMESLOT_CHOICES, NotificationPreference, LeagueStanding
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.forms import modelformset_factory


UserModel = get_user_model()

class InvitePlayerForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name  = forms.CharField(max_length=150)
    email      = forms.EmailField()
    make_captain = forms.BooleanField(required=False, initial=False)

class AvailabilityForm(forms.ModelForm):
    # Limit choices to Available / Not Available only
    status = forms.ChoiceField(
        choices=[
            (Availability.Status.AVAILABLE, "Available"),
            (Availability.Status.UNAVAILABLE, "Not Available"),
        ],
        widget=forms.Select(attrs={"class":"form-select"}),
    )

    class Meta:
        model = Availability
        fields = ["status", "note"]
        widgets = {
            "note": forms.TextInput(attrs={"class":"form-control", "placeholder": "Optional note"}),
        }

class FixtureForm(forms.ModelForm):
    class Meta:
        model = Fixture
        fields = ["week_number", "date", "opponent", "home", "is_bye"]
        widgets = {
            "week_number": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "date": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "opponent": forms.TextInput(attrs={"class": "form-control"}),
            "home": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_bye": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        # Accept optional 'season' for validation
        self._season = kwargs.pop("season", None)
        super().__init__(*args, **kwargs)
        if not self._season and getattr(self.instance, "season_id", None):
            self._season = self.instance.season

    def clean(self):
        cleaned = super().clean()
        week = cleaned.get("week_number")
        season = self._season
        is_bye = cleaned.get("is_bye")

        # Per-season unique week number
        if week and season:
            qs = Fixture.objects.filter(season=season, week_number=week)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError({"week_number": "Another match already uses this week number for the selected season."})

        # Opponent required unless it's a bye week
        opponent = (cleaned.get("opponent") or "").strip()
        if not is_bye and not opponent:
            self.add_error("opponent", "Opponent is required for non-bye matches.")
        else:
            # Normalize empty opponent for bye weeks
            if is_bye and not opponent:
                cleaned["opponent"] = ""

        return cleaned

class LineupForm(forms.ModelForm):
    class Meta:
        model = Lineup
        fields = ["published", "notes"]
        widgets = {
            "published": forms.CheckboxInput(attrs={"class":"form-check-input"}),
            "notes": forms.Textarea(attrs={"class":"form-control", "rows":3}),
        }


# SubPlanForm
class SubPlanForm(forms.ModelForm):
    class Meta:
        model = SubPlan
        fields = [
            "player",
            "timeslot",
            "slot_code",
            "target_type",
            "target_team_name",
            "published",
            "notes",
        ]
        widgets = {
            "player": forms.Select(attrs={"class": "form-select"}),
            "timeslot": forms.Select(choices=TIMESLOT_CHOICES, attrs={"class": "form-select"}),
            "slot_code": forms.Select(attrs={"class": "form-select"}),
            "target_type": forms.Select(attrs={"class": "form-select"}),
            "target_team_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Falcons"}),
            "published": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self._fixture = kwargs.pop("fixture", None)
        super().__init__(*args, **kwargs)
        # If a fixture is provided, set it on the instance and restrict player choices to the season roster
        if self._fixture:
            if not getattr(self.instance, "fixture_id", None):
                self.instance.fixture = self._fixture
            season = getattr(self._fixture, "season", None)
            if season:
                self.fields["player"].queryset = Player.objects.filter(season_rosters__season=season).distinct().order_by("last_name", "first_name")
        # If target_type is AGAINST_US, hint that team name will be this fixture's opponent
        # (UI can disable via JS; here we just leave it editable)

    def clean(self):
        cleaned = super().clean()
        # Ensure fixture is present for model.clean() logic
        if not getattr(self.instance, "fixture_id", None) and self._fixture:
            self.instance.fixture = self._fixture
        return cleaned


# SubResultForm
class SubResultForm(forms.ModelForm):
    class Meta:
        model = SubResult
        fields = [
            "player",
            "timeslot",
            "kind",
            "slot_code",
            "target_type",
            "target_team_name",
            "result",
            "home_games",
            "away_games",
            "notes",
        ]
        widgets = {
            "player": forms.Select(attrs={"class": "form-select"}),
            "timeslot": forms.Select(choices=TIMESLOT_CHOICES, attrs={"class": "form-select"}),
            "kind": forms.Select(attrs={"class": "form-select"}),
            "slot_code": forms.Select(attrs={"class": "form-select"}),
            "target_type": forms.Select(attrs={"class": "form-select"}),
            "target_team_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Falcons"}),
            "result": forms.Select(attrs={"class": "form-select"}),
            "home_games": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "away_games": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self._fixture = kwargs.pop("fixture", None)
        super().__init__(*args, **kwargs)
        if self._fixture:
            if not getattr(self.instance, "fixture_id", None):
                self.instance.fixture = self._fixture
            season = getattr(self._fixture, "season", None)
            if season:
                self.fields["player"].queryset = Player.objects.filter(season_rosters__season=season).distinct().order_by("last_name", "first_name")

    def clean(self):
        cleaned = super().clean()
        # Ensure fixture is present for model.clean() logic
        if not getattr(self.instance, "fixture_id", None) and self._fixture:
            self.instance.fixture = self._fixture
        # Keep kind in sync with slot_code if provided (S* => Singles, D* => Doubles)
        slot_code = cleaned.get("slot_code")
        if slot_code:
            if str(slot_code).startswith("S"):
                cleaned["kind"] = SubResult.Kind.SINGLES
            elif str(slot_code).startswith("D"):
                cleaned["kind"] = SubResult.Kind.DOUBLES
        return cleaned

class LineupSlotForm(forms.ModelForm):
    class Meta:
        model = LineupSlot
        fields = ["slot", "player1", "player2"]
        widgets = {
            "slot": forms.Select(attrs={"class":"form-select"}),
            "player1": forms.Select(attrs={"class":"form-select"}),
            "player2": forms.Select(attrs={"class":"form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Don’t allow changing which slot this row represents
        self.fields["slot"].disabled = True
        # Allow partial saves; strict rules enforced in clean()
        self.fields["player1"].required = False
        self.fields["player2"].required = False
        # Limit selectable players to those Available for this lineup's fixture
        lineup = getattr(self.instance, "lineup", None)
        if lineup and lineup.fixture_id:
            qs = (
                Player.objects.filter(
                    Q(availability__fixture=lineup.fixture, availability__status=Availability.Status.AVAILABLE)
                    | Q(is_substitute=True)
                )
                .distinct()
                .order_by("last_name", "first_name")
            )
            self.fields["player1"].queryset = qs
            if "player2" in self.fields:
                self.fields["player2"].queryset = qs
        # Hide Player 2 field entirely for Singles rows
        if self.instance.slot and self.instance.slot.startswith("S"):
            self.fields.pop("player2")

    def clean(self):
        cleaned = super().clean()
        slot = (self.instance.slot or cleaned.get("slot"))
        p1 = cleaned.get("player1")
        p2 = cleaned.get("player2")

        if slot:
            if slot.startswith("S"):
                # Singles: must have exactly one player
                if not p1:
                    self.add_error("player1", "Singles slots must have one player assigned.")
                # And must NOT have a second player (UI hides it, but guard anyway)
                if p2:
                    self.add_error("player2", "Singles slots must have only one player.")
            elif slot.startswith("D"):
                # Doubles: must have exactly two (and different) players
                if not p1 or not p2:
                    self.add_error(None, "Doubles slots must have exactly two players.")
                else:
                    same_person = (p1 == p2)
                    both_subs = bool(getattr(p1, "is_substitute", False) and getattr(p2, "is_substitute", False))
                    if same_person and not both_subs:
                        self.add_error("player2", "Doubles partners must be two different players (unless both are marked as Sub).")
        return cleaned


# Prevent the same player appearing in multiple slots
class BaseLineupSlotFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        # If any per-form errors exist already, let those surface and skip global checks
        if any(self.errors):
            return

        used = {}  # player_id -> slot label (e.g., "Singles 1", "Doubles 2")

        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue

            # Determine a human-friendly slot label if available
            try:
                slot_label = form.instance.get_slot_display()
            except Exception:
                slot_label = form.cleaned_data.get("slot") or getattr(form.instance, "slot", "?")

            p1 = form.cleaned_data.get("player1")
            p2 = form.cleaned_data.get("player2")

            for field_name, p in (("player1", p1), ("player2", p2)):
                if not p:
                    continue
                # Ignore the global Sub (External) when checking duplicates
                if getattr(p, "is_substitute", False):
                    continue
                pid = getattr(p, "id", getattr(p, "pk", None))
                if pid is None:
                    continue
                if pid in used:
                    other_slot = used[pid]
                    form.add_error(field_name, f"{p} appears in {other_slot} and {slot_label}.")
                else:
                    used[pid] = slot_label

        # If we added errors to forms above, Django will surface them; no need to raise here.


class UsernameForm(forms.ModelForm):
    class Meta:
        model = UserModel
        fields = ["username"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control", "autocomplete": "username"}),
        }

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            raise forms.ValidationError("Username is required.")
        qs = UserModel.objects.exclude(pk=self.instance.pk).filter(username__iexact=username)
        if qs.exists():
            raise forms.ValidationError("That username is already taken.")
        return username

# Styled password change form using Bootstrap classes
class StyledPasswordChangeForm(PasswordChangeForm):
    """Password change form with Bootstrap styling on inputs."""
    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["old_password"].widget.attrs.update({
            "class": "form-control",
            "autocomplete": "current-password",
        })
        self.fields["new_password1"].widget.attrs.update({
            "class": "form-control",
            "autocomplete": "new-password",
        })
        self.fields["new_password2"].widget.attrs.update({
            "class": "form-control",
            "autocomplete": "new-password",
        })

class PlayerForm(forms.ModelForm):
    class Meta:
        model = Player
        fields = ["first_name", "last_name", "email",]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
        }

class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = [
            "email_enabled", "sms_enabled",
            "lineup_overdue_staff_email", "scores_overdue_staff_email",
            "lineup_published_email", "lineup_published_sms",
            "subplan_created_email", "subplan_created_sms",
            "result_posted_email", "result_posted_sms",
            "match_reminder_24h_email", "match_reminder_24h_sms",
            "availability_reminder_5d_email", "availability_reminder_5d_sms",
        ]
        widgets = {
            "email_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "sms_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "lineup_overdue_staff_email": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "scores_overdue_staff_email": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "lineup_published_email": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "lineup_published_sms": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "subplan_created_email": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "subplan_created_sms": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "result_posted_email": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "result_posted_sms": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "match_reminder_24h_email": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "match_reminder_24h_sms": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "availability_reminder_5d_email": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "availability_reminder_5d_sms": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        pref = self.instance
        verified = bool(getattr(pref, "phone_verified_at", None))
        consented = bool(getattr(pref, "sms_opt_in", False))
        needs_lock = not (verified and consented)
        if "sms_enabled" in self.fields:
            if needs_lock:
                # Disable toggle until verified + consent
                self.fields["sms_enabled"].disabled = True
                self.fields["sms_enabled"].widget.attrs["disabled"] = "disabled"
                self.fields["sms_enabled"].help_text = (
                    "Verify your phone and check the consent box in the modal to enable SMS."
                )
            else:
                self.fields["sms_enabled"].help_text = "SMS notifications will be sent to your verified number."

    def clean_sms_enabled(self):
        val = self.cleaned_data.get("sms_enabled")
        pref = self.instance
        verified = bool(getattr(pref, "phone_verified_at", None))
        consented = bool(getattr(pref, "sms_opt_in", False))
        if val and not (verified and consented):
            raise forms.ValidationError(
                "You must verify your phone and consent to SMS before enabling."
            )
        return val

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("sms_enabled"):
            pref = self.instance
            has_number = bool((getattr(pref, "phone_e164", "") or "").strip())
            verified = bool(getattr(pref, "phone_verified_at", None))
            consented = bool(getattr(pref, "sms_opt_in", False))
            if not (has_number and verified and consented):
                self.add_error(None, "To enable SMS, verify your phone and give consent using the Verify button above.")
        return cleaned

LineupSlotFormSet = forms.inlineformset_factory(
    Lineup,
    LineupSlot,
    form=LineupSlotForm,
    formset=BaseLineupSlotFormSet,
    extra=0,
    can_delete=False,
    max_num=6,
    validate_max=True,
)
class ShareContactPrefsForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = ["share_email_with_team", "share_mobile_with_team"]
        widgets = {
            "share_email_with_team": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "share_mobile_with_team": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

# league/forms.py
class LeagueStandingForm(forms.ModelForm):
    class Meta:
        model = LeagueStanding
        fields = ["team_name", "points"]
        widgets = {
            "team_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Team name"}),
            "points": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
        }

LeagueStandingFormSet = modelformset_factory(
    LeagueStanding,
    form=LeagueStandingForm,
    extra=0,
    can_delete=False
)