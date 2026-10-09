from pathlib import Path
from types import SimpleNamespace

from app import catalog


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_house_settings_modal_has_one_form_and_fixed_checkbox_layout() -> None:
    houses = Path("app/templates/houses.html").read_text(encoding="utf-8")
    dialog = Path("app/templates/_house_settings_dialog.html").read_text(encoding="utf-8")

    assert 'data-settings-open' in houses
    assert '{% include "_house_settings_dialog.html" %}' in houses
    assert '/houses/plz-blacklist' not in houses
    assert '/houses/hospital-policy' not in houses
    assert '/houses/internet-policy' not in houses
    assert '/houses/workplace' not in houses

    assert dialog.count("<form ") == 1
    assert 'action="/houses/settings"' in dialog
    assert dialog.count("Einstellungen speichern") == 1
    assert 'class="checkbox-field"' in dialog
    assert "Unbekannt ablehnen" in dialog


def test_unified_house_settings_save_commits_once(monkeypatch) -> None:
    db = _FakeDb()
    calls: list[tuple] = []

    monkeypatch.setattr(catalog, "_profile_or_503", lambda _db: SimpleNamespace(id=7))
    monkeypatch.setattr(catalog, "selected_country", lambda: "DE")
    monkeypatch.setattr(
        catalog,
        "save_de_plz_blacklist",
        lambda _db, profile_id, raw, *, commit: calls.append(
            ("plz", profile_id, raw, commit)
        ),
    )
    monkeypatch.setattr(
        catalog,
        "save_hospital_distance_policy",
        lambda _db, profile_id, raw, *, fail_closed, commit: calls.append(
            ("hospital", profile_id, raw, fail_closed, commit)
        ),
    )
    monkeypatch.setattr(
        catalog,
        "save_internet_policy",
        lambda _db, profile_id, raw, *, commit: calls.append(
            ("internet", profile_id, raw, commit)
        ),
    )
    monkeypatch.setattr(
        catalog,
        "save_candidate_workplace",
        lambda _db, profile_id, *, country_code, input_text, commit, force_geocoding_retry: calls.append(
            ("workplace", profile_id, country_code, input_text, commit, force_geocoding_retry)
        ),
    )

    response = catalog.update_house_settings(
        None,
        None,
        db,
        plz_blacklist_text="01067\n0xxxx",
        hospital_max_distance_km="25",
        hospital_fail_closed="1",
        internet_minimum_mbps="100",
        workplace_country="DE",
        workplace_text="01067 Dresden",
        return_to="/houses?ansicht=alle",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/houses?ansicht=alle"
    assert db.commits == 1
    assert db.rollbacks == 0
    assert calls == [
        ("plz", 7, "01067\n0xxxx", False),
        ("hospital", 7, "25", True, False),
        ("internet", 7, "100", False),
        ("workplace", 7, "DE", "01067 Dresden", False, False),
    ]


def test_unified_house_settings_does_not_mutate_de_policy_in_at(monkeypatch) -> None:
    db = _FakeDb()
    workplace_calls: list[tuple] = []

    monkeypatch.setattr(catalog, "_profile_or_503", lambda _db: SimpleNamespace(id=9))
    monkeypatch.setattr(catalog, "selected_country", lambda: "AT")
    monkeypatch.setattr(
        catalog,
        "save_de_plz_blacklist",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DE policy touched")),
    )
    monkeypatch.setattr(
        catalog,
        "save_hospital_distance_policy",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DE policy touched")),
    )
    monkeypatch.setattr(
        catalog,
        "save_internet_policy",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DE policy touched")),
    )
    monkeypatch.setattr(
        catalog,
        "save_candidate_workplace",
        lambda _db, profile_id, *, country_code, input_text, commit, force_geocoding_retry: workplace_calls.append(
            (profile_id, country_code, input_text, commit, force_geocoding_retry)
        ),
    )

    response = catalog.update_house_settings(
        None,
        None,
        db,
        plz_blacklist_text="0xxxx",
        hospital_max_distance_km="20",
        hospital_fail_closed="1",
        internet_minimum_mbps="1000",
        workplace_country="AT",
        workplace_text="5020 Salzburg",
        return_to="/houses",
    )

    assert response.status_code == 303
    assert db.commits == 1
    assert db.rollbacks == 0
    assert workplace_calls == [(9, "AT", "5020 Salzburg", False, False)]
