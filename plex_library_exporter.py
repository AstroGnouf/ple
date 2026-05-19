#!/usr/bin/env python3
"""
Plex Library Exporter
=====================
A command-line tool that connects to a Plex Media Server and exports
library titles to CSV or plain-text files.

Usage:
    python3 plex_library_exporter.py

On first run the tool prompts for server hostname/IP and API token,
validates the connection, discovers available libraries, and saves the
configuration to config.json so subsequent runs remember the server
and last-selected library.
"""

import csv
import json
import os
import sys

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


# ---------------------------------------------------------------------------
# Plex connection
# ---------------------------------------------------------------------------

def connect_to_plex(base_url: str, token: str) -> PlexServer:
    """Attempt to connect to the Plex server and return a PlexServer instance.

    Raises an exception on failure so the caller can handle retries.
    """
    # Ensure the URL has a scheme.
    if not base_url.startswith(("http://", "https://")):
        base_url = f"http://{base_url}"
    # Append default Plex port if none was specified.
    # (Only when there is no port after the host.)
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    if parsed.port is None:
        base_url = f"{base_url}:32400"

    server = PlexServer(base_url, token)
    return server


def prompt_for_credentials() -> tuple:
    """Interactively ask the user for Plex server address and API token."""
    print("\n--- Plex Server Configuration ---")
    host = input("Enter Plex server hostname or IP address (e.g. 192.168.1.100): ").strip()
    token = input("Enter your Plex API token: ").strip()
    return host, token


def establish_connection(config: dict) -> PlexServer:
    """Try to connect using saved config or prompt the user. Allows retries on
    failure. Returns a connected PlexServer instance and updates *config*
    in-place with the validated credentials."""

    host = config.get("host", "")
    token = config.get("token", "")

    # If we already have saved credentials, try them first.
    if host and token:
        print(f"\nConnecting to saved server ({host})…")
        try:
            server = connect_to_plex(host, token)
            print(f"✓ Successfully connected to '{server.friendlyName}'.")
            return server
        except Unauthorized:
            print("✗ Connection failed: invalid or expired API token.")
        except Exception as exc:
            print(f"✗ Connection failed: {exc}")
        print("Saved credentials did not work. Please re-enter them.\n")

    # Interactive prompt loop with retry support.
    while True:
        host, token = prompt_for_credentials()
        if not host or not token:
            print("Error: Both hostname and token are required.")
            continue
        print(f"Connecting to {host}…")
        try:
            server = connect_to_plex(host, token)
            print(f"✓ Successfully connected to '{server.friendlyName}'.")
            # Persist validated credentials.
            config["host"] = host
            config["token"] = token
            save_config(config)
            return server
        except Unauthorized:
            print("✗ Connection failed: invalid or expired API token.")
        except Exception as exc:
            print(f"✗ Connection failed: {exc}")

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


def select_library(sections: list, config: dict) -> object:
    """Display available libraries, highlight the previously selected one (if
    any), and let the user choose. Returns the chosen library section."""

    last_library = config.get("last_library", "")

    print("\n--- Available Libraries ---")
    for idx, section in enumerate(sections, start=1):
        marker = " ← last used" if section.title == last_library else ""
        print(f"  {idx}. {section.title} ({section.type}){marker}")

    # Determine a default selection based on last-used library.
    default_idx = None
    for idx, section in enumerate(sections, start=1):
        if section.title == last_library:
            default_idx = idx
            break

    while True:
        prompt_msg = "Select a library by number"
        if default_idx is not None:
            prompt_msg += f" [default: {default_idx}]"
        prompt_msg += ": "

        choice = input(prompt_msg).strip()
        if choice == "" and default_idx is not None:
            choice = str(default_idx)

        try:
            choice_int = int(choice)
            if 1 <= choice_int <= len(sections):
                selected = sections[choice_int - 1]
                # Remember this selection for next time.
                config["last_library"] = selected.title
                save_config(config)
                print(f"✓ Selected library: {selected.title}")
                return selected
        except ValueError:
            pass
        print(f"Invalid selection. Please enter a number between 1 and {len(sections)}.")


# ---------------------------------------------------------------------------
# Export logic
# ---------------------------------------------------------------------------

def choose_export_format() -> str:
    """Ask the user whether to export as CSV or plain text."""
    while True:
        fmt = input("\nExport format – enter 'csv' or 'text': ").strip().lower()
        if fmt in ("csv", "text"):
            return fmt
        print("Invalid choice. Please enter 'csv' or 'text'.")


def choose_filename(default_ext: str) -> str:
    """Prompt for an output filename, suggesting a sensible default extension."""
    while True:
        name = input(f"Enter output filename (e.g. titles.{default_ext}): ").strip()
        if name:
            return name
        print("Filename cannot be empty.")


def export_titles(section, fmt: str, filename: str) -> None:
    """Fetch all items from the selected library section and write their
    titles to *filename* in the requested format."""

    print(f"Fetching items from '{section.title}'…")
    try:
        items = section.all()
    except Exception as exc:
        print(f"Error fetching library items: {exc}")
        sys.exit(1)

    if not items:
        print("The selected library is empty – nothing to export.")
        return

    titles = [item.title for item in items]
    print(f"Found {len(titles)} title(s). Writing to '{filename}'…")

    try:
        if fmt == "csv":
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Title"])  # Header row
                for title in titles:
                    writer.writerow([title])
        else:
            # Plain text – one title per line, no header.
            with open(filename, "w", encoding="utf-8") as fh:
                for title in titles:
                    fh.write(title + "\n")
    except OSError as exc:
        print(f"Error writing file: {exc}")
        sys.exit(1)

    print(f"✓ Export complete! {len(titles)} title(s) saved to '{filename}'.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("       Plex Library Exporter")
    print("=" * 50)

    # Step 1 – Load any saved configuration.
    config = load_config()

    # Step 2 – Connect to the Plex server (prompt if needed).
    server = establish_connection(config)

    # Step 3 – Discover libraries.
    sections = discover_libraries(server)

    # Step 4 – Let the user pick a library.
    selected = select_library(sections, config)

    # Step 5 – Choose export format and filename.
    fmt = choose_export_format()
    default_ext = "csv" if fmt == "csv" else "txt"
    filename = choose_filename(default_ext)

    # Step 6 – Export!
    export_titles(selected, fmt, filename)


if __name__ == "__main__":
    main()
