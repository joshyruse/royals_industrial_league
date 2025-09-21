# tests/test_season_reset_clone.py
import pytest
from decimal import Decimal
from django.urls import reverse
from django.utils import timezone

from league.models import (
    Season, Player, RosterEntry, Fixture,
    Lineup, LineupSlot, SlotScore,
    Availability, SubAvailability,
    SubPlan, SubResult,
    PlayerMatchPoints, LeagueStanding
)

@pytest.fixture
def admin_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="admin", email="a@a.co", password="pass", is_staff=True
    )
    return user

@pytest.fixture
def two_players(django_user_model):
    u1 = django_user_model.objects.create_user(username="p1", password="x")
    u2 = django_user_model.objects.create_user(username="p2", password="x")
    p1 = Player.objects.create(user=u1, first_name="Al", last_name="Alpha", email="p1@x.com")
    p2 = Player.objects.create(user=u2, first_name="Bea", last_name="Beta", email="p2@x.com")
    return p1, p2

@pytest.fixture
def active_season(two_players, admin_user):
    p1, p2 = two_players
    season = Season.objects.create(name="Spring", year=timezone.now().year, is_active=True)
    RosterEntry.objects.create(season=season, player=p1)
    RosterEntry.objects.create(season=season, player=p2)

    fx = Fixture.objects.create(season=season, opponent="Sharks", date=timezone.now(), week_number=1)
    ln = Lineup.objects.create(fixture=fx, published=True, created_by=admin_user)
    LineupSlot.objects.create(lineup=ln, slot="S1", player1=p1)
    LineupSlot.objects.create(lineup=ln, slot="D1", player1=p1, player2=p2)

    SlotScore.objects.create(fixture=fx, slot_code="S1", result=SlotScore.Result.WIN, home_games=6, away_games=2)
    SlotScore.objects.create(fixture=fx, slot_code="D1", result=SlotScore.Result.LOSS, home_games=4, away_games=6)

    Availability.objects.create(fixture=fx, player=p1, status="A")
    SubAvailability.objects.create(fixture=fx, player=p2, timeslot="1000")

    SubPlan.objects.create(fixture=fx, player=p2, timeslot="1000", slot_code="D1",
                           target_type=SubPlan.Target.OTHER_TEAM, target_team_name="Lions")
    SubResult.objects.create(fixture=fx, player=p2, timeslot="1000", slot_code="D1",
                             result=SlotScore.Result.WIN, points_cached=Decimal("1.50"))

    PlayerMatchPoints.objects.create(fixture=fx, player=p1, points=Decimal("2.0"))

    LeagueStanding.objects.create(season=season, team_name="Royals", is_royals=True,
                                  points=Decimal("3.50"), published=False, updated_by=admin_user)
    LeagueStanding.objects.create(season=season, team_name="Sharks", is_royals=False,
                                  points=Decimal("2.00"), published=False, updated_by=admin_user)
    return season

def clone_active_to_reset_season(active: Season) -> Season:
    reset = Season.objects.create(
        name="RESET SEASON",
        year=getattr(active, "year", timezone.now().year),
        is_active=False
    )
    for re in RosterEntry.objects.filter(season=active):
        RosterEntry.objects.create(season=reset, player=re.player, is_captain=getattr(re, "is_captain", False))

    fx_map = {}
    for fx in Fixture.objects.filter(season=active).order_by("date"):
        fx2 = Fixture.objects.create(
            season=reset, opponent=fx.opponent, date=fx.date,
            week_number=getattr(fx, "week_number", None), home=getattr(fx, "home", False),
            is_bye=getattr(fx, "is_bye", False),
        )
        fx_map[fx.id] = fx2

    for ln in Lineup.objects.filter(fixture__season=active):
        ln2 = Lineup.objects.create(fixture=fx_map[ln.fixture_id], published=ln.published, created_by=ln.created_by)
        for ls in LineupSlot.objects.filter(lineup=ln):
            LineupSlot.objects.create(lineup=ln2, slot=ls.slot, player1=ls.player1, player2=ls.player2)

    for sc in SlotScore.objects.filter(fixture__season=active):
        SlotScore.objects.create(fixture=fx_map[sc.fixture_id], slot_code=sc.slot_code,
                                 result=sc.result, home_games=sc.home_games, away_games=sc.away_games)

    for av in Availability.objects.filter(fixture__season=active):
        Availability.objects.create(fixture=fx_map[av.fixture_id], player=av.player, status=av.status)

    for sa in SubAvailability.objects.filter(fixture__season=active):
        SubAvailability.objects.create(fixture=fx_map[sa.fixture_id], player=sa.player, timeslot=sa.timeslot)

    from django.forms.models import model_to_dict
    # Create SubPlan using only fields that exist on the model to avoid unexpected kwargs
    plan_field_names = {f.name for f in SubPlan._meta.get_fields()}
    for sp in SubPlan.objects.filter(fixture__season=active):
        data = {
            "fixture": fx_map[sp.fixture_id],
            "player": sp.player,
            "timeslot": getattr(sp, "timeslot", None),
            "slot_code": getattr(sp, "slot_code", None),
            "target_type": getattr(sp, "target_type", None),
            "target_team_name": getattr(sp, "target_team_name", ""),
            "notes": getattr(sp, "notes", ""),
            "published": getattr(sp, "published", False),
        }
        # Keep only keys that are valid model fields
        data = {k: v for k, v in data.items() if k in plan_field_names}
        SubPlan.objects.create(**data)

    for sr in SubResult.objects.filter(fixture__season=active):
        SubResult.objects.create(
            fixture=fx_map[sr.fixture_id], player=sr.player, timeslot=sr.timeslot, slot_code=sr.slot_code,
            result=sr.result, points_cached=sr.points_cached,
            target_type=getattr(sr, "target_type", None), target_team_name=getattr(sr, "target_team_name", ""),
            plan=getattr(sr, "plan", None),
        )

    for pmp in PlayerMatchPoints.objects.filter(fixture__season=active):
        PlayerMatchPoints.objects.create(fixture=fx_map[pmp.fixture_id], player=pmp.player, points=pmp.points)

    for st in LeagueStanding.objects.filter(season=active):
        LeagueStanding.objects.create(season=reset, team_name=st.team_name, is_royals=st.is_royals,
                                      points=st.points, published=st.published, updated_by=st.updated_by)
    return reset

