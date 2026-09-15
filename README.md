# Plexee Library Exporter

A command-line tool that connects to a Plex Media Server and exports library titles to CSV, text, or HTML files.

## Features

- **Multiple Export Formats**: CSV, plain text, or modern HTML with sortable columns
- **Audiobook Support**: Special handling for audiobook libraries (Artist → Album structure)
- **Persistent Configuration**: Remembers your server settings and last-used library
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

## Export Formats

- **CSV**: Includes Title, Author (audiobooks), and Date Added columns
- **Text**: One title per line (audiobooks: "Title by Author")
- **HTML**: Sortable table with terminal theme, defaults to newest items first

## Diagnostic Tool

Use `plex_diagnostic.py` for troubleshooting connection issues:

```bash
python3 plex_diagnostic.py
```
