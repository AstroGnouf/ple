#!/usr/bin/env python3
"""
Plexee Library Exporter
=======================
A command-line tool that connects to a Plex Media Server and exports
library titles to CSV, plain-text, or HTML files.  One, several, or
all libraries can be exported in a single run.  Movie and TV show
libraries can optionally include IMDb ratings looked up via the OMDb API.
HTML exports link titles to IMDb when an IMDb id is available.

Usage:
    python3 plex_library_exporter.py
    python3 plex_library_exporter.py --setup

On first run the tool asks whether to use Interactive Manual or
Automated mode, then prompts for server hostname/IP, port, and API
token.  Configuration is saved to config.json.

Automated mode is cron-friendly: later runs use saved settings and
never prompt.  Re-run with --setup to change mode or export settings.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Dependency check – give a friendly message if PlexAPI is not installed.
# ---------------------------------------------------------------------------
try:
    from plexapi.server import PlexServer
    from plexapi.exceptions import Unauthorized, NotFound
except ImportError:
    print(
        "Error: The 'PlexAPI' library is not installed.\n"
        "Install it with:  pip install PlexAPI\n"
        "Or run:           pip install -r requirements.txt"
    )
    sys.exit(1)

# Path to the persistent configuration file (same directory as this script).
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
# Local cache of OMDb / IMDb ratings so each title is looked up once.
OMDB_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "omdb_cache.json")
OMDB_API_URL = "https://www.omdbapi.com/"
OMDB_REQUEST_DELAY = 0.15  # seconds between live API calls

MODE_INTERACTIVE = "interactive"
MODE_AUTOMATED = "automated"
VALID_MODES = (MODE_INTERACTIVE, MODE_AUTOMATED)
VALID_FORMATS = ("csv", "text", "html")
FORMAT_EXTENSIONS = {"csv": "csv", "text": "txt", "html": "html"}


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load configuration from config.json. Returns an empty dict if the file
    does not exist or is corrupted."""
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: Could not read config file ({exc}). Starting fresh.")
    return {}


def save_config(config: dict) -> None:
    """Persist the configuration dictionary to config.json."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
    except OSError as exc:
        print(f"Warning: Could not save config file ({exc}).")


def stdin_is_interactive() -> bool:
    """Return True when stdin is a terminal (safe to prompt)."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def is_automated(config: dict) -> bool:
    """Return True when the saved run mode is Automated."""
    return str(config.get("mode", "")).strip().lower() == MODE_AUTOMATED


def extension_for_format(fmt: str) -> str:
    """Return the file extension for an export format (without the dot)."""
    return FORMAT_EXTENSIONS.get(fmt, "txt")


