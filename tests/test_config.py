from pathlib import Path

import pytest

from calsync.config import expand_env, load_config


def test_expand_env_replaces_nested_values():
    cfg = {"people": [{"name": "${A}", "target_calendar": "Kalender ${B}"}], "n": 3}
    out = expand_env(cfg, {"A": "Anna", "B": "Bo"})
    assert out == {"people": [{"name": "Anna", "target_calendar": "Kalender Bo"}], "n": 3}


def test_missing_variable_fails_clearly():
    with pytest.raises(KeyError, match="GOOGLE_PERSON_NAME"):
        expand_env("${GOOGLE_PERSON_NAME}", {})


def test_repo_config_loads_names_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_PERSON_NAME", "Anna")
    monkeypatch.setenv("ICLOUD_PERSON_NAME", "Bo")
    cfg = load_config(Path(__file__).parent.parent / "config.yaml")
    google, icloud = cfg["people"]
    assert (google["name"], google["target_calendar"]) == ("Anna", "Hvad laver Bo?")
    assert (icloud["name"], icloud["target_calendar"]) == ("Bo", "Hvad laver Anna?")
