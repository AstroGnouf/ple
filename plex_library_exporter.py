#!/usr/bin/env python3
"""
Plexee Library Exporter
=======================
A command-line tool that connects to a Plex Media Server and exports
library titles to CSV, plain-text, or HTML files.  One, several, or
all libraries can be exported in a single run.

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
import traceback

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


def establish_connection(config: dict) -> PlexServer:
    """Try to connect using saved config or prompt the user. Allows retries on
    failure. Returns a connected PlexServer instance and updates *config*
    in-place with the validated credentials."""

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
        print("Saved credentials did not work. Please re-enter them.\n")

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


def select_libraries(sections: list, config: dict) -> list:
    """Display available libraries and let the user pick one, several, or all.

    Returns a list of chosen library section objects (never empty).
    """
    last_libraries = config.get("last_libraries")
    if not last_libraries:
        # Backward compatibility with the old single-library key.
        last_one = config.get("last_library", "")
        last_libraries = [last_one] if last_one else []

    last_set = set(last_libraries)

    print("\n--- Available Libraries ---")
    for idx, section in enumerate(sections, start=1):
        marker = " ← last used" if section.title in last_set else ""
        print(f"  {idx}. {section.title} ({section.type}){marker}")

    print("\n  Enter a number, comma-separated numbers (1,3,5), a range (1-3),")
    print("  or 'all' to export every library.")

    # Build a default string from the previously selected libraries.
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
            if len(selected) == 1:
                print(f"✓ Selected library: {titles[0]}")
            elif len(selected) == len(sections):
                print(f"✓ Selected all {len(selected)} libraries")
            else:
                print(f"✓ Selected {len(selected)} libraries: {', '.join(titles)}")
            return selected

        print(
            f"Invalid selection. Enter a number 1–{len(sections)}, "
            "comma-separated numbers, a range, or 'all'."
        )


# ---------------------------------------------------------------------------
# Export logic
# ---------------------------------------------------------------------------

def choose_export_format() -> str:
    """Ask the user whether to export as CSV, plain text, or HTML."""
    while True:
        fmt = input("\nExport format – enter 'csv', 'text', or 'html': ").strip().lower()
        if fmt in ("csv", "text", "html"):
            return fmt
        print("Invalid choice. Please enter 'csv', 'text', or 'html'.")


def choose_filename(default_ext: str) -> str:
    """Prompt for an output filename, suggesting a sensible default extension."""
    while True:
        name = input(f"Enter output filename (e.g. titles.{default_ext}): ").strip()
        if name:
            return name
        print("Filename cannot be empty.")


def _is_audiobook_library(section) -> bool:
    """Return True if *section* appears to be an audiobook library.

    Plex audiobook libraries are created as music libraries (type "artist").
    We detect them by the library type.  The user is also given a chance to
    confirm when an artist-type library is selected (see export_titles).
    """
    return getattr(section, "type", "") == "artist"


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

    Returns a list of dicts: [{"title": ..., "added_at": ...}, ...]
    """
    try:
        items = section.all()
    except Exception as exc:
        print(f"Error fetching library items: {exc}")
        sys.exit(1)

    results = []
    for item in items:
        title = item.title
        added_at = getattr(item, "addedAt", None)
        results.append({"title": title, "added_at": added_at})
    
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
                    
                    // Try to parse as date first
                    const aDate = new Date(aValue);
                    const bDate = new Date(bValue);
                    
                    if (!isNaN(aDate) && !isNaN(bDate)) {{
                        return isAscending ? aDate - bDate : bDate - aDate;
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
    header_cells.append('                        <th class="sortable">Date Added</th>')
    headers = "\n".join(header_cells)

    def _esc(value: str) -> str:
        return (
            (value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    # Generate table rows
    rows_html = []
    for entry in entries:
        title = _esc(entry.get("title", ""))
        date_added = _format_date(entry.get("added_at"))
        cells = [f'                        <td class="title-cell">{title}</td>']
        if include_library:
            library = _esc(entry.get("library", ""))
            cells.append(f'                        <td class="library-cell">{library}</td>')
        if include_author:
            author = _esc(entry.get("author", ""))
            cells.append(f'                        <td class="author-cell">{author}</td>')
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


def export_titles(sections: list, fmt: str, filename: str) -> None:
    """Fetch items from one or more library sections and write them to
    *filename* in the requested format.

    For audiobook / music libraries the function drills down to the album
    level (artist → album) so that actual book titles are exported instead
    of author names.

    When more than one library is selected, a Library column is included
    (CSV / HTML) so titles can be distinguished.  Audiobook Author columns
    are included whenever any selected library is an audiobook library.
    """
    entries: list[dict] = []
    for section in sections:
        entries.extend(_fetch_section_entries(section))

    if not entries:
        print("The selected library/libraries are empty – nothing to export.")
        return

    include_library = len(sections) > 1
    include_author = any("author" in e for e in entries)
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
                header.append("Date Added")
                writer.writerow(header)
                for entry in entries:
                    row = [entry["title"]]
                    if include_library:
                        row.append(entry.get("library", ""))
                    if include_author:
                        row.append(entry.get("author", ""))
                    row.append(_format_date(entry.get("added_at")))
                    writer.writerow(row)
        elif fmt == "html":
            _export_html(
                entries,
                display_name,
                filename,
                include_author=include_author,
                include_library=include_library,
            )
        else:
            # Plain text – one title per line.
            # Multi-library: "Title [Library]"; audiobooks: "Title by Author".
            with open(filename, "w", encoding="utf-8") as fh:
                for entry in entries:
                    line = entry["title"]
                    if include_author and entry.get("author"):
                        line = f"{line} by {entry['author']}"
                    if include_library and entry.get("library"):
                        line = f"{line} [{entry['library']}]"
                    fh.write(line + "\n")
    except OSError as exc:
        print(f"Error writing file: {exc}")
        sys.exit(1)

    print(f"✓ Export complete! {len(entries)} title(s) saved to '{filename}'.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("       Plexee Library Exporter")
    print("=" * 50)

    # Step 1 – Load any saved configuration.
    config = load_config()

    # Step 2 – Connect to the Plex server (prompt if needed).
    server = establish_connection(config)

    # Step 3 – Discover libraries.
    sections = discover_libraries(server)

    # Step 4 – Let the user pick one, several, or all libraries.
    selected = select_libraries(sections, config)

    # Step 5 – Choose export format and filename.
    fmt = choose_export_format()
    if fmt == "csv":
        default_ext = "csv"
    elif fmt == "html":
        default_ext = "html"
    else:
        default_ext = "txt"
    filename = choose_filename(default_ext)

    # Step 6 – Export!
    export_titles(selected, fmt, filename)


if __name__ == "__main__":
    main()
