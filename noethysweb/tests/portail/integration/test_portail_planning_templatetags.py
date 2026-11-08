"""Unit tests for portail/templatetags/planning.py (filters is_modif_allowed, rangelistfrom0/1)."""

import datetime
from types import SimpleNamespace

import pytest
from django.template import Context, Template
from portail.templatetags import planning as planning_tags
from portail.templatetags.planning import (
    is_modif_allowed,
    rangelistfrom0,
    rangelistfrom1,
)

# 2024-05-15 is a Wednesday. "now" is frozen at 12:00 on that day (freezegun is not a project
# dependency, so the `datetime` module used by the templatetag is swapped for a fake).
NOW = datetime.datetime(2024, 5, 15, 12, 0)


def freeze(monkeypatch, now):
    class FakeDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    fake = SimpleNamespace(
        datetime=FakeDatetime, timedelta=datetime.timedelta, date=datetime.date
    )
    monkeypatch.setattr(planning_tags, "datetime", fake)


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    freeze(monkeypatch, NOW)


HOLIDAY = SimpleNamespace(type="fixe", jour=1, mois=5, annee=0)  # 1st of May


def make_data(limite=None, mode="portail", consultation=None, feries=()):
    data = {
        "mode": mode,
        "selection_activite": SimpleNamespace(portail_reservations_limite=limite),
        "liste_feries": list(feries),
    }
    if consultation is not None:
        data["periode_reservation"] = SimpleNamespace(mode_consultation=consultation)
    return data


class TestRange:
    def test_rangelistfrom0(self):
        assert list(rangelistfrom0(3)) == [0, 1, 2]

    def test_rangelistfrom1(self):
        assert list(rangelistfrom1(3)) == [1, 2, 3]

    def test_filters_registered_in_templates(self):
        out = Template("{% for i in n|rangelistfrom1 %}{{ i }}{% endfor %}").render(
            Context({"n": 3})
        )
        assert out == "123"
        out = Template("{% for i in n|rangelistfrom0 %}{{ i }}{% endfor %}").render(
            Context({"n": 2})
        )
        assert out == "01"

    def test_is_modif_allowed_usable_as_template_filter(self):
        out = Template("{{ d|is_modif_allowed:data }}").render(
            Context({"d": datetime.date(2030, 1, 1), "data": make_data()})
        )
        assert out == "True"