def sanitize_filename(name: str) -> str:
    """Turn a library title into a safe filename stem."""
    stem = (name or "library").strip()
    stem = re.sub(r'[<>:"/\\|?*]', "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip(" ._")
    return stem or "library"


def apply_extension(name: str, default_ext: str, last_filename: str | None = None) -> str | None:
    """Resolve a user-supplied or remembered filename to *name.ext*.

    Empty *name* falls back to the stem of *last_filename*.  Any extension
    the user typed is stripped and replaced with *default_ext*.
    """
    if name == "" and last_filename:
        name = os.path.splitext(last_filename)[0]
    if not name or name in (".", ".."):
        return None
    base_name = os.path.splitext(name)[0]
    if not base_name or base_name in (".", ".."):
        return None
    return f"{base_name}.{default_ext}"


def filename_for_library(library_name: str, fmt: str, config: dict) -> str:
    """Return the output path for *library_name* without prompting.

    Prefers a previously saved filename (extension updated to match *fmt*),
    otherwise uses a sanitised copy of the library title.
    """
    ext = extension_for_format(fmt)
    saved = (config.get("library_filenames") or {}).get(library_name)
    resolved = apply_extension("", ext, saved)
    if resolved:
        return resolved
    return f"{sanitize_filename(library_name)}.{ext}"


def prompt_for_mode() -> str:
    """Ask whether this install is Interactive Manual or Automated."""
    print("\n--- Run Mode ---")
    print("  1. Interactive Manual  – prompt for libraries, format, and")
    print("                           filenames on every run")
    print("  2. Automated           – no prompts after this setup; reuse")
    print("                           saved settings (suitable for cron)")
    while True:
        choice = input("Select mode [1]: ").strip().lower()
        if choice in ("", "1", "i", "interactive", "manual", "interactive manual"):
            return MODE_INTERACTIVE
        if choice in ("2", "a", "auto", "automated"):
            return MODE_AUTOMATED
        print("Invalid choice. Enter 1 (Interactive Manual) or 2 (Automated).")


def ensure_mode(config: dict, force_setup: bool = False) -> tuple[str, bool]:
    """Return ``(mode, just_configured)``.

    Prompts on first run or when *force_setup* is True.  Exits with a clear
    error if a prompt is required but stdin is not a TTY (e.g. cron before
    the first interactive setup).
    """
    current = str(config.get("mode", "")).strip().lower()
    if current in VALID_MODES and not force_setup:
        return current, False

    if not stdin_is_interactive():
        print(
            "Error: Run mode is not configured, and this session cannot "
            "prompt (stdin is not a terminal).\n"
            "Run once interactively to choose Interactive Manual or "
            "Automated mode:\n"
            f"  python3 {os.path.basename(sys.argv[0])}"
        )
        sys.exit(1)

    mode = prompt_for_mode()
    config["mode"] = mode
    save_config(config)
    label = "Interactive Manual" if mode == MODE_INTERACTIVE else "Automated"
    print(f"✓ Run mode saved: {label}")
    if mode == MODE_AUTOMATED:
        print("  This setup run will still ask for libraries, format, and")
        print("  filenames.  Later Automated runs will reuse those settings.")
    return mode, True


def abort_if_unattended(reason: str) -> None:
    """Exit when a prompt is needed but stdin is not a terminal."""
    if stdin_is_interactive():
        return
    print(f"Error: {reason}")
    print("This process has no terminal, so it cannot prompt for input.")
    print("Configure Automated mode interactively first, or run from a terminal.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Plex connection
# ---------------------------------------------------------------------------

def connect_to_plex(base_url: str, token: str, port: int = 32400) -> PlexServer:
    """Attempt to connect to the Plex server and return a PlexServer instance.

    *port* is the TCP port number to use for the connection. It defaults to
    32400 (the standard Plex Media Server port).

    Prints detailed debug status messages during the connection process.
    Raises an exception on failure so the caller can handle retries.
    """
    # Ensure the URL has a scheme.
    if not base_url.startswith(("http://", "https://")):
        base_url = f"http://{base_url}"
    # Strip any existing port from the URL and use the explicit port parameter.
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    # Rebuild the base URL with the configured port.
    host_part = parsed.hostname or parsed.netloc
    scheme = parsed.scheme or "http"
    base_url = f"{scheme}://{host_part}:{port}"

    print(f"Attempting to connect to {host_part}:{port}...")
    print("Testing API token authentication...")

    try:
        server = PlexServer(base_url, token)
    except Unauthorized as exc:
        print("✗ Connection failed!")
        print("  Error: Unauthorized – the API token was rejected by the server.")
        print("  Please verify your Plex API token is correct and has not expired.")
        print()
        print("  Raw Error Output:")
        print(f"    Exception Type : {type(exc).__module__}.{type(exc).__qualname__}")
        print(f"    Exception Msg  : {exc}")
        tb_str = traceback.format_exc()
        if tb_str and tb_str.strip() != "NoneType: None":
            print("    Traceback:")
            for line in tb_str.strip().splitlines():
                print(f"      {line}")
        raise
    except Exception as exc:
        print("✗ Connection failed!")
        # Provide user-friendly messages for common errors.
        err_msg = str(exc)
        if "Connection refused" in err_msg:
            print(f"  Error: Connection refused – no service is listening on {host_part}:{port}.")
            print("  Check that the Plex Media Server is running and the port is correct.")
        elif "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            print(f"  Error: Connection timeout – could not reach {host_part}:{port}.")
            print("  Check the hostname/IP and ensure no firewall is blocking the connection.")
        elif "Name or service not known" in err_msg or "nodename nor servname" in err_msg:
            print(f"  Error: Server not found – '{host_part}' could not be resolved.")
            print("  Verify the hostname or IP address is spelled correctly.")
        elif "SSL" in err_msg or "certificate" in err_msg.lower():
            print(f"  Error: SSL/TLS error – {err_msg}")
            print("  Try using http:// instead of https://, or check server certificates.")
        else:
            print(f"  Error: {err_msg}")
        print()
        print("  Raw Error Output:")
        print(f"    Exception Type : {type(exc).__module__}.{type(exc).__qualname__}")
        print(f"    Exception Msg  : {exc}")
        tb_str = traceback.format_exc()
        if tb_str and tb_str.strip() != "NoneType: None":
            print("    Traceback:")
            for line in tb_str.strip().splitlines():
                print(f"      {line}")
        raise

    # Connection succeeded – display server details.
    print("✓ Connection successful!")
    print(f"  Server name   : {server.friendlyName}")
    print(f"  Plex version  : {server.version}")
    try:
        lib_count = len(server.library.sections())
        print(f"  Libraries     : {lib_count} found")
    except Exception:
        print("  Libraries     : (unable to enumerate)")

    return server


def validate_port(port_str: str) -> int | None:
    """Return an integer port if *port_str* represents a valid TCP port
    (1–65535), otherwise return ``None``."""
    try:
        port = int(port_str)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    return None


def prompt_for_credentials() -> tuple:
    """Interactively ask the user for Plex server address, TCP port, and API
    token.  Returns a (host, port, token) tuple."""
    print("\n--- Plex Server Configuration ---")
    host = input("Enter Plex server hostname or IP address (e.g. 192.168.1.100): ").strip()

    # Port prompt – default to the standard Plex port if the user just hits Enter.
    while True:
        port_input = input("Enter Plex server TCP port [32400]: ").strip()
        if port_input == "":
            port = 32400
            break
        port = validate_port(port_input)
        if port is not None:
            break
        print("Invalid port number. Please enter a value between 1 and 65535.")

    token = input("Enter your Plex API token: ").strip()
    return host, port, token


def establish_connection(config: dict, automated: bool = False) -> PlexServer:
    """Try to connect using saved config or prompt the user. Allows retries on
    failure. Returns a connected PlexServer instance and updates *config*
    in-place with the validated credentials.

    Automated / non-TTY runs never prompt: they use saved credentials or exit.
    """

    host = config.get("host", "")
    token = config.get("token", "")
    # Backward compatibility: default to 32400 if port is missing from config.
    port = config.get("port", 32400)

    # If we already have saved credentials, try them first.
    if host and token:
        print(f"\nUsing saved credentials for {host}:{port}…")
        try:
            server = connect_to_plex(host, token, port)
            return server
        except Exception:
            pass  # Debug details already printed by connect_to_plex.
        if automated or not stdin_is_interactive():
            print("Error: Saved credentials did not work. Cannot prompt in Automated mode.")
            print("Run interactively with --setup to re-enter server details.")
            sys.exit(1)
        print("Saved credentials did not work. Please re-enter them.\n")

    abort_if_unattended(
        "Plex server credentials are missing or invalid."
    )

    # Interactive prompt loop with retry support.
    while True:
        host, port, token = prompt_for_credentials()
        if not host or not token:
            print("Error: Both hostname and token are required.")
            continue
        try:
            server = connect_to_plex(host, token, port)
            # Persist validated credentials.
            config["host"] = host
            config["port"] = port
            config["token"] = token
            save_config(config)
            return server
        except Exception:
            pass  # Debug details already printed by connect_to_plex.

        # Offer to retry.
        retry = input("Would you like to try again? (y/n): ").strip().lower()
        if retry not in ("y", "yes"):
            print("Exiting.")
            sys.exit(0)


# ---------------------------------------------------------------------------
# Library discovery & selection
# ---------------------------------------------------------------------------

def discover_libraries(server: PlexServer) -> list:
    """Return a list of library section objects from the Plex server."""
    sections = server.library.sections()
    if not sections:
        print("No libraries found on the server.")
        sys.exit(1)
    return sections


def _parse_library_choice(choice: str, count: int) -> list[int] | None:
    """Parse a library selection string into 1-based indices.

    Accepts:
      - ``all`` / ``*``  – every library
      - a single number  – e.g. ``2``
      - comma-separated  – e.g. ``1,3,5``
      - ranges           – e.g. ``1-3`` or ``1,3-5``
      - space-separated  – e.g. ``1 3 5``

    Returns a de-duplicated list of valid indices, or ``None`` if the
    input cannot be parsed.
    """
    raw = choice.strip().lower()
    if raw in ("all", "*", "a"):
        return list(range(1, count + 1))

    # Normalise separators: commas and whitespace both work; ranges use '-'.
    tokens = raw.replace(",", " ").split()
    if not tokens:
        return None

    indices: list[int] = []
    seen: set[int] = set()
    for token in tokens:
        if "-" in token and not token.startswith("-"):
            parts = token.split("-", 1)
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                return None
            if start > end:
                start, end = end, start
            for n in range(start, end + 1):
                if not 1 <= n <= count:
                    return None
                if n not in seen:
                    seen.add(n)
                    indices.append(n)
        else:
            try:
                n = int(token)
            except ValueError:
                return None
            if not 1 <= n <= count:
                return None
            if n not in seen:
                seen.add(n)
                indices.append(n)

    return indices or None


def _remembered_libraries(sections: list, config: dict) -> list:
    """Return section objects matching the last saved library titles."""
    last_libraries = config.get("last_libraries")
    if not last_libraries:
        last_one = config.get("last_library", "")
        last_libraries = [last_one] if last_one else []
    if not last_libraries:
        return []
    by_title = {section.title: section for section in sections}
    return [by_title[title] for title in last_libraries if title in by_title]


def _announce_selection(selected: list, total: int) -> None:
    titles = [s.title for s in selected]
    if len(selected) == 1:
        print(f"✓ Selected library: {titles[0]}")
    elif len(selected) == total:
        print(f"✓ Selected all {len(selected)} libraries")
    else:
        print(f"✓ Selected {len(selected)} libraries: {', '.join(titles)}")


def select_libraries(sections: list, config: dict, automated: bool = False) -> list:
    """Display available libraries and let the user pick one, several, or all.

    In Automated mode the last saved selection is reused (or every library
    if none has been saved).  Returns a list of section objects (never empty).
    """
    last_libraries = config.get("last_libraries")
    if not last_libraries:
        last_one = config.get("last_library", "")
        last_libraries = [last_one] if last_one else []
    last_set = set(last_libraries)

    print("\n--- Available Libraries ---")
    for idx, section in enumerate(sections, start=1):
        marker = " ← last used" if section.title in last_set else ""
        print(f"  {idx}. {section.title} ({section.type}){marker}")

    if automated:
        selected = _remembered_libraries(sections, config)
        if not selected:
            selected = list(sections)
            print("No saved library selection – exporting all libraries.")
        _announce_selection(selected, len(sections))
        titles = [s.title for s in selected]
        config["last_library"] = titles[0]
        config["last_libraries"] = titles
        save_config(config)
        return selected

    abort_if_unattended("Library selection is required.")

    print("\n  Enter a number, comma-separated numbers (1,3,5), a range (1-3),")
    print("  or 'all' to export every library.")

    default_str = None
    if last_libraries:
        default_indices = [
            str(idx)
            for idx, section in enumerate(sections, start=1)
            if section.title in last_set
        ]
        if default_indices:
            if len(default_indices) == len(sections):
                default_str = "all"
            else:
                default_str = ",".join(default_indices)

    while True:
        prompt_msg = "Select library/libraries"
        if default_str is not None:
            prompt_msg += f" [default: {default_str}]"
        prompt_msg += ": "

        choice = input(prompt_msg).strip()
        if choice == "" and default_str is not None:
            choice = default_str

        indices = _parse_library_choice(choice, len(sections))
        if indices:
            selected = [sections[i - 1] for i in indices]
            titles = [s.title for s in selected]
            config["last_library"] = titles[0]
            config["last_libraries"] = titles
            save_config(config)
            _announce_selection(selected, len(sections))
            return selected

        print(
            f"Invalid selection. Enter a number 1–{len(sections)}, "
            "comma-separated numbers, a range, or 'all'."
        )


# ---------------------------------------------------------------------------
# Export logic
# ---------------------------------------------------------------------------

def choose_export_format(config: dict, automated: bool = False) -> str:
    """Return the export format, prompting in Interactive mode.

    Automated runs reuse ``config['export_format']`` (default: html).
    """
    saved = str(config.get("export_format", "")).strip().lower()
    if saved not in VALID_FORMATS:
        saved = ""

    if automated:
        fmt = saved or "html"
        print(f"\nUsing saved export format: {fmt}")
        return fmt

    abort_if_unattended("Export format is required.")

    while True:
        prompt = "\nExport format – enter 'csv', 'text', or 'html'"
        if saved:
            prompt += f" [last: {saved}]"
        prompt += ": "
        fmt = input(prompt).strip().lower()
        if fmt == "" and saved:
            fmt = saved
        if fmt in VALID_FORMATS:
            config["export_format"] = fmt
            save_config(config)
            return fmt
        print("Invalid choice. Please enter 'csv', 'text', or 'html'.")


def choose_filename(
    default_ext: str,
    library_name: str = None,
    last_filename: str = None,
    automated: bool = False,
) -> str:
    """Return an output filename with the correct extension.

    Interactive runs prompt (Enter reuses the last stem).  Automated runs
    reuse the last filename or a sanitised library title – never prompt.
    """
    if automated:
        resolved = apply_extension("", default_ext, last_filename)
        if resolved:
            return resolved
        stem = sanitize_filename(library_name or "library")
        return f"{stem}.{default_ext}"

    abort_if_unattended("An output filename is required.")

    last_base = os.path.splitext(last_filename)[0] if last_filename else None

    prompt = "Enter filename"
    if library_name:
        prompt = f"Filename for '{library_name}'"
    if last_base:
        prompt += f" [last: {last_base}]"
    else:
        prompt += " (e.g. titles)"
    prompt += f" (.{default_ext} added automatically): "

    while True:
        name = input(prompt).strip()
        resolved = apply_extension(name, default_ext, last_filename)
        if resolved:
            return resolved
        print("Filename cannot be empty.")


def choose_index_location(config: dict, automated: bool = False) -> str:
    """Return the path for the index.html file.

    Interactive runs prompt (Enter reuses the last location).  Automated runs
    reuse the last location or default to current directory.
    """
    last_location = config.get("index_html_path", "")
    default_location = last_location or "index.html"

    if automated:
        return default_location

    abort_if_unattended("Index file location is required.")

    prompt = "Enter location for index.html"
    if last_location:
        prompt += f" [last: {last_location}]"
    else:
        prompt += " [default: index.html]"
    prompt += ": "

    while True:
        location = input(prompt).strip()
        if location == "":
            location = default_location
        
        # Ensure it ends with .html
        if not location.lower().endswith(".html"):
            if location.endswith("/") or location.endswith(os.sep):
                location = os.path.join(location, "index.html")
            else:
                location = f"{location}.html"
        
        # Ensure it's named index.html (or in a directory)
        base_name = os.path.basename(location)
        if base_name.lower() != "index.html":
            print("Warning: The index file should be named 'index.html'.")
            confirm = input(f"Use '{location}' anyway? (y/n): ").strip().lower()
            if confirm not in ("y", "yes"):
                continue
        
        return location


def _is_movie_library(section) -> bool:
    """Return True if *section* is a Plex movie library."""
    return getattr(section, "type", "") == "movie"


def _is_show_library(section) -> bool:
    """Return True if *section* is a Plex TV show library."""
    return getattr(section, "type", "") == "show"


def _is_imdb_library(section) -> bool:
    """Return True if *section* can be rated via OMDb (movies or TV shows)."""
    return _is_movie_library(section) or _is_show_library(section)


def _omdb_type_for_section(section) -> str:
    """OMDb ``type`` query value for a movie or TV show library."""
    return "series" if _is_show_library(section) else "movie"


def _is_audiobook_library(section) -> bool:
    """Return True if *section* appears to be an audiobook library.

    Plex audiobook libraries are created as music libraries (type "artist").
    We detect them by the library type.  The user is also given a chance to
    confirm when an artist-type library is selected (see export_titles).
    """
    return getattr(section, "type", "") == "artist"


# ---------------------------------------------------------------------------
# OMDb / IMDb ratings
# ---------------------------------------------------------------------------

_IMDB_ID_RE = re.compile(r"(tt\d{7,})", re.IGNORECASE)


def extract_imdb_id(item) -> str | None:
    """Return an IMDb id (``tt1234567``) from a Plex item's guid(s), or None.

    Plex stores ids on ``item.guids`` (list of objects with ``.id``) and
    sometimes on the older singular ``item.guid`` string.  Typical values:

      ``imdb://tt0111161``
      ``com.plexapp.agents.imdb://tt0111161?lang=en``
    """
    candidates: list = []
    guids = getattr(item, "guids", None)
    if guids:
        candidates.extend(list(guids))
    single = getattr(item, "guid", None)
    if single:
        candidates.append(single)

    for guid in candidates:
        if guid is None:
            continue
        value = guid if isinstance(guid, str) else (getattr(guid, "id", None) or str(guid))
        match = _IMDB_ID_RE.search(value)
        if match:
            return match.group(1).lower()
    return None


def _title_cache_key(title: str, year=None) -> str:
    """Stable cache key for a title+year OMDb lookup."""
    y = str(year) if year not in (None, "") else ""
    return f"t:{(title or '').strip().lower()}|{y}"


def load_omdb_cache(path: str | None = None) -> dict:
    """Load the on-disk OMDb ratings cache.  Returns ``{}`` if missing."""
    cache_path = path or OMDB_CACHE_PATH
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: Could not read OMDb cache ({exc}). Starting a new cache.")
    return {}


def save_omdb_cache(cache: dict, path: str | None = None) -> None:
    """Persist the OMDb ratings cache to disk."""
    cache_path = path or OMDB_CACHE_PATH
    try:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2)
    except OSError as exc:
        print(f"Warning: Could not save OMDb cache ({exc}).")


class OmdbInvalidKeyError(Exception):
    """Raised when OMDb rejects the API key."""


def fetch_omdb_rating(
    api_key: str,
    imdb_id: str | None = None,
    title: str | None = None,
    year=None,
    media_type: str = "movie",
    opener=None,
) -> dict:
    """Look up a movie or TV show on OMDb.

    Returns a dict with ``imdb_rating`` / ``imdb_id``.  Prefers an IMDb id
    lookup; falls back to title (+ optional year).  *media_type* is the OMDb
    ``type`` parameter (``movie`` or ``series``) and is only sent on title
    searches — an IMDb id already identifies the title.  *opener* is
    ``urllib.request.urlopen``-compatible (injectable in tests).
    """
    params: dict[str, str] = {"apikey": api_key}
    if imdb_id:
        params["i"] = imdb_id
    elif title:
        params["t"] = title
        omdb_type = media_type if media_type in ("movie", "series") else "movie"
        params["type"] = omdb_type
        if year not in (None, ""):
            params["y"] = str(year)
    else:
        return {"imdb_rating": "", "imdb_id": "", "error": "no identifier"}

    url = OMDB_API_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": "PlexeeLibraryExporter/1.0"}
    )
    urlopen = opener or urllib.request.urlopen
    try:
        with urlopen(request, timeout=15) as resp:
            payload = resp.read().decode("utf-8")
        data = json.loads(payload)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        return {"imdb_rating": "", "imdb_id": imdb_id or "", "error": str(exc)}

    error = str(data.get("Error") or "")
    if "invalid api key" in error.lower():
        raise OmdbInvalidKeyError(error or "Invalid API key")

    if str(data.get("Response", "")).lower() != "true":
        return {
            "imdb_rating": "",
            "imdb_id": imdb_id or "",
            "error": error or "not found",
        }

    rating = data.get("imdbRating") or ""
    if str(rating).strip().upper() in ("N/A", "NA", ""):
        rating = ""
    return {
        "imdb_rating": str(rating),
        "imdb_id": data.get("imdbID") or imdb_id or "",
        "title": data.get("Title") or title or "",
    }


