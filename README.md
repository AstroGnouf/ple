# Plexee Library Exporter

A command-line tool that connects to a Plex Media Server and exports library titles to CSV, text, or HTML files.

## Features

- **Multiple Export Formats**: CSV, plain text, or modern HTML with sortable columns
- **Multi-library export**: Pick one library, several (e.g. `1,3,5` or `1-3`), or `all`
- **Audiobook Support**: Special handling for audiobook libraries (Artist → Album structure)
- **Persistent Configuration**: Remembers your server settings and last-used libraries
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
- Plex server hostname/IP
- TCP port (default: 32400)
- Plex API token

## Selecting Libraries

When prompted, you can:

- Enter a single number (e.g. `2`)
- Enter comma-separated numbers (e.g. `1,3,5`)
- Enter a range (e.g. `1-3`) or mix them (`1,3-5`)
- Enter `all` to export every library

Multiple libraries are written to a **single** file. CSV and HTML include a Library column; text exports append `[Library Name]` to each line.

## Export Formats

- **CSV**: Includes Title, Library (when exporting more than one), Author (audiobooks), and Date Added
- **Text**: One title per line (audiobooks: "Title by Author"; multi-library: "Title [Library]")
- **HTML**: Sortable table with terminal theme, defaults to newest items first

## Diagnostic Tool

Use `plex_diagnostic.py` for troubleshooting connection issues:

```bash
python3 plex_diagnostic.py
```
