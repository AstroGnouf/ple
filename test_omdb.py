#!/usr/bin/env python3
"""Focused tests for OMDb / IMDb rating lookups and export columns."""

import csv
import json
import os
import sys
import tempfile
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plex_library_exporter import (  # noqa: E402
    OmdbInvalidKeyError,
    _export_html,
    _fetch_standard_titles,
    _is_movie_library,
    _title_cache_key,
    choose_omdb_settings,
    enrich_entries_with_omdb_ratings,
    export_titles,
    extract_imdb_id,
    fetch_omdb_rating,
    load_omdb_cache,
    save_omdb_cache,
)


class FakeSection:
    def __init__(self, title, type_, items):
        self.title = title
        self.type = type_
        self._items = items

    def all(self):
        return self._items

    def searchAlbums(self):
        return self._items


def _movie(title, added=None, imdb_id=None, year=None, guid=None):
    ns = SimpleNamespace(title=title, addedAt=added, year=year)
    if imdb_id:
        ns.guids = [SimpleNamespace(id=f"imdb://{imdb_id}")]
    elif guid:
        ns.guid = guid
        ns.guids = []
    else:
        ns.guids = []
        ns.guid = None
    return ns


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make_opener(payloads_by_query: dict, calls: list | None = None):
    """Return a urlopen stand-in keyed by IMDb id or title query string."""

    def opener(request, timeout=15):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if calls is not None:
            calls.append(url)
        qs = parse_qs(urlparse(url).query)
        key = (qs.get("i") or qs.get("t") or [url])[0]
        if key not in payloads_by_query:
            raise AssertionError(f"Unexpected OMDb query: {key} url={url}")
        payload = payloads_by_query[key]
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)

    return opener


def test_extract_imdb_id_from_guids():
    item = SimpleNamespace(guids=[SimpleNamespace(id="imdb://tt0111161")])
    assert extract_imdb_id(item) == "tt0111161"


def test_extract_imdb_id_from_agent_guid():
    item = SimpleNamespace(
        guids=[],
        guid="com.plexapp.agents.imdb://tt1375666?lang=en",
    )
    assert extract_imdb_id(item) == "tt1375666"


def test_extract_imdb_id_missing():
    item = SimpleNamespace(guids=[SimpleNamespace(id="tmdb://123")], guid="plex://movie/abc")
    assert extract_imdb_id(item) is None


def test_is_movie_library():
    assert _is_movie_library(SimpleNamespace(type="movie")) is True
    assert _is_movie_library(SimpleNamespace(type="show")) is False
    assert _is_movie_library(SimpleNamespace(type="artist")) is False


def test_fetch_standard_titles_captures_imdb_for_movies():
    section = FakeSection(
        "Movies",
        "movie",
        [_movie("Inception", datetime(2020, 1, 1), imdb_id="tt1375666", year=2010)],
    )
    entries = _fetch_standard_titles(section)
    assert entries[0]["title"] == "Inception"
    assert entries[0]["imdb_id"] == "tt1375666"
    assert entries[0]["year"] == 2010


def test_fetch_standard_titles_tv_has_no_imdb_id():
    section = FakeSection(
        "TV",
        "show",
        [_movie("The Expanse", datetime(2019, 5, 1), imdb_id="tt3230854")],
    )
    entries = _fetch_standard_titles(section)
    assert "imdb_id" not in entries[0]


def test_fetch_omdb_rating_by_id():
    opener = make_opener(
        {"tt0111161": {"Response": "True", "imdbRating": "9.3", "imdbID": "tt0111161", "Title": "The Shawshank Redemption"}}
    )
    result = fetch_omdb_rating("fake-key", imdb_id="tt0111161", opener=opener)
    assert result["imdb_rating"] == "9.3"
    assert result["imdb_id"] == "tt0111161"


def test_fetch_omdb_rating_not_found():
    opener = make_opener({"Missing": {"Response": "False", "Error": "Movie not found!"}})
    result = fetch_omdb_rating("fake-key", title="Missing", opener=opener)
    assert result["imdb_rating"] == ""
    assert "not found" in result["error"].lower() or result["error"] == "Movie not found!"


def test_fetch_omdb_rating_na():
    opener = make_opener({"tt0000001": {"Response": "True", "imdbRating": "N/A", "imdbID": "tt0000001"}})
    result = fetch_omdb_rating("fake-key", imdb_id="tt0000001", opener=opener)
    assert result["imdb_rating"] == ""


def test_fetch_omdb_invalid_key():
    opener = make_opener({"tt0111161": {"Response": "False", "Error": "Invalid API key!"}})
    try:
        fetch_omdb_rating("bad", imdb_id="tt0111161", opener=opener)
        raise AssertionError("expected OmdbInvalidKeyError")
    except OmdbInvalidKeyError:
        pass


def test_enrich_uses_cache_and_skips_network():
    calls = []
    opener = make_opener({}, calls=calls)
    cache = {"tt0111161": {"imdb_rating": "9.3", "imdb_id": "tt0111161"}}
    entries = [{"title": "Shawshank", "imdb_id": "tt0111161"}]
    stats = enrich_entries_with_omdb_ratings(
        entries, "key", cache=cache, opener=opener, delay=0
    )
    assert entries[0]["imdb_rating"] == "9.3"
    assert stats["cached"] == 1
    assert stats["fetched"] == 0
    assert calls == []