def enrich_entries_with_omdb_ratings(
    entries: list[dict],
    api_key: str,
    cache: dict | None = None,
    cache_path: str | None = None,
    opener=None,
    delay: float | None = None,
) -> dict:
    """Fill ``imdb_rating`` on movie and TV show entries.  Returns lookup stats.

    Uses *cache* (loaded from disk when omitted) so each title is fetched
    at most once.  Entries without an ``imdb_id`` key (audiobooks, photos)
    are left alone.  Title fallbacks use ``omdb_type`` (``movie`` or
    ``series``) when present on the entry.
    """
    targets = [e for e in entries if "imdb_id" in e]
    stats = {"cached": 0, "fetched": 0, "missing": 0, "skipped": 0}
    if not targets:
        return stats

    own_cache = cache is None
    if cache is None:
        cache = load_omdb_cache(cache_path)
    wait = OMDB_REQUEST_DELAY if delay is None else delay
    cache_dirty = False
    invalid_key = False

    print(f"  Looking up IMDb ratings for {len(targets)} title(s) via OMDb…")
    for index, entry in enumerate(targets, start=1):
        imdb_id = (entry.get("imdb_id") or "").strip()
        title = entry.get("title") or ""
        year = entry.get("year")
        cache_key = imdb_id.lower() if imdb_id else _title_cache_key(title, year)

        cached_row = cache.get(cache_key)
        if cached_row is None and imdb_id:
            cached_row = cache.get(_title_cache_key(title, year))
        if cached_row is not None:
            entry["imdb_rating"] = cached_row.get("imdb_rating", "") or ""
            if cached_row.get("imdb_id") and not entry.get("imdb_id"):
                entry["imdb_id"] = cached_row["imdb_id"]
            stats["cached"] += 1
            if not entry["imdb_rating"]:
                stats["missing"] += 1
            continue

        if invalid_key:
            entry["imdb_rating"] = ""
            stats["skipped"] += 1
            continue

        try:
            result = fetch_omdb_rating(
                api_key,
                imdb_id=imdb_id or None,
                title=title,
                year=year,
                media_type=entry.get("omdb_type") or "movie",
                opener=opener,
            )
        except OmdbInvalidKeyError as exc:
            print(f"  Error: OMDb API key rejected ({exc}). Skipping remaining lookups.")
            invalid_key = True
            entry["imdb_rating"] = ""
            stats["skipped"] += 1
            continue

        if wait:
            time.sleep(wait)

        stats["fetched"] += 1
        rating = (result or {}).get("imdb_rating", "") or ""
        resolved_id = (result or {}).get("imdb_id", "") or imdb_id
        error = str((result or {}).get("error") or "")
        entry["imdb_rating"] = rating
        if resolved_id:
            entry["imdb_id"] = resolved_id
        if not rating:
            stats["missing"] += 1

        # Cache hits and "not found"; skip transient network errors so later runs retry.
        if error and "not found" not in error.lower():
            continue

        record = {"imdb_rating": rating, "imdb_id": resolved_id, "title": title}
        cache[cache_key] = record
        if resolved_id:
            cache[resolved_id.lower()] = record
        cache_dirty = True

        if index % 25 == 0 or index == len(targets):
            print(f"    Progress: {index}/{len(targets)}")

    if own_cache and cache_dirty:
        save_omdb_cache(cache, cache_path)

    print(
        f"  Ratings: {stats['cached']} cached, {stats['fetched']} fetched, "
        f"{stats['missing']} missing"
        + (f", {stats['skipped']} skipped" if stats["skipped"] else "")
        + "."
    )
    return stats


