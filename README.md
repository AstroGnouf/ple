# Plexee Library Exporter

A command-line tool that connects to a Plex Media Server and exports library titles to CSV, text, or HTML files.

## Features

- **Interactive Manual or Automated mode**: chosen on first run and saved in `config.json`
- **Cron-friendly Automated runs**: no prompts after setup; reuse saved libraries, format, and filenames
- **Multiple Export Formats**: CSV, plain text, or modern HTML with sortable columns
- **Multi-library export**: Pick one library, several (e.g. `1,3,5` or `1-3`), or `all`
- **Audiobook Support**: Special handling for audiobook libraries (Artist → Album structure)
- **Persistent Configuration**: Remembers your server settings, last-used libraries, and per-library filenames
- **Connection Debugging**: Detailed connection status and error reporting
- **HTML Theme**: Terminal-style green-on-black aesthetic with sortable tables

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python3 plex_library_exporter.py
```

On first run, you'll be prompted for:

- **Run mode**: Interactive Manual or Automated
- Plex server hostname/IP
- TCP port (default: 32400)
- Plex API token
- Which libraries to export, format, and filenames

Re-run setup (mode and export settings) at any time:

```bash
python3 plex_library_exporter.py --setup
```

## Run Modes

### Interactive Manual

Prompts for libraries, format, and filenames on every run. Last values are offered as defaults.

### Automated (cron)

After the first interactive setup, later runs use saved settings and **never prompt**. If credentials fail or setup was never completed, the process exits with an error instead of hanging.

Example crontab (daily at 2:00 AM):

```cron
0 2 * * * /usr/bin/python3 /path/to/plex_library_exporter.py >> /path/to/plexee.log 2>&1
```

Use the same working directory you used during setup (or absolute paths in `library_filenames`) so exports land where you expect.

## Selecting Libraries

When prompted, you can:

- Enter a single number (e.g. `2`)
- Enter comma-separated numbers (e.g. `1,3,5`)
- Enter a range (e.g. `1-3`) or mix them (`1,3-5`)
- Enter `all` to export every library

When exporting multiple libraries, you'll be prompted for a **separate filename for each library**. The exporter remembers each library's last filename for convenient re-runs.

**Note**: The correct file extension (`.csv`, `.txt`, or `.html`) is automatically added based on your chosen format, so just enter the base filename (e.g., `movies` becomes `movies.csv`).

## Export Formats

- **CSV**: Includes Title, Author (for audiobook libraries), and Date Added
- **Text**: One title per line (audiobooks: "Title by Author")
- **HTML**: Sortable table with terminal theme, defaults to newest items first

### HTML Index Page

When exporting **multiple libraries in HTML format**, the exporter automatically creates an `index.html` page with button-style links to each library's HTML file. The index page uses the same green-on-black terminal aesthetic as the individual library pages.

This makes it easy to:
- Navigate between multiple library exports
- Create a central hub for all your exported libraries
- Share a single entry point to all your library data

Simply open `index.html` in your browser to access links to all your exported libraries.

## Diagnostic Tool

Use `plex_diagnostic.py` for troubleshooting connection issues:

```bash
python3 plex_diagnostic.py
```
