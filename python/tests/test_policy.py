import datetime as dt

from plasmon.coordinator import policy
from plasmon.coordinator.config import OrgPolicy, Window


def test_window_crossing_midnight():
    w = Window(days=["mon", "tue", "wed", "thu", "fri"], start="19:00", end="08:00")
    monday_evening = dt.datetime(2026, 10, 5, 20, 0)  # a Monday
    tuesday_early = dt.datetime(2026, 10, 6, 7, 30)
    tuesday_noon = dt.datetime(2026, 10, 6, 12, 0)
    saturday_early = dt.datetime(2026, 10, 10, 7, 30)  # Friday night runs into Saturday morning
    sunday_evening = dt.datetime(2026, 10, 11, 21, 0)
    assert policy.window_open(w, monday_evening)
    assert policy.window_open(w, tuesday_early)
    assert not policy.window_open(w, tuesday_noon)
    assert policy.window_open(w, saturday_early)
    assert not policy.window_open(w, sunday_evening)


def test_available_and_parse():
    always = OrgPolicy()
    assert policy.available(always) == (True, "")
    pol = OrgPolicy(windows=[policy.parse_hours("weekdays 19:00-08:00"), policy.parse_hours("weekends 00:00-23:59")])
    ok, why = policy.available(pol, dt.datetime(2026, 10, 6, 12, 0))
    assert not ok and "outside window" in why
    assert policy.available(pol, dt.datetime(2026, 10, 10, 15, 0))[0]  # Saturday afternoon
    assert policy.parse_hours("mon,wed 20:00-07:00").days == ["mon", "wed"]
    assert policy.parse_hours("22:00-06:00").days == list(policy.DAYS)