def choose_omdb_settings(
    config: dict,
    sections: list,
    automated: bool = False,
) -> str | None:
    """Return an OMDb API key when IMDb ratings should be fetched.

    Movie and TV show libraries use ratings.  Interactive runs prompt
    (Enter reuses a saved key, ``skip`` disables).  Automated runs reuse
    the saved key or skip silently when none is configured.
    """
    if not any(_is_imdb_library(section) for section in sections):
        return None

    saved_key = str(config.get("omdb_api_key", "")).strip()
    enabled = config.get("omdb_enabled")

    if automated:
        if enabled is False or not saved_key:
            if not saved_key:
                print("OMDb API key not configured – skipping IMDb ratings.")
            else:
                print("IMDb ratings disabled in config – skipping.")
            return None
        print("Using saved OMDb API key for IMDb ratings.")
        return saved_key

    abort_if_unattended("An OMDb API key is required to fetch IMDb ratings.")

    print("\n--- IMDb Ratings (movie and TV show libraries) ---")
    print("  Ratings come from OMDb (https://www.omdbapi.com/).")
    print("  Get a free key at that site.  Press Enter to skip.")
    if saved_key:
        prompt = "OMDb API key [saved key on file; Enter to reuse, 'skip' to disable]: "
    else:
        prompt = "Enter OMDb API key (or press Enter to skip): "

    value = input(prompt).strip()
    if value.lower() in ("skip", "n", "no", "disable", "off"):
        config["omdb_enabled"] = False
        save_config(config)
        print("IMDb ratings disabled.")
        return None
    if value == "":
        if saved_key:
            config["omdb_enabled"] = True
            save_config(config)
            return saved_key
        config["omdb_enabled"] = False
        save_config(config)
        print("Skipping IMDb ratings.")
        return None

    config["omdb_api_key"] = value
    config["omdb_enabled"] = True
    save_config(config)
    print("✓ OMDb API key saved.")
    return value