def test_enrich_fetches_and_writes_cache():
    opener = make_opener(
        {"tt1375666": {"Response": "True", "imdbRating": "8.8", "imdbID": "tt1375666", "Title": "Inception"}}
    )
    cache = {}
    entries = [{"title": "Inception", "imdb_id": "tt1375666", "year": 2010}]
    stats = enrich_entries_with_omdb_ratings(
        entries, "key", cache=cache, opener=opener, delay=0
    )
    assert entries[0]["imdb_rating"] == "8.8"
    assert stats["fetched"] == 1
    assert cache["tt1375666"]["imdb_rating"] == "8.8"


def test_enrich_title_fallback_when_no_imdb_id():
    opener = make_opener(
        {"Alien": {"Response": "True", "imdbRating": "8.5", "imdbID": "tt0078748", "Title": "Alien"}}
    )
    cache = {}
    entries = [{"title": "Alien", "imdb_id": "", "year": 1979}]
    enrich_entries_with_omdb_ratings(entries, "key", cache=cache, opener=opener, delay=0)
    assert entries[0]["imdb_rating"] == "8.5"
    assert entries[0]["imdb_id"] == "tt0078748"
    assert cache[_title_cache_key("Alien", 1979)]["imdb_rating"] == "8.5"


def test_enrich_ignores_non_movie_entries():
    opener = make_opener({})
    entries = [{"title": "Project Hail Mary", "author": "Andy Weir"}]
    stats = enrich_entries_with_omdb_ratings(
        entries, "key", cache={}, opener=opener, delay=0
    )
    assert "imdb_rating" not in entries[0]
    assert stats["fetched"] == 0


def test_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "omdb_cache.json")
        save_omdb_cache({"tt1": {"imdb_rating": "7.0"}}, path)
        loaded = load_omdb_cache(path)
        assert loaded["tt1"]["imdb_rating"] == "7.0"
        assert load_omdb_cache(os.path.join(tmp, "missing.json")) == {}


def test_choose_omdb_skips_non_movie():
    sections = [SimpleNamespace(type="artist", title="Audiobooks")]
    assert choose_omdb_settings({}, sections, automated=True) is None


def test_choose_omdb_automated_uses_saved_key():
    sections = [SimpleNamespace(type="movie", title="Movies")]
    key = choose_omdb_settings(
        {"omdb_api_key": "abc123", "omdb_enabled": True},
        sections,
        automated=True,
    )
    assert key == "abc123"


def test_choose_omdb_automated_disabled():
    sections = [SimpleNamespace(type="movie", title="Movies")]
    key = choose_omdb_settings(
        {"omdb_api_key": "abc123", "omdb_enabled": False},
        sections,
        automated=True,
    )
    assert key is None


def test_csv_includes_imdb_rating_column():
    movies = FakeSection(
        "Movies",
        "movie",
        [_movie("Alien", datetime(2020, 1, 1), imdb_id="tt0078748", year=1979)],
    )
    cache = {"tt0078748": {"imdb_rating": "8.5", "imdb_id": "tt0078748"}}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.csv")
        export_titles([movies], "csv", path, omdb_api_key="key", omdb_cache=cache)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == ["Title", "IMDb Rating", "Date Added"]
        assert rows[1] == ["Alien", "8.5", "2020-01-01"]


def test_csv_without_key_has_no_rating_column():
    movies = FakeSection(
        "Movies",
        "movie",
        [_movie("Alien", datetime(2020, 1, 1), imdb_id="tt0078748")],
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.csv")
        export_titles([movies], "csv", path)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == ["Title", "Date Added"]


def test_text_appends_rating():
    movies = FakeSection(
        "Movies",
        "movie",
        [_movie("Alien", imdb_id="tt0078748")],
    )
    cache = {"tt0078748": {"imdb_rating": "8.5", "imdb_id": "tt0078748"}}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.txt")
        export_titles([movies], "text", path, omdb_api_key="key", omdb_cache=cache)
        lines = open(path, encoding="utf-8").read().splitlines()
        assert lines == ["Alien (8.5)"]


def test_html_includes_rating_column():
    movies = FakeSection(
        "Movies",
        "movie",
        [_movie("Alien", datetime(2020, 1, 1), imdb_id="tt0078748")],
    )
    cache = {"tt0078748": {"imdb_rating": "8.5", "imdb_id": "tt0078748"}}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.html")
        export_titles([movies], "html", path, omdb_api_key="key", omdb_cache=cache)
        html = open(path, encoding="utf-8").read()
        assert "IMDb Rating" in html
        assert "rating-cell" in html
        assert "8.5" in html
        assert "looksLikeNumber" in html


def test_html_direct_rating_flag():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.html")
        _export_html(
            [{"title": "Dune", "imdb_rating": "8.0", "added_at": None}],
            "Movies",
            path,
            include_rating=True,
        )
        html = open(path, encoding="utf-8").read()
        assert ">IMDb Rating<" in html
        assert "8.0" in html


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
        except Exception as extra:
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(extra).__name__}: {extra}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
