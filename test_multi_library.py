#!/usr/bin/env python3
"""Focused tests for multi-library selection and export writers."""

import csv
import os
import sys
import tempfile
from datetime import datetime
from types import SimpleNamespace

# Import without requiring a live Plex connection.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plex_library_exporter import (  # noqa: E402
    _display_name,
    _export_html,
    _format_date,
    _parse_library_choice,
    export_titles,
)


def test_parse_all():
    assert _parse_library_choice("all", 5) == [1, 2, 3, 4, 5]
    assert _parse_library_choice("ALL", 3) == [1, 2, 3]
    assert _parse_library_choice("*", 2) == [1, 2]
    assert _parse_library_choice("a", 2) == [1, 2]


def test_parse_single():
    assert _parse_library_choice("2", 5) == [2]
    assert _parse_library_choice("1", 1) == [1]


def test_parse_comma_and_space():
    assert _parse_library_choice("1,3,5", 5) == [1, 3, 5]
    assert _parse_library_choice("1, 3, 5", 5) == [1, 3, 5]
    assert _parse_library_choice("1 3 5", 5) == [1, 3, 5]


def test_parse_range():
    assert _parse_library_choice("1-3", 5) == [1, 2, 3]
    assert _parse_library_choice("3-1", 5) == [1, 2, 3]
    assert _parse_library_choice("1,3-5", 5) == [1, 3, 4, 5]


def test_parse_dedupes():
    assert _parse_library_choice("1,1,2", 5) == [1, 2]
    assert _parse_library_choice("1-3,2", 5) == [1, 2, 3]


def test_parse_invalid():
    assert _parse_library_choice("", 5) is None
    assert _parse_library_choice("0", 5) is None
    assert _parse_library_choice("6", 5) is None
    assert _parse_library_choice("foo", 5) is None
    assert _parse_library_choice("1-9", 5) is None
    assert _parse_library_choice("1,x", 5) is None


def test_display_name():
    one = [SimpleNamespace(title="Movies")]
    two = [SimpleNamespace(title="Movies"), SimpleNamespace(title="TV")]
    assert _display_name(one) == "Movies"
    assert _display_name(two) == "2 Libraries"


def test_format_date():
    assert _format_date(None) == ""
    assert _format_date(datetime(2024, 3, 15, 12, 0, 0)) == "2024-03-15"


class FakeSection:
    def __init__(self, title, type_, items):
        self.title = title
        self.type = type_
        self._items = items

    def all(self):
        return self._items

    def searchAlbums(self):
        return self._items


def _item(title, added=None, author=None):
    ns = SimpleNamespace(title=title, addedAt=added)
    if author is not None:
        ns.parentTitle = author
    return ns


def test_csv_single_library():
    movies = FakeSection(
        "Movies",
        "movie",
        [_item("Alien", datetime(2020, 1, 1)), _item("Dune", datetime(2021, 6, 1))],
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.csv")
        export_titles([movies], "csv", path)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == ["Title", "Date Added"]
        assert rows[1] == ["Alien", "2020-01-01"]
        assert rows[2] == ["Dune", "2021-06-01"]


def test_csv_multi_library_includes_library_column():
    movies = FakeSection("Movies", "movie", [_item("Alien", datetime(2020, 1, 1))])
    tv = FakeSection("TV Shows", "show", [_item("The Expanse", datetime(2019, 5, 1))])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.csv")
        export_titles([movies, tv], "csv", path)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == ["Title", "Library", "Date Added"]
        titles = {r[0]: r[1] for r in rows[1:]}
        assert titles["Alien"] == "Movies"
        assert titles["The Expanse"] == "TV Shows"


def test_csv_audiobook_and_movie_includes_author():
    books = FakeSection(
        "Audiobooks",
        "artist",
        [_item("Project Hail Mary", datetime(2022, 1, 1), author="Andy Weir")],
    )
    movies = FakeSection("Movies", "movie", [_item("Alien", datetime(2020, 1, 1))])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.csv")
        export_titles([books, movies], "csv", path)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == ["Title", "Library", "Author", "Date Added"]
        by_title = {r[0]: r for r in rows[1:]}
        assert by_title["Project Hail Mary"][2] == "Andy Weir"
        assert by_title["Alien"][2] == ""


def test_text_multi_library():
    movies = FakeSection("Movies", "movie", [_item("Alien")])
    books = FakeSection(
        "Audiobooks",
        "artist",
        [_item("Project Hail Mary", author="Andy Weir")],
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.txt")
        export_titles([movies, books], "text", path)
        lines = open(path, encoding="utf-8").read().splitlines()
        assert "Alien [Movies]" in lines
        assert "Project Hail Mary by Andy Weir [Audiobooks]" in lines


def test_html_multi_library_has_library_column_and_sort_script():
    movies = FakeSection("Movies", "movie", [_item("Alien", datetime(2020, 1, 1))])
    tv = FakeSection("TV Shows", "show", [_item("The Expanse", datetime(2019, 5, 1))])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.html")
        export_titles([movies, tv], "html", path)
        html = open(path, encoding="utf-8").read()
        assert "2 Libraries" in html
        assert ">Library<" in html
        assert "Movies" in html
        assert "TV Shows" in html
        assert "Alien" in html
        assert "The Expanse" in html
        assert "dateColumnIndex = headers.length - 1" in html
        assert "Plexee Library Export" in html


def test_html_single_library_no_library_column():
    movies = FakeSection("Movies", "movie", [_item("Alien", datetime(2020, 1, 1))])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.html")
        export_titles([movies], "html", path)
        html = open(path, encoding="utf-8").read()
        assert ">Library<" not in html
        assert "Movies" in html


def test_html_escapes_special_chars():
    movies = FakeSection(
        "Movies",
        "movie",
        [_item("Tom & Jerry <Show>")],
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.html")
        _export_html(
            [{"title": "Tom & Jerry <Show>", "library": "Movies", "added_at": None}],
            "Movies",
            path,
            include_author=False,
            include_library=True,
        )
        html = open(path, encoding="utf-8").read()
        assert "Tom &amp; Jerry &lt;Show&gt;" in html
        assert "Tom & Jerry <Show>" not in html


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
