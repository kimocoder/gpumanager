import json
import logging
from pathlib import Path
import tempfile
import os

import importlib


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    # Load the settings module afresh so we can monkeypatch its CONFIG_DIR
    settings = importlib.import_module("nvidia_manager.settings")
    # Point CONFIG_DIR to a temporary directory
    tempdir = tmp_path / "conf"
    monkeypatch.setattr(settings, "CONFIG_DIR", tempdir)
    monkeypatch.setattr(settings, "CONFIG_PATH", tempdir / "settings.json")

    defaults = {"a": 1, "b": 2}
    # Save settings that override one default and add a new key
    to_save = {"b": 42, "c": "extra"}
    settings.save_settings(to_save)

    # Ensure file was created
    assert (tempdir / "settings.json").exists()

    # Load back and ensure defaults are merged and overrides applied
    loaded = settings.load_settings(defaults)
    assert loaded["a"] == 1
    assert loaded["b"] == 42
    assert loaded["c"] == "extra"


def test_load_invalid_json_returns_defaults(tmp_path, monkeypatch, caplog):
    settings = importlib.import_module("nvidia_manager.settings")
    tempdir = tmp_path / "conf2"
    monkeypatch.setattr(settings, "CONFIG_DIR", tempdir)
    monkeypatch.setattr(settings, "CONFIG_PATH", tempdir / "settings.json")

    tempdir.mkdir(parents=True, exist_ok=True)
    # Write invalid JSON to the settings file
    p = tempdir / "settings.json"
    p.write_text("not a json", encoding="utf-8")

    caplog.set_level(logging.WARNING)
    defaults = {"x": 10}
    loaded = settings.load_settings(defaults)

    # Invalid JSON should result in defaults being returned (merged)
    assert loaded["x"] == 10
    # And an exception or warning should have been logged
    assert any(
        "Failed to load settings" in rec.message or
        "did not contain a JSON object" in rec.message
        for rec in caplog.records
    )

