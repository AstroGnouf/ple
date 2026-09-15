#!/usr/bin/env python3
"""Test automatic file extension handling."""

import os
import sys

# Test the filename extension logic in isolation.
def apply_extension(name: str, default_ext: str, last_filename: str = None) -> str:
    """Simulates the choose_filename logic without user input."""
    if name == "" and last_filename:
        last_base = os.path.splitext(last_filename)[0]
        name = last_base
    
    if name:
        base_name = os.path.splitext(name)[0]
        if base_name:
            return f"{base_name}.{default_ext}"
    return None


def test_adds_extension():
    assert apply_extension("myfile", "csv") == "myfile.csv"
    assert apply_extension("myfile", "html") == "myfile.html"
    assert apply_extension("myfile", "txt") == "myfile.txt"


def test_replaces_wrong_extension():
    assert apply_extension("myfile.txt", "csv") == "myfile.csv"
    assert apply_extension("myfile.html", "csv") == "myfile.csv"
    assert apply_extension("myfile.old.csv", "html") == "myfile.old.html"


def test_uses_last_filename_base():
    assert apply_extension("", "csv", "movies.html") == "movies.csv"
    assert apply_extension("", "txt", "audiobooks.csv") == "audiobooks.txt"


def test_strips_extension_from_user_input():
    assert apply_extension("report.csv", "html") == "report.html"
    assert apply_extension("data.txt", "csv") == "data.csv"


def test_handles_dots_in_filename():
    # os.path.splitext treats the last dot as extension separator.
    assert apply_extension("my.file.name", "csv") == "my.file.csv"
    assert apply_extension("my.file.name.old", "html") == "my.file.name.html"
    assert apply_extension("report.2024.csv", "html") == "report.2024.html"


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
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
