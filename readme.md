

# Vogue Runway Image Downloader

<img src="app_logo.png" alt="Vogue Scraper Logo" style="float: left; margin-right: 2em; width: 240px; height: auto; max-width: 40%;">
<br clear="left">

A Python tool for downloading fashion show images from Vogue Runway. Uses Vogue's embedded page data for fast, reliable scraping — no browser automation required.

## Features
- **No browser needed** — pure HTTP requests, no Chrome/Selenium dependency
- **Browse seasons & designers** — discover available collections before downloading
- **Download images** — single collection or all shows for a designer
- **Concurrent downloads** — multi-threaded image downloading with progress bar
- **Resolution selection** — choose from xl, lg, md, sm image sizes
- **Metadata export** — saves `metadata.json` alongside images with show info and URLs
- **Retry logic** — automatic retries with backoff for network issues

## Requirements
- Python 3.10+
- The following Python libraries (installed via requirements.txt):
  - requests
  - beautifulsoup4
  - html5lib
  - unidecode
  - tqdm

## Installation

1. **Clone the Repository:**
   ```sh
   git clone https://github.com/jaceyang97/voguescraper.git
   cd voguescraper
   ```

2. **Install the Required Python Packages:**
   ```sh
   pip install -r requirements.txt
   ```

## Usage

### List available seasons

```sh
python vogue.py seasons
```

### List designers in a season

```sh
python vogue.py designers -s "Fall 2024 Ready-to-Wear"
```

### List all shows for a designer

```sh
python vogue.py shows -d "Yohji Yamamoto"
```

### Download a specific collection

```sh
python vogue.py download -d "Yohji Yamamoto" -s "Fall 2024 Ready-to-Wear"
```

### Download all shows for a designer

```sh
python vogue.py download -d "Yohji Yamamoto" --all -o ./output
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-d`, `--designer` | Designer/brand name | — |
| `-s`, `--season` | Season name | — |
| `--all` | Download all shows for a designer | false |
| `-o`, `--output` | Output directory | `.` (current dir) |
| `-w`, `--workers` | Concurrent download threads | 4 |
| `-r`, `--resolution` | Image resolution (`xl`, `lg`, `md`, `sm`) | `xl` |

### Output structure

```
output/
  yohji-yamamoto/
    fall-2024-ready-to-wear/
      metadata.json
      001.jpg
      002.jpg
      ...
```

## Troubleshooting

1. **No images found:**
   Vogue's internal data structure may have changed. Check that the designer and season names are correct by using the `shows` and `seasons` commands first.

2. **Connection errors:**
   The scraper includes automatic retries. If issues persist, check your internet connection and try again.

3. **Designer name format:**
   Use the display name (e.g., "Yohji Yamamoto"), not the URL slug. The scraper handles slug conversion automatically.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Legal Disclaimer

This project is not affiliated with, endorsed by, or in any way associated with Vogue or its parent company. The content and images accessed through this script are the property of Vogue and are used for educational and non-commercial purposes only.

By using this script, you agree to use it responsibly and acknowledge that the developers of this project are not liable for any misuse. If the usage of this script is found to harm the web integrity or violate the terms of service of Vogue, the developers will take immediate action to remove or modify the script as necessary.