def _fetch_audiobook_titles(section) -> list[dict]:
    """Retrieve book titles from an audiobook (music-type) library.

    Audiobooks are structured as Artist (author) → Album (book).
    We use ``section.searchAlbums()`` to get all albums in one call,
    then read each album's title and its parent artist (author) name.

    Returns a list of dicts: [{"title": ..., "author": ..., "added_at": ...}, ...]
    """
    print("  Detected audiobook/music library – fetching albums (book titles)…")
    try:
        albums = section.searchAlbums()
    except Exception as exc:
        print(f"Error fetching albums: {exc}")
        sys.exit(1)

    results = []
    for album in albums:
        title = album.title
        # parentTitle is the artist (author) name.
        author = getattr(album, "parentTitle", "") or ""
        # addedAt is a datetime object or None.
        added_at = getattr(album, "addedAt", None)
        results.append({"title": title, "author": author, "added_at": added_at})

    return results


def _fetch_standard_titles(section) -> list[dict]:
    """Retrieve titles from a standard (movie / TV show / photo) library.

    Movie and TV show libraries also capture IMDb id and year so OMDb can
    look up ratings.  ``omdb_type`` is ``movie`` or ``series``.

    Returns a list of dicts: [{"title": ..., "added_at": ...}, ...]
    """
    try:
        items = section.all()
    except Exception as exc:
        print(f"Error fetching library items: {exc}")
        sys.exit(1)

    is_imdb = _is_imdb_library(section)
    omdb_type = _omdb_type_for_section(section) if is_imdb else None
    results = []
    for item in items:
        title = item.title
        added_at = getattr(item, "addedAt", None)
        entry = {"title": title, "added_at": added_at}
        if is_imdb:
            entry["imdb_id"] = extract_imdb_id(item) or ""
            year = getattr(item, "year", None)
            entry["year"] = year if year not in (None, 0, "0") else None
            entry["omdb_type"] = omdb_type
        results.append(entry)

    return results


