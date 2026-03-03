# Vogue Runway Scraper

<img src="app_logo.png" alt="Vogue Scraper Logo" width="240">

Download fashion show images from Vogue Runway. Pure HTTP — no browser needed.

## Features

- **Interactive mode** — guided terminal UI with designer search, show selection, and progress bars
- **Scriptable CLI** — non-interactive commands for automation and LLM agents
- **9,000+ designers** — full Vogue Runway index, searchable
- **Concurrent downloads** — multi-threaded with configurable workers
- **Resolution selection** — xl, lg, md, sm
- **Metadata export** — `metadata.json` with show info and image URLs

## Installation

```sh
git clone https://github.com/jaceyang97/voguescraper.git
cd voguescraper
pip install -r requirements.txt
```

## Usage

### Interactive mode

```sh
python vogue.py
```

Launches a guided terminal UI: search for a designer, pick shows, choose resolution, and download.

### CLI (for scripts / agents)

```sh
# Search for a designer by name
python vogue.py designers -q "dior"

# List all shows for a designer
python vogue.py shows -d "Christian Dior"

# Download a specific collection
python vogue.py download -d "Christian Dior" -s "Fall 2025 Ready-to-Wear"

# Download all shows for a designer
python vogue.py download -d "Christian Dior" --all -o ./output
```

### Download options

| Flag | Description | Default |
|------|-------------|---------|
| `-d`, `--designer` | Designer/brand name | required |
| `-s`, `--season` | Season name (single collection) | — |
| `--all` | Download all shows | false |
| `-o`, `--output` | Output directory | `.` |
| `-w`, `--workers` | Concurrent download threads | 4 |
| `-r`, `--resolution` | Image resolution (`xl`, `lg`, `md`, `sm`) | `xl` |

### Output structure

```
output/
  christian-dior/
    fall-2025-ready-to-wear/
      metadata.json
      001.jpg
      002.jpg
      ...
```

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

Not affiliated with Vogue or Conde Nast. For educational and non-commercial use only.
