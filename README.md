# Plexee Library Exporter

A command-line tool that connects to a Plex Media Server and exports library titles to CSV, text, or HTML files.

## Why Did I Make This?
Have you or your users ever wanted a quick, easy and organized way of seeing what's in each of your libraries without firing up Plex? I sure have so I looked around and was surprised to find there wasn't really anything out there that did it, so I decided to create something myself and Plexee Library Exporter (PLE) was born!

It first started out as simple manual way to export libraries into a text file which served the purpose. Soon I realized I could do quite a bit more including full automation, csv and html exports with a cool retro terminal theme.

Oh, and yes this is 100% Vibe Coded trash! I had a great time creating it and wouldn't have been able to do it otherwise. 

I hope you find it as useful as I do :)


## Features

- **Interactive Manual or Automated mode**: chosen on first run and saved in `config.json`
- **Cron-friendly Automated runs**: no prompts after setup; reuse saved libraries, format, and filenames
- **Multiple Export Formats**: CSV, plain text, or modern HTML with sortable columns
- **Multi-library export**: Pick one library, several (e.g. `1,3,5` or `1-3`), or `all`
- **Audiobook Support**: Special handling for audiobook libraries (Artist → Album structure)
- **Persistent Configuration**: Remembers your server settings, last-used libraries, and per-library filenames
- **Connection Debugging**: Detailed connection status and error reporting
- **HTML Theme**: Terminal-style green-on-black aesthetic with sortable tables
- **IMDb ratings**: Optional OMDb lookups for movie and TV show libraries, cached locally

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

- **CSV**: Includes Title, Author (for audiobook libraries), IMDb Rating (movies and TV shows, when enabled), and Date Added
- **Text**: One title per line (audiobooks: "Title by Author"; movies and TV shows with ratings: "Title (7.5)")
- **HTML**: Sortable table with terminal theme, defaults to newest items first; IMDb Rating column for movies and TV shows when enabled. Titles with an IMDb id link to `https://www.imdb.com/title/{id}/`

### HTML Index Page

When exporting in **HTML format**, the exporter automatically creates an `index.html` page with button-style links to each library's HTML file. The index page uses the same green-on-black terminal aesthetic as the individual library pages.

**On first HTML export**, you'll be prompted to specify the location for `index.html`. This location is saved to your configuration and reused on future runs. You can:
- Use the default `index.html` (in the current directory)
- Specify a subdirectory like `exports/index.html`
- Use an absolute path like `/var/www/html/index.html`

This makes it easy to:
- Navigate between multiple library exports
- Create a central hub for all your exported libraries
- Share a single entry point to all your library data
- Place the index in a web-accessible directory for easy sharing

Simply open the generated `index.html` in your browser to access links to all your exported libraries.

## IMDb Ratings (movie and TV show libraries)

When you export a **movie** or **TV show** library, the exporter can look up IMDb ratings via [OMDb](https://www.omdbapi.com/).

1. Get a free API key at https://www.omdbapi.com/apikey.aspx (1,000 requests/day on the free tier).
2. When prompted, paste the key (or press Enter to skip). Type `skip` later to disable ratings.
3. The key is stored in `config.json` as `omdb_api_key`. Automated runs reuse it without prompting.

Lookups prefer the IMDb id already stored on the Plex item (`imdb://tt…`). If that is missing, the exporter falls back to a title + year search (OMDb type `movie` or `series`). Ratings are cached in `omdb_cache.json` next to the script so later runs only fetch new titles.

In HTML exports, a title that has an IMDb id is a link to that title on IMDb. Titles without an id stay plain text.

Photos and audiobooks are not rated this way.

## Diagnostic Tool

Use `plex_diagnostic.py` for troubleshooting connection issues:

```bash
python3 plex_diagnostic.py
```

