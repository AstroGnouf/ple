#!/usr/bin/env python3
"""
Plexee Library Exporter
=======================
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


def _export_html(entries: list[dict], is_audiobook: bool, library_name: str, filename: str) -> None:
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
    
    # Generate table headers
    if is_audiobook:
        headers = """                        <th class="sortable">Title</th>
                        <th class="sortable">Author</th>
                        <th class="sortable">Date Added</th>"""
    else:
        headers = """                        <th class="sortable">Title</th>
                        <th class="sortable">Date Added</th>"""
    
    # Generate table rows
    rows_html = []
    for entry in entries:
        title = entry.get("title", "")
        # Escape HTML special characters
        title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        date_added = _format_date(entry.get("added_at"))
        
        if is_audiobook:
            author = entry.get("author", "")
            author = author.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            row = f"""                    <tr>
                        <td class="title-cell">{title}</td>
                        <td class="author-cell">{author}</td>
                        <td class="date-cell">{date_added}</td>
                    </tr>"""
        else:
            row = f"""                    <tr>
                        <td class="title-cell">{title}</td>
                        <td class="date-cell">{date_added}</td>
                    </tr>"""
        
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


def export_titles(section, fmt: str, filename: str) -> None:
    """Fetch all items from the selected library section and write their
    titles to *filename* in the requested format.

    For audiobook / music libraries the function drills down to the album
    level (artist → album) so that actual book titles are exported instead
    of author names.  A CSV export of an audiobook library includes both
    "Title" and "Author" columns; a text export lists one book per line
    as "Book Title by Author Name".  An HTML export creates a modern,
    sortable table with Title, Date Added, and (for audiobooks) Author.
    """

    print(f"Fetching items from '{section.title}'…")

    is_audiobook = _is_audiobook_library(section)

    if is_audiobook:
        entries = _fetch_audiobook_titles(section)
    else:
        entries = _fetch_standard_titles(section)

    if not entries:
        print("The selected library is empty – nothing to export.")
        return

    print(f"Found {len(entries)} title(s). Writing to '{filename}'…")

    try:
        if fmt == "csv":
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                if is_audiobook:
                    writer.writerow(["Title", "Author", "Date Added"])
                    for entry in entries:
                        added = _format_date(entry.get("added_at"))
                        writer.writerow([entry["title"], entry.get("author", ""), added])
                else:
                    writer.writerow(["Title", "Date Added"])
                    for entry in entries:
                        added = _format_date(entry.get("added_at"))
                        writer.writerow([entry["title"], added])
        elif fmt == "html":
            _export_html(entries, is_audiobook, section.title, filename)
        else:
            # Plain text – one title per line.
            # Audiobooks: "Book Title by Author Name"; others: title only.
            with open(filename, "w", encoding="utf-8") as fh:
                for entry in entries:
                    if is_audiobook and entry.get("author"):
                        fh.write(f"{entry['title']} by {entry['author']}\n")
                    else:
                        fh.write(entry["title"] + "\n")
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

    # Step 4 – Let the user pick a library.
    selected = select_library(sections, config)

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
