import pytest

from app.common import config


def test_categories_include_fallback():
    assert "Other" in config.CATEGORIES
    assert len(config.CATEGORIES) == len(set(config.CATEGORIES))


def test_env_requires_value(monkeypatch):
    monkeypatch.delenv("DOCAGENT_X", raising=False)
    with pytest.raises(RuntimeError):
        config.env("DOCAGENT_X")
    assert config.env("DOCAGENT_X", "d") == "d"
