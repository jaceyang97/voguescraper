# vogue

CLI for scraping fashion show images from Vogue Runway. Designed for agent consumption via `run(command="...")`.

## Install

```
pip install git+https://github.com/jaceyang97/voguescraper
```

Creates the `vogue` command. Also works as `python -m vogue`.

## Quick Reference

```
vogue designers [<query>]              Search or list designers
vogue shows <designer>                 List shows for a designer
vogue images <designer> <show>         List image URLs
vogue download <designer> <show|--all> Download images to disk
vogue info <designer> <show>           Show collection metadata
```

## Workflow

Typical trajectory from search to download:

```
$ vogue designers yamamoto
Yohji Yamamoto
[1 results | exit:0 | 1.7s]

$ vogue shows "Yohji Yamamoto"
fall-2024-ready-to-wear	Fall 2024 Ready-to-Wear
fall-2024-menswear	Fall 2024 Menswear
spring-2024-ready-to-wear	Spring 2024 Ready-to-Wear
...
[99 results | exit:0 | 2.2s]

$ vogue info "Yohji Yamamoto" fall-2024-ready-to-wear
Designer:  Yohji Yamamoto
Show:      Fall 2024 Ready-to-Wear
Slug:      fall-2024-ready-to-wear
Images:    69
URL:       https://www.vogue.com/fashion-shows/fall-2024-ready-to-wear/yohji-yamamoto
[1 results | exit:0 | 3.4s]

$ vogue images "Yohji Yamamoto" fall-2024-ready-to-wear | head -3
https://assets.vogue.com/photos/.../00001-yohji-yamamoto-fall-2024-ready-to-wear.jpg
https://assets.vogue.com/photos/.../00002-yohji-yamamoto-fall-2024-ready-to-wear.jpg
https://assets.vogue.com/photos/.../00003-yohji-yamamoto-fall-2024-ready-to-wear.jpg

$ vogue download "Yohji Yamamoto" fall-2024-ready-to-wear
  fall-2024-ready-to-wear: 69 images -> output/yohji-yamamoto/fall-2024-ready-to-wear
fall-2024-ready-to-wear: 69 images -> output/yohji-yamamoto/fall-2024-ready-to-wear
[69 results | exit:0 | 31.8s]
```

## Output Contracts

Every command writes results to stdout and metadata to stderr.

**stdout** (pipeable, one record per line):

| Command | Format | Example |
|---------|--------|---------|
| `designers` | `name` | `Yohji Yamamoto` |
| `shows` | `slug\ttitle` | `fall-2024-ready-to-wear\tFall 2024 Ready-to-Wear` |
| `images` | `url` | `https://assets.vogue.com/photos/.../xl.jpg` |
| `download` | `slug: N images -> path` | `fall-2024-ready-to-wear: 69 images -> output/yohji-yamamoto/fall-2024-ready-to-wear` |
| `info` | `Key:  value` | `Designer:  Yohji Yamamoto` |

**stderr** (metadata footer on every command):

```
[N results | exit:CODE | DURATION]
```

Piping only captures stdout, so `vogue designers dior | wc -l` returns `4`, not 5.

**`--json` flag** returns structured data on stdout:

```
$ vogue shows "Yohji Yamamoto" --json
[{"title": "Fall 2024 Ready-to-Wear", "slug": "fall-2024-ready-to-wear"}, ...]

$ vogue info "Yohji Yamamoto" fall-2024-ready-to-wear --json
{"designer": "Yohji Yamamoto", "show": "Fall 2024 Ready-to-Wear", "slug": "fall-2024-ready-to-wear", "images": 69, "url": "..."}
```

## Error Patterns

Every error includes what went wrong and what to do next.

**Missing args** (progressive discovery):

```
$ vogue shows
[error] usage: vogue shows <designer> [--json]
  Find designers: vogue designers <query>
[exit:1 | 0ms]
```

**Not found**:

```
$ vogue shows "Christain Dior"
[error] Page not found (Christain Dior).
  Check the designer name or show slug.
[exit:1 | 0.8s]
```

**Bad flag value**:

```
$ vogue images "Dior" show -r huge
[error] Invalid resolution "huge".
  Available: xl, lg, md, sm
[exit:1 | 0ms]
```

**Overflow** (>200 lines truncated, full output written to temp file):

```
$ vogue designers
3.1 Phillip Lim
A Detacher
...
--- output truncated (3000 lines) ---
Full output: /tmp/vogue-output/output-1711700000.txt
Explore: cat /tmp/vogue-output/output-1711700000.txt | grep <pattern>
         cat /tmp/vogue-output/output-1711700000.txt | tail -100
[3000 results | exit:0 | 1.2s]
```

## Flags

| Flag | Applies to | Description |
|------|-----------|-------------|
| `--json`, `-j` | all | Output as JSON |
| `-r RES` | `images`, `download` | Resolution: `xl`, `lg`, `md`, `sm` (default: `xl`) |
| `-o DIR` | `download` | Output directory (default: `output`) |
| `-w N` | `download` | Parallel workers (default: `4`) |
| `--all` | `download` | Download every show for a designer |

## Download Output

```
output/
  yohji-yamamoto/
    fall-2024-ready-to-wear/
      metadata.json
      001.jpg
      002.jpg
      ...
```

`metadata.json` contains designer, show title/slug, image count, and all image URLs.

## Development

```
pip install -e .
python -m pytest tests/
```

## License

MIT