@pytest.mark.django_db
def test_clone_then_reset_active_season(client, admin_user, active_season):
    # Log in as admin
    client.login(username="admin", password="pass")

    # 1) Clone
    reset = clone_active_to_reset_season(active_season)
    assert reset.name == "RESET SEASON"
    assert Fixture.objects.filter(season=reset).exists()
    assert Lineup.objects.filter(fixture__season=reset).exists()
    assert SlotScore.objects.filter(fixture__season=reset).exists()
    assert LeagueStanding.objects.filter(season=reset).exists()

    # 2) Reset original
    resp = client.post(reverse("admin_dashboard"), {
        "action": "reset_season",
        "season_id": str(active_season.id),
    }, follow=False)
    assert resp.status_code in (302, 303)

    # 3) Original wiped
    assert not Fixture.objects.filter(season=active_season).exists()
    assert not Lineup.objects.filter(fixture__season=active_season).exists()
    assert not LineupSlot.objects.filter(lineup__fixture__season=active_season).exists()
    assert not SlotScore.objects.filter(fixture__season=active_season).exists()
    assert not SubPlan.objects.filter(fixture__season=active_season).exists()
    assert not SubResult.objects.filter(fixture__season=active_season).exists()
    assert not Availability.objects.filter(fixture__season=active_season).exists()
    assert not SubAvailability.objects.filter(fixture__season=active_season).exists()
    assert not PlayerMatchPoints.objects.filter(fixture__season=active_season).exists()
    assert not LeagueStanding.objects.filter(season=active_season).exists()

    # Roster & players preserved
    assert RosterEntry.objects.filter(season=active_season).count() == 2
    assert Player.objects.count() >= 2

    # 4) Clone intact
    assert Fixture.objects.filter(season=reset).exists()
    assert Lineup.objects.filter(fixture__season=reset).exists()
    assert SlotScore.objects.filter(fixture__season=reset).exists()
    assert LeagueStanding.objects.filter(season=reset).exists()
@pytest.mark.django_db
def test_reset_season_button_renders_and_posts(client, admin_user, active_season):
    """Smoke test: the Reset Season button/modal is present and posting it performs a reset.
    This does NOT click a real browser modal; it verifies the markup and the POST endpoint.
    """
    # Log in as admin
    client.login(username="admin", password="pass")

    # GET admin dashboard – button & modal markup should be present
    resp = client.get(reverse("admin_dashboard"))
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    # Button present with correct target modal
    assert "Reset Season" in html
    assert 'data-bs-target="#confirmResetSeason"' in html
    assert 'id="confirmResetSeason"' in html  # modal exists on the page

    # Ensure we have some season-scoped data prior to reset
    assert Fixture.objects.filter(season=active_season).exists()

    # POST the reset form (simulate confirming the modal)
    resp2 = client.post(reverse("admin_dashboard"), {
        "action": "reset_season",
        "season_id": str(active_season.id),
    }, follow=False)
    assert resp2.status_code in (302, 303)

    # After reset, season-scoped data should be cleared
    assert not Fixture.objects.filter(season=active_season).exists()
    assert not Lineup.objects.filter(fixture__season=active_season).exists()
    assert not SlotScore.objects.filter(fixture__season=active_season).exists()
    assert not LeagueStanding.objects.filter(season=active_season).exists()

    # Roster preserved
    assert RosterEntry.objects.filter(season=active_season).count() == 2