class TestIsModifAllowed:
    def test_non_portail_mode_always_allowed(self):
        data = make_data(limite="0#00:00", mode="consommations", consultation=True)
        assert is_modif_allowed(datetime.date(2000, 1, 1), data) is True

    def test_consultation_mode_forbids(self):
        assert (
            is_modif_allowed(datetime.date(2030, 1, 1), make_data(consultation=True))
            is False
        )

    def test_not_consultation_mode_allows_when_no_limit(self):
        assert (
            is_modif_allowed(datetime.date(2030, 1, 1), make_data(consultation=False))
            is True
        )

    def test_no_periode_reservation_key_allows_when_no_limit(self):
        assert is_modif_allowed(datetime.date(2030, 1, 1), make_data()) is True

    def test_empty_limit_allows_even_past_dates(self):
        assert is_modif_allowed(datetime.date(2000, 1, 1), make_data(limite="")) is True

    # --- "J-x" : x open days before, at HH:MM ---
    def test_j_minus_0_same_day_before_hour_allowed(self):
        assert (
            is_modif_allowed(datetime.date(2024, 5, 15), make_data("0#18:00")) is True
        )

    def test_j_minus_0_same_day_after_hour_forbidden(self):
        assert (
            is_modif_allowed(datetime.date(2024, 5, 15), make_data("0#08:00")) is False
        )

    def test_j_minus_1_tomorrow_before_limit_allowed(self):
        # limit = today 18:00 ; now = today 12:00
        assert (
            is_modif_allowed(datetime.date(2024, 5, 16), make_data("1#18:00")) is True
        )

    def test_j_minus_1_tomorrow_after_limit_forbidden(self):
        assert (
            is_modif_allowed(datetime.date(2024, 5, 16), make_data("1#08:00")) is False
        )

    def test_j_minus_2_day_after_tomorrow(self):
        assert (
            is_modif_allowed(datetime.date(2024, 5, 17), make_data("2#18:00")) is True
        )
        # J-2 before the 16th is the 14th 18:00, already passed at "now" (15th 12:00)
        assert (
            is_modif_allowed(datetime.date(2024, 5, 16), make_data("2#18:00")) is False
        )
        assert (
            is_modif_allowed(datetime.date(2024, 5, 14), make_data("2#18:00")) is False
        )

    def test_exclude_weekends_skips_saturday_and_sunday(self, monkeypatch):
        # Monday 2024-05-20, J-1 skipping weekends -> Friday 17th 18:00 (future) -> allowed
        data = make_data("1#18:00#exclure_weekends")
        assert is_modif_allowed(datetime.date(2024, 5, 20), data) is True
        # Without exclusion, limit is Sunday 19th 18:00 -> allowed too; use a frozen-now past case:
        freeze(monkeypatch, datetime.datetime(2024, 5, 19, 12, 0))
        # Sunday noon: with weekend exclusion the limit is Friday 17th -> passed
        assert is_modif_allowed(datetime.date(2024, 5, 20), data) is False
        # Without weekend exclusion the limit is Sunday 18:00 -> still allowed
        assert (
            is_modif_allowed(datetime.date(2024, 5, 20), make_data("1#18:00")) is True
        )

    def test_exclude_feries_skips_holiday(self, monkeypatch):
        # Date: Thursday 2024-05-02, J-1 would be 1st May (holiday) -> Tuesday 30th April 18:00.
        data = make_data("1#18:00#exclure_feries", feries=[HOLIDAY])
        freeze(monkeypatch, datetime.datetime(2024, 5, 1, 9, 0))
        assert is_modif_allowed(datetime.date(2024, 5, 2), data) is False
        # without the holiday exclusion the limit is 1 May 18:00 -> still open
        assert is_modif_allowed(datetime.date(2024, 5, 2), make_data("1#18:00")) is True

    def test_exclude_specific_weekdays(self):
        # exclure_jours02 -> Wednesday(2)... digits are weekday numbers (0=Monday)
        # Date Thursday 2024-05-16, J-1 would be Wednesday 15 (excluded) -> Tuesday 14 18:00 (passed at noon 15th).
        data = make_data("1#18:00#exclure_jours2")
        assert is_modif_allowed(datetime.date(2024, 5, 16), data) is False
        assert (
            is_modif_allowed(datetime.date(2024, 5, 16), make_data("1#18:00")) is True
        )

    def test_exclude_specific_weekdays_other_day_not_excluded(self):
        data = make_data("1#18:00#exclure_jours4")  # Friday excluded, irrelevant here
        assert is_modif_allowed(datetime.date(2024, 5, 16), data) is True

    # --- 1000-1006 : previous monday..sunday ---
    def test_previous_weekday_rule_allowed(self):
        # 1002 -> previous Wednesday: for date Friday 2024-05-17, limit = Thursday 16 - then Wed(-1) => 15th... see below
        data = make_data("1002#23:59")
        # limit = date - (1 day, weekday=WE(-1)) = 2024-05-17 -> 05-16 -> previous Wednesday = 05-15 23:59
        assert is_modif_allowed(datetime.date(2024, 5, 17), data) is True

    def test_previous_weekday_rule_forbidden(self):
        data = make_data("1002#08:00")  # limit 2024-05-15 08:00 < now(12:00)
        assert is_modif_allowed(datetime.date(2024, 5, 17), data) is False

    # --- 2000-2006 : weekday of the previous week ---
    def test_previous_week_rule_allowed(self):
        # 2004 -> Friday of previous week, for date Wed 2024-05-22: limit = Friday 2024-05-17 18:00 (future at 05-15)
        data = make_data("2004#18:00")
        assert is_modif_allowed(datetime.date(2024, 5, 22), data) is True

    def test_previous_week_rule_forbidden(self, monkeypatch):
        freeze(monkeypatch, datetime.datetime(2024, 5, 20, 12, 0))
        data = make_data("2004#18:00")
        assert is_modif_allowed(datetime.date(2024, 5, 22), data) is False

    def test_nbre_jours_out_of_known_ranges_never_blocks(self):
        # 1500 matches no rule -> limit stays the day itself at HH:MM
        assert (
            is_modif_allowed(datetime.date(2024, 5, 20), make_data("1500#10:00"))
            is True
        )
