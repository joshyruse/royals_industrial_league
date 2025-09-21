from django.contrib import admin
from django.utils import timezone
from .models import Player, Season, RosterEntry, Fixture, Availability, Lineup, LineupSlot, SlotScore, PlayerMatchPoints, SubPlan, SubResult, SubAvailability, Notification, NotificationReceipt, DeliveryAttempt, NotificationPreference, PhoneVerification

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "is_captain")
    search_fields = ("first_name", "last_name", "email")


# Inline for roster entries under Season
class RosterEntryInline(admin.TabularInline):
    model = RosterEntry
    extra = 0
    autocomplete_fields = ("player",)
    fields = ("player", "ntrp", "is_captain", "added_at")
    readonly_fields = ("added_at",)

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "roster_limit")
    search_fields = ("name", "year")
    inlines = [RosterEntryInline]

class SlotScoreInline(admin.TabularInline):
    model = SlotScore
    extra = 0
    fields = ("slot_code", "home_games", "away_games", "result", "updated_at")
    readonly_fields = ("updated_at",)

@admin.register(Fixture)
class FixtureAdmin(admin.ModelAdmin):
    list_display = ("season", "week_number", "date", "opponent", "home", "is_bye")
    list_filter = ("season", "home", "is_bye")
    search_fields = ("opponent",)
    inlines = [SlotScoreInline]

@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ("player", "fixture", "status", "updated_at")
    list_filter = ("status", "fixture__season")

class LineupSlotInline(admin.TabularInline):
    model = LineupSlot
    extra = 6

@admin.register(Lineup)
class LineupAdmin(admin.ModelAdmin):
    list_display = ("fixture", "published")
    inlines = [LineupSlotInline]


# Standalone admin for RosterEntry
@admin.register(RosterEntry)
class RosterEntryAdmin(admin.ModelAdmin):
    list_display = ("season", "player", "ntrp", "is_captain", "added_at")
    list_filter = ("season", "ntrp", "is_captain")
    search_fields = ("player__first_name", "player__last_name", "player__email", "season__name", "season__year")
    autocomplete_fields = ("season", "player")

@admin.register(SlotScore)
class SlotScoreAdmin(admin.ModelAdmin):
    list_display = ("fixture", "slot_code", "result", "home_games", "away_games", "updated_at")
    list_filter = ("result", "slot_code", "fixture__season")
    search_fields = ("fixture__opponent",)
    autocomplete_fields = ("fixture",)

@admin.register(PlayerMatchPoints)
class PlayerMatchPointsAdmin(admin.ModelAdmin):
    list_display = ("fixture", "player", "points", "updated_at")
    list_filter = ("fixture__season",)
    search_fields = ("player__first_name", "player__last_name", "fixture__opponent")
    autocomplete_fields = ("fixture", "player")


# Admin for SubPlan
@admin.register(SubPlan)
class SubPlanAdmin(admin.ModelAdmin):
    list_display = ("fixture", "player", "timeslot", "slot_code", "target_type", "target_team_name", "published", "updated_at")
    list_filter = ("target_type", "published", "timeslot", "fixture__season")
    search_fields = ("player__first_name", "player__last_name", "target_team_name", "fixture__opponent")
    autocomplete_fields = ("fixture", "player")


# Admin for SubResult
@admin.register(SubResult)
class SubResultAdmin(admin.ModelAdmin):
    list_display = ("fixture", "player", "timeslot", "kind", "slot_code", "target_team_name", "result", "points_cached", "updated_at")
    list_filter = ("result", "kind", "timeslot", "fixture__season")
    search_fields = ("player__first_name", "player__last_name", "target_team_name", "fixture__opponent")
    autocomplete_fields = ("fixture", "player", "plan")


# Admin for SubAvailability
@admin.register(SubAvailability)
class SubAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("fixture", "player", "timeslot", "created_at")
    list_filter = ("timeslot", "fixture__season")
    search_fields = ("player__first_name", "player__last_name", "fixture__opponent")
    autocomplete_fields = ("fixture", "player")

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "event", "season", "fixture", "player", "title", "created_at")
    list_filter = ("event", "season")
    search_fields = ("title", "body")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.action(description="Mark selected as read")
def mark_receipts_read(modeladmin, request, queryset):
    queryset.filter(read_at__isnull=True).update(read_at=timezone.now())


@admin.action(description="Mark selected as unread")
def mark_receipts_unread(modeladmin, request, queryset):
    queryset.update(read_at=None)


@admin.register(NotificationReceipt)
class NotificationReceiptAdmin(admin.ModelAdmin):
    list_display = ("id", "notification", "user", "read_at", "created_at")
    list_filter = ("read_at",)
    search_fields = ("notification__title", "user__username", "user__email")
    date_hierarchy = "created_at"
    actions = (mark_receipts_read, mark_receipts_unread)
    ordering = ("-created_at",)


@admin.register(DeliveryAttempt)
class DeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "notification", "channel", "to", "status", "retry_count", "provider_message_id", "sent_at", "created_at")
    list_filter = ("channel", "status")
    readonly_fields = ("error",)
    search_fields = ("to", "provider_message_id", "notification__title")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

@admin.register(PhoneVerification)
class PhoneVerificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "phone_e164", "code", "attempts", "created_at", "expires_at", "consumed_at")
    list_filter = ("consumed_at",)
    search_fields = ("user__username", "user__email", "phone_e164")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "consumed_at")
    ordering = ("-created_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user", "email_enabled", "sms_enabled", "sms_opt_in",
        "phone_number", "phone_e164", "has_verified_phone", "has_usable_phone",
        "timezone", "share_email_with_team", "share_mobile_with_team", "lineup_published_sms",
        "subplan_created_email", "subplan_created_sms",
        "result_posted_email", "result_posted_sms",
        "match_reminder_24h_email", "match_reminder_24h_sms",
        "availability_reminder_5d_email", "availability_reminder_5d_sms",
        "updated_at",
    )
    list_filter = (
        "email_enabled", "sms_enabled", "sms_opt_in",
        "lineup_published_email", "lineup_published_sms",
        "subplan_created_email", "subplan_created_sms",
        "result_posted_email", "result_posted_sms",
        "match_reminder_24h_email", "match_reminder_24h_sms",
        "availability_reminder_5d_email", "availability_reminder_5d_sms",
        "timezone",
    )
    search_fields = ("user__username", "user__email", "phone_number", "phone_e164")
    autocomplete_fields = ("user",)
    ordering = ("-updated_at",)

    @admin.display(boolean=True, description="Phone verified")
    def has_verified_phone(self, obj):
        return bool(getattr(obj, "phone_verified_at", None))

    @admin.display(boolean=True, description="Usable phone")
    def has_usable_phone(self, obj):
        # uses model property if present; falls back to basic check
        val = getattr(obj, "has_usable_phone", None)
        if callable(val):
            try:
                return bool(val())
            except TypeError:
                pass
        return bool(getattr(obj, "sms_enabled", False) and getattr(obj, "sms_opt_in", False) and getattr(obj, "phone_verified_at", None) and (getattr(obj, "phone_e164", "") or getattr(obj, "phone_number", "")).strip())