def _format_date(dt) -> str:
    """Format a datetime object as YYYY-MM-DD or return empty string if None."""
    if dt is None:
        return ""
    try:
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _export_html(
    entries: list[dict],
    library_name: str,
    filename: str,
    include_author: bool = False,
    include_library: bool = False,
    include_rating: bool = False,
) -> None:
    """Generate a modern HTML5 page with a sortable table of library entries."""
    
    # HTML template with inline CSS and JavaScript for sorting
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{library_name} - Plexee Library Export</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Courier New', 'Monaco', 'Consolas', monospace;
            background: #000000;
            color: #00ff00;
            padding: 20px;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #000000;
            border: 2px solid #00ff00;
            box-shadow: 0 0 20px rgba(0, 255, 0, 0.3);
            overflow: hidden;
        }}
        
        header {{
            background: #000000;
            color: #00ff00;
            padding: 30px;
            text-align: center;
            border-bottom: 2px solid #00ff00;
        }}
        
        header h1 {{
            font-size: 2em;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 3px;
            text-shadow: 0 0 10px #00ff00;
        }}
        
        header p {{
            font-size: 1.1em;
            opacity: 0.8;
        }}
        
        .stats {{
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-top: 20px;
            padding: 15px;
            background: rgba(0, 255, 0, 0.05);
            border: 1px solid #00ff00;
        }}
        
        .stat {{
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #00ff00;
            text-shadow: 0 0 10px #00ff00;
        }}
        
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.7;
            text-transform: uppercase;
        }}
        
        .table-container {{
            padding: 30px;
            overflow-x: auto;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.95em;
        }}
        
        thead {{
            background: rgba(0, 255, 0, 0.1);
            position: sticky;
            top: 0;
        }}
        
        th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            color: #00ff00;
            cursor: pointer;
            user-select: none;
            transition: background 0.2s;
            position: relative;
            border: 1px solid #00ff00;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        th:hover {{
            background: rgba(0, 255, 0, 0.2);
            text-shadow: 0 0 10px #00ff00;
        }}
        
        th.sortable::after {{
            content: ' ⇅';
            opacity: 0.5;
            font-size: 0.8em;
        }}
        
        th.sorted-asc::after {{
            content: ' ↑';
            opacity: 1;
            color: #00ff00;
            text-shadow: 0 0 10px #00ff00;
        }}
        
        th.sorted-desc::after {{
            content: ' ↓';
            opacity: 1;
            color: #00ff00;
            text-shadow: 0 0 10px #00ff00;
        }}
        
        tbody tr {{
            border-bottom: 1px solid #00ff00;
            transition: background 0.2s;
        }}
        
        tbody tr:hover {{
            background: rgba(0, 255, 0, 0.1);
        }}
        
        td {{
            padding: 15px;
            color: #00ff00;
            border: 1px solid rgba(0, 255, 0, 0.3);
        }}
        
        .title-cell {{
            font-weight: 500;
        }}
        
        .date-cell {{
            color: #00cc00;
            white-space: nowrap;
        }}
        
        .author-cell {{
            color: #00dd00;
        }}
        
        .library-cell {{
            color: #00cc66;
        }}
        
        .rating-cell {{
            color: #88ff00;
            white-space: nowrap;
            font-weight: bold;
        }}
        
        a.imdb-link {{
            color: #00ff00;
            text-decoration: underline;
            text-underline-offset: 3px;
        }}
        
        a.imdb-link:hover {{
            color: #88ff00;
            text-shadow: 0 0 8px #00ff00;
        }}
        
        footer {{
            text-align: center;
            padding: 20px;
            color: #00ff00;
            font-size: 0.9em;
            border-top: 2px solid #00ff00;
            opacity: 0.7;
        }}
        
        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}
            
            header {{
                padding: 20px;
            }}
            
            header h1 {{
                font-size: 1.5em;
            }}
            
            .table-container {{
                padding: 15px;
            }}
            
            th, td {{
                padding: 10px;
                font-size: 0.9em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{library_name}</h1>
            <p>Plexee Library Export</p>
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{total_count}</div>
                    <div class="stat-label">Total Items</div>
                </div>
            </div>
        </header>
        
        <div class="table-container">
            <table id="libraryTable">
                <thead>
                    <tr>
{headers}
                    </tr>
                </thead>
                <tbody>
{rows}
                </tbody>
            </table>
        </div>
        
        <footer>
            <p>Generated by Plexee Library Exporter • {timestamp}</p>
        </footer>
    </div>
    
    <script>
        // Simple table sorting functionality
        document.addEventListener('DOMContentLoaded', function() {{
            const table = document.getElementById('libraryTable');
            const headers = table.querySelectorAll('th.sortable');
            
            headers.forEach((header, index) => {{
                header.addEventListener('click', () => {{
                    sortTable(index, header);
                }});
            }});
            
            function sortTable(columnIndex, header, forceDescending = false) {{
                const tbody = table.querySelector('tbody');
                const rows = Array.from(tbody.querySelectorAll('tr'));
                const isAscending = forceDescending ? false : !header.classList.contains('sorted-asc');
                
                // Remove sorting classes from all headers
                headers.forEach(h => {{
                    h.classList.remove('sorted-asc', 'sorted-desc');
                }});
                
                // Add appropriate class to current header
                header.classList.add(isAscending ? 'sorted-asc' : 'sorted-desc');
                
                // Sort rows
                rows.sort((a, b) => {{
                    const aValue = a.cells[columnIndex].textContent.trim();
                    const bValue = b.cells[columnIndex].textContent.trim();
                    
                    // Try to parse as date first (YYYY-MM-DD)
                    const aDate = new Date(aValue);
                    const bDate = new Date(bValue);
                    const looksLikeDate = (v) => /^\d{{4}}-\d{{2}}-\d{{2}}/.test(v);
                    
                    if (looksLikeDate(aValue) && looksLikeDate(bValue) && !isNaN(aDate) && !isNaN(bDate)) {{
                        return isAscending ? aDate - bDate : bDate - aDate;
                    }}
                    
                    // Numeric compare (IMDb ratings such as 8.8 / 10)
                    const aNum = parseFloat(aValue);
                    const bNum = parseFloat(bValue);
                    const looksLikeNumber = (v) => /^-?\d+(\.\d+)?$/.test(v);
                    if (looksLikeNumber(aValue) && looksLikeNumber(bValue) && !isNaN(aNum) && !isNaN(bNum)) {{
                        return isAscending ? aNum - bNum : bNum - aNum;
                    }}
                    
                    // Otherwise compare as strings
                    return isAscending 
                        ? aValue.localeCompare(bValue)
                        : bValue.localeCompare(aValue);
                }});
                
                // Reorder rows in the table
                rows.forEach(row => tbody.appendChild(row));
            }}
            
            // Default sort: Date Added column, newest first (descending)
            const dateColumnIndex = headers.length - 1; // Date Added is always the last column
            sortTable(dateColumnIndex, headers[dateColumnIndex], true);
        }});
    </script>
</body>
</html>"""
    
    # Generate table headers.  Date Added is always last so the default
    # sort (newest first) can target headers.length - 1.
    header_cells = ['                        <th class="sortable">Title</th>']
    if include_library:
        header_cells.append('                        <th class="sortable">Library</th>')
    if include_author:
        header_cells.append('                        <th class="sortable">Author</th>')
    if include_rating:
        header_cells.append('                        <th class="sortable">IMDb Rating</th>')
    header_cells.append('                        <th class="sortable">Date Added</th>')
    headers = "\n".join(header_cells)

    def _esc(value: str) -> str:
        return (
            (value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def _imdb_title_html(entry: dict) -> str:
        """Title text, or a link to IMDb when a valid id is present."""
        title = _esc(entry.get("title", ""))
        imdb_id = (entry.get("imdb_id") or "").strip().lower()
        if not re.fullmatch(r"tt\d{7,}", imdb_id):
            return title
        href = f"https://www.imdb.com/title/{imdb_id}/"
        return (
            f'<a class="imdb-link" href="{href}" '
            f'target="_blank" rel="noopener noreferrer">{title}</a>'
        )

    # Generate table rows
    rows_html = []
    for entry in entries:
        title_html = _imdb_title_html(entry)
        date_added = _format_date(entry.get("added_at"))
        cells = [f'                        <td class="title-cell">{title_html}</td>']
        if include_library:
            library = _esc(entry.get("library", ""))
            cells.append(f'                        <td class="library-cell">{library}</td>')
        if include_author:
            author = _esc(entry.get("author", ""))
            cells.append(f'                        <td class="author-cell">{author}</td>')
        if include_rating:
            rating = _esc(entry.get("imdb_rating", ""))
            cells.append(f'                        <td class="rating-cell">{rating}</td>')
        cells.append(f'                        <td class="date-cell">{date_added}</td>')
        row = "                    <tr>\n" + "\n".join(cells) + "\n                    </tr>"
        rows_html.append(row)
    
    # Get current timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Fill in template
    html_content = html_template.format(
        library_name=library_name,
        total_count=len(entries),
        headers=headers,
        rows="\n".join(rows_html),
        timestamp=timestamp
    )
    
    # Write to file
    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(html_content)


def _fetch_section_entries(section) -> list[dict]:
    """Fetch titles from *section* and tag each entry with the library name."""
    print(f"Fetching items from '{section.title}'…")
    if _is_audiobook_library(section):
        entries = _fetch_audiobook_titles(section)
    else:
        entries = _fetch_standard_titles(section)
    for entry in entries:
        entry["library"] = section.title
    print(f"  Found {len(entries)} title(s).")
    return entries


def _display_name(sections: list) -> str:
    """Human-readable name for the export heading / HTML title."""
    if len(sections) == 1:
        return sections[0].title
    return f"{len(sections)} Libraries"


def export_titles(
    sections: list,
    fmt: str,
    filename: str,
    omdb_api_key: str | None = None,
    omdb_cache: dict | None = None,
) -> None:
    """Fetch items from one or more library sections and write them to
    *filename* in the requested format.

    For audiobook / music libraries the function drills down to the album
    level (artist → album) so that actual book titles are exported instead
    of author names.

    When more than one library is selected, a Library column is included
    (CSV / HTML) so titles can be distinguished.  Audiobook Author columns
    are included whenever any selected library is an audiobook library.

    When *omdb_api_key* is set, movie and TV show libraries get an IMDb
    Rating column (CSV / HTML) or a ``(7.5)`` suffix (text).  HTML titles
    link to IMDb when an id is available.
    """
    entries: list[dict] = []
    for section in sections:
        entries.extend(_fetch_section_entries(section))

    if not entries:
        print("The selected library/libraries are empty – nothing to export.")
        return

    include_library = len(sections) > 1
    include_author = any("author" in e for e in entries)
    include_rating = False
    if omdb_api_key and any("imdb_id" in e for e in entries):
        enrich_entries_with_omdb_ratings(entries, omdb_api_key, cache=omdb_cache)
        include_rating = True
    display_name = _display_name(sections)

    print(f"Writing {len(entries)} title(s) to '{filename}'…")

    try:
        if fmt == "csv":
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                header = ["Title"]
                if include_library:
                    header.append("Library")
                if include_author:
                    header.append("Author")
                if include_rating:
                    header.append("IMDb Rating")
                header.append("Date Added")
                writer.writerow(header)
                for entry in entries:
                    row = [entry["title"]]
                    if include_library:
                        row.append(entry.get("library", ""))
                    if include_author:
                        row.append(entry.get("author", ""))
                    if include_rating:
                        row.append(entry.get("imdb_rating", ""))
                    row.append(_format_date(entry.get("added_at")))
                    writer.writerow(row)
        elif fmt == "html":
            _export_html(
                entries,
                display_name,
                filename,
                include_author=include_author,
                include_library=include_library,
                include_rating=include_rating,
            )
        else:
            # Plain text – one title per line.
            # Multi-library: "Title [Library]"; audiobooks: "Title by Author".
            # Movies and TV shows with ratings: "Title (7.5)".
            with open(filename, "w", encoding="utf-8") as fh:
                for entry in entries:
                    line = entry["title"]
                    if include_author and entry.get("author"):
                        line = f"{line} by {entry['author']}"
                    if include_rating and entry.get("imdb_rating"):
                        line = f"{line} ({entry['imdb_rating']})"
                    if include_library and entry.get("library"):
                        line = f"{line} [{entry['library']}]"
                    fh.write(line + "\n")
    except OSError as exc:
        print(f"Error writing file: {exc}")
        sys.exit(1)

    print(f"✓ Export complete! {len(entries)} title(s) saved to '{filename}'.")


def create_index_page(library_files: list[tuple[str, str]], index_path: str = "index.html") -> None:
    """Create an index.html page with links to each exported HTML file.
    
    *library_files* is a list of (library_name, filename) tuples.
    *index_path* is the full path where the index.html will be written.
    """
    index_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Library Index - Plexee Library Exporter</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Courier New', 'Monaco', 'Consolas', monospace;
            background: #000000;
            color: #00ff00;
            padding: 20px;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: #000000;
            border: 2px solid #00ff00;
            box-shadow: 0 0 20px rgba(0, 255, 0, 0.3);
            overflow: hidden;
        }}
        
        header {{
            background: #000000;
            color: #00ff00;
            padding: 30px;
            text-align: center;
            border-bottom: 2px solid #00ff00;
        }}
        
        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 3px;
            text-shadow: 0 0 10px #00ff00;
        }}
        
        header p {{
            font-size: 1.1em;
            opacity: 0.8;
        }}
        
        .stats {{
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-top: 20px;
            padding: 15px;
            background: rgba(0, 255, 0, 0.05);
            border: 1px solid #00ff00;
        }}
        
        .stat {{
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #00ff00;
            text-shadow: 0 0 10px #00ff00;
        }}
        
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.7;
            text-transform: uppercase;
        }}
        
        .content {{
            padding: 40px;
        }}
        
        .library-grid {{
            display: grid;
            gap: 20px;
            margin-top: 20px;
        }}
        
        .library-button {{
            display: block;
            padding: 20px 30px;
            background: rgba(0, 255, 0, 0.05);
            border: 2px solid #00ff00;
            color: #00ff00;
            text-decoration: none;
            text-align: center;
            font-size: 1.2em;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            transition: all 0.3s;
            box-shadow: 0 0 10px rgba(0, 255, 0, 0.2);
        }}
        
        .library-button:hover {{
            background: rgba(0, 255, 0, 0.15);
            box-shadow: 0 0 20px rgba(0, 255, 0, 0.5);
            text-shadow: 0 0 10px #00ff00;
            transform: translateY(-2px);
        }}
        
        .library-button:active {{
            transform: translateY(0);
        }}
        
        .library-name {{
            display: block;
            margin-bottom: 5px;
        }}
        
        .library-arrow {{
            font-size: 0.8em;
            opacity: 0.7;
        }}
        
        footer {{
            text-align: center;
            padding: 20px;
            color: #00ff00;
            font-size: 0.9em;
            border-top: 2px solid #00ff00;
            opacity: 0.7;
        }}
        
        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}
            
            header {{
                padding: 20px;
            }}
            
            header h1 {{
                font-size: 1.8em;
            }}
            
            .content {{
                padding: 20px;
            }}
            
            .library-button {{
                padding: 15px 20px;
                font-size: 1em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Library Index</h1>
            <p>Plexee Library Exporter</p>
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{library_count}</div>
                    <div class="stat-label">Exported Libraries</div>
                </div>
            </div>
        </header>
        
        <div class="content">
            <div class="library-grid">
{library_buttons}
            </div>
        </div>
        
        <footer>
            <p>Generated by Plexee Library Exporter • {timestamp}</p>
        </footer>
    </div>
</body>
</html>"""

    def _esc(value: str) -> str:
        return (
            (value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    # Generate library buttons
    button_html = []
    index_dir = os.path.dirname(os.path.abspath(index_path))
    
    for library_name, filename in library_files:
        # Make the link relative to the index.html location
        abs_filename = os.path.abspath(filename)
        try:
            rel_path = os.path.relpath(abs_filename, index_dir)
        except ValueError:
            # On Windows, relpath fails if paths are on different drives
            rel_path = abs_filename
        
        button = f'''                <a href="{_esc(rel_path)}" class="library-button">
                    <span class="library-name">{_esc(library_name)}</span>
                    <span class="library-arrow">→</span>
                </a>'''
        button_html.append(button)
    
    # Get current timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Fill in template
    html_content = index_template.format(
        library_count=len(library_files),
        library_buttons="\n".join(button_html),
        timestamp=timestamp
    )
    
    # Write to the specified index path
    try:
        # Create directory if it doesn't exist
        index_dir = os.path.dirname(index_path)
        if index_dir and not os.path.exists(index_dir):
            os.makedirs(index_dir, exist_ok=True)
        
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(html_content)
        print(f"✓ Index page created: {index_path}")
    except OSError as exc:
        print(f"Warning: Could not create index page: {exc}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Plex library titles to CSV, text, or HTML."
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Re-run first-time prompts (mode, and later libraries/format/filenames).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    print("=" * 50)
    print("       Plexee Library Exporter")
    print("=" * 50)

    # Step 1 – Load any saved configuration and resolve run mode.
    config = load_config()
    mode, just_configured = ensure_mode(config, force_setup=args.setup)
    # First-run / --setup still prompts for libraries, format, and filenames
    # even when the saved mode is Automated, so cron has settings to reuse.
    automated = mode == MODE_AUTOMATED and not just_configured
    label = "Automated" if mode == MODE_AUTOMATED else "Interactive Manual"
    print(f"Mode: {label}")
    if automated:
        print("Automated mode – using saved settings (no prompts).")
    elif mode == MODE_AUTOMATED and just_configured:
        print("Automated mode configured – collecting export settings for later runs.")

    # Step 2 – Connect to the Plex server (prompt if needed).
    server = establish_connection(config, automated=automated)

    # Step 3 – Discover libraries.
    sections = discover_libraries(server)

    # Step 4 – Pick one, several, or all libraries.
    selected = select_libraries(sections, config, automated=automated)

    # Step 4b – Optional OMDb API key for IMDb ratings on movie and TV libraries.
    omdb_api_key = choose_omdb_settings(config, selected, automated=automated)
    omdb_cache = load_omdb_cache() if omdb_api_key else None

    # Step 5 – Choose export format.
    fmt = choose_export_format(config, automated=automated)
    default_ext = extension_for_format(fmt)

    # Step 5b – If HTML format, choose index location before library exports
    index_path = None
    if fmt == "html":
        index_path = choose_index_location(config, automated=automated)
        config["index_html_path"] = index_path
        save_config(config)
        print(f"Index page will be created at: {index_path}")

    # Step 6 – For each library, resolve filename and export.
    library_filenames = config.get("library_filenames") or {}

    if len(selected) > 1:
        print(f"\n--- Exporting {len(selected)} libraries ---")

    # Track exported HTML files for index page generation
    exported_html_files = []

    for section in selected:
        last_filename = library_filenames.get(section.title)
        filename = choose_filename(
            default_ext,
            section.title,
            last_filename,
            automated=automated,
        )
        print(f"Output file for '{section.title}': {filename}")

        library_filenames[section.title] = filename
        config["library_filenames"] = library_filenames
        config["export_format"] = fmt
        save_config(config)

        export_titles(
            [section],
            fmt,
            filename,
            omdb_api_key=omdb_api_key,
            omdb_cache=omdb_cache,
        )
        
        # Track HTML exports for index page
        if fmt == "html":
            exported_html_files.append((section.title, filename))
        
        print()

    if omdb_api_key and omdb_cache is not None:
        save_omdb_cache(omdb_cache)

    # Step 7 – Create index.html if HTML format was used
    if fmt == "html" and exported_html_files:
        print("--- Creating Index Page ---")
        create_index_page(exported_html_files, index_path)


if __name__ == "__main__":
    main()
