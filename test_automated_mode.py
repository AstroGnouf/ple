#!/usr/bin/env python3
"""Tests for Interactive vs Automated run mode (cron-friendly)."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ple import (  # noqa: E402
    MODE_AUTOMATED,
    MODE_INTERACTIVE,
    _remembered_libraries,
    choose_export_format,
    choose_filename,
    ensure_mode,
    filename_for_library,
    is_automated,
    parse_args,
    sanitize_filename,
    select_libraries,
)


def test_is_automated():
    assert is_automated({"mode": "automated"}) is True
    assert is_automated({"mode": "Automated"}) is True
    assert is_automated({"mode": "interactive"}) is False
    assert is_automated({}) is False


def test_parse_args_setup():
    assert parse_args([]).setup is False
    assert parse_args(["--setup"]).setup is True


def test_ensure_mode_uses_saved():
    mode, just = ensure_mode({"mode": MODE_AUTOMATED})
    assert mode == MODE_AUTOMATED
    assert just is False
    mode, just = ensure_mode({"mode": MODE_INTERACTIVE})
    assert mode == MODE_INTERACTIVE
    assert just is False


def test_ensure_mode_unattended_without_config_exits():
    with patch("ple.stdin_is_interactive", return_value=False):
        try:
            ensure_mode({})
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")


def test_sanitize_filename():
    assert sanitize_filename("Movies") == "Movies"
    assert sanitize_filename("TV Shows") == "TV_Shows"
    assert sanitize_filename('A/B:C*D?') == "A_B_C_D"
    assert sanitize_filename("   ") == "library"


def test_filename_for_library_uses_saved_stem():
    config = {"library_filenames": {"Movies": "movies.html"}}
    assert filename_for_library("Movies", "csv", config) == "movies.csv"
    assert filename_for_library("TV Shows", "html", {}) == "TV_Shows.html"


def test_choose_filename_automated_reuses_last():
    name = choose_filename("csv", "Movies", "movies.html", automated=True)
    assert name == "movies.csv"


def test_choose_filename_automated_generates_from_title():
    name = choose_filename("html", "TV Shows", None, automated=True)
    assert name == "TV_Shows.html"


def test_choose_export_format_automated_uses_saved():
    fmt = choose_export_format({"export_format": "csv"}, automated=True)
    assert fmt == "csv"


def test_choose_export_format_automated_defaults_html():
    with patch("ple.save_config"):
        fmt = choose_export_format({}, automated=True)
    assert fmt == "html"


def test_remembered_libraries_skips_missing():
    sections = [
        SimpleNamespace(title="Movies", type="movie"),
        SimpleNamespace(title="TV Shows", type="show"),
    ]
    found = _remembered_libraries(
        sections, {"last_libraries": ["Movies", "Gone", "TV Shows"]}
    )
    assert [s.title for s in found] == ["Movies", "TV Shows"]


def test_select_libraries_automated_reuses_saved():
    sections = [
        SimpleNamespace(title="Movies", type="movie"),
        SimpleNamespace(title="TV Shows", type="show"),
        SimpleNamespace(title="Music", type="artist"),
    ]
    config = {"last_libraries": ["TV Shows", "Music"]}
    with patch("ple.save_config"):
        selected = select_libraries(sections, config, automated=True)
    assert [s.title for s in selected] == ["TV Shows", "Music"]


def test_select_libraries_automated_exports_all_when_none_saved():
    sections = [
        SimpleNamespace(title="Movies", type="movie"),
        SimpleNamespace(title="TV Shows", type="show"),
    ]
    config = {}
    with patch("ple.save_config"):
        selected = select_libraries(sections, config, automated=True)
    assert [s.title for s in selected] == ["Movies", "TV Shows"]


def test_select_libraries_interactive_without_tty_exits():
    sections = [SimpleNamespace(title="Movies", type="movie")]
    with patch("ple.stdin_is_interactive", return_value=False):
        try:
            select_libraries(sections, {}, automated=False)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    with patch("ple.save_config"):
        for fn in tests:
            try:
                fn()
                print(f"  PASS  {fn.__name__}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {fn.__name__}: {exc}")
            except Exception as exc:
                failed += 1
                print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
