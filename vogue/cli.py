"""Agent-friendly CLI for Vogue Runway (Layer 2 — command router + presentation).

Implements the two-layer architecture from "CLI Is All Agents Need":
  Layer 1 (scraper.py): raw data extraction, no formatting
  Layer 2 (this file):  command routing, overflow, errors, metadata footer

Output conventions:
  stdout  — result data (one item per line, pipeable)
  stderr  — metadata footer [exit:N | Xms], errors, progress
"""

import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import requests

from vogue import __version__
from vogue.scraper import (
    BASE_URL,
    RESOLUTIONS,
    Collection,
    create_session,
    download_images,
    get_all_designers,
    get_designer_shows,
    get_show_images,
    save_metadata,
    slugify,
)

MAX_LINES = 200
OVERFLOW_DIR = Path("/tmp/vogue-output")


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class CLIError(Exception):
    """User-facing error with optional recovery hints."""

    def __init__(self, message, hints=None):
        self.message = message
        self.hints = hints or []
        super().__init__(message)


# ---------------------------------------------------------------------------
# Arg-parsing helpers (simple flag popping — no argparse needed)
# ---------------------------------------------------------------------------


def _pop_flag(args: list, *names) -> bool:
    """Remove boolean flag(s) from args. Returns True if any found."""
    found = False
    for name in names:
        while name in args:
            args.remove(name)
            found = True
    return found


def _pop_value(args: list, *names, default=None):
    """Remove a --flag value pair from args. Returns the value."""
    for name in names:
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                val = args.pop(i + 1)
                args.pop(i)
                return val
            args.pop(i)
            raise CLIError(f"{name} requires a value")
    return default


# ---------------------------------------------------------------------------
# Output helpers (Layer 2 presentation)
# ---------------------------------------------------------------------------


def _footer(code: int, elapsed: float, count=None):
    """Print metadata footer to stderr: [N results | exit:0 | 123ms]."""
    dur = f"{elapsed * 1000:.0f}ms" if elapsed < 1 else f"{elapsed:.1f}s"
    parts = []
    if count is not None:
        parts.append(f"{count} results")
    parts.extend([f"exit:{code}", dur])
    print(f"[{' | '.join(parts)}]", file=sys.stderr)


def _truncate(lines: list[str]) -> tuple[list[str], str | None]:
    """Truncate output exceeding MAX_LINES. Writes full output to temp file."""
    if len(lines) <= MAX_LINES:
        return lines, None

    OVERFLOW_DIR.mkdir(parents=True, exist_ok=True)
    path = OVERFLOW_DIR / f"output-{time.time_ns()}.txt"
    path.write_text("\n".join(lines))

    notice = (
        f"\n--- output truncated ({len(lines)} lines) ---\n"
        f"Full output: {path}\n"
        f"Explore: cat {path} | grep <pattern>\n"
        f"         cat {path} | tail -100"
    )
    return lines[:MAX_LINES], notice


@contextmanager
def _handle_errors(context=""):
    """Catch scraper exceptions and re-raise as CLIError with navigation hints."""
    try:
        yield
    except CLIError:
        raise
    except requests.ConnectionError:
        raise CLIError(
            "Could not connect to vogue.com.",
            hints=["Check your internet connection."],
        )
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 404:
            raise CLIError(
                f"Page not found{f' ({context})' if context else ''}.",
                hints=["Check the designer name or show slug."],
            )
        elif status == 403:
            raise CLIError("Access denied (403). Vogue may be blocking requests.")
        else:
            raise CLIError(f"HTTP {status}: {e}")
    except ValueError as e:
        raise CLIError(
            f"Parse error: {e}",
            hints=["Vogue may have changed their site structure."],
        )


def _resolve_shows(shows, show_slug, designer, fuzzy=True):
    """Find shows by slug (exact, then optional substring match). Raises CLIError if none."""
    matches = [s for s in shows if s.slug == show_slug]
    if not matches and fuzzy:
        matches = [s for s in shows if show_slug.lower() in s.slug.lower()]
    if not matches:
        avail = ", ".join(s.slug for s in shows[:10])
        raise CLIError(
            f'Show "{show_slug}" not found for "{designer}".',
            hints=[f"Available: {avail}", f'List all: vogue shows "{designer}"'],
        )
    return matches


def _validate_resolution(res):
    """Raise CLIError if resolution is not in RESOLUTIONS."""
    if res not in RESOLUTIONS:
        raise CLIError(
            f'Invalid resolution "{res}".',
            hints=[f"Available: {', '.join(RESOLUTIONS)}"],
        )


# ---------------------------------------------------------------------------
# Commands — each returns a result count for the footer
# ---------------------------------------------------------------------------


def cmd_designers(args: list) -> int:
    """Search or list all designers. One name per line."""
    as_json = _pop_flag(args, "--json", "-j")
    query = args[0] if args else None

    with _handle_errors():
        session = create_session()
        designers = get_all_designers(session)

    if query:
        q = query.lower()
        designers = [d for d in designers if q in d.lower()]
        if not designers:
            raise CLIError(
                f'No designers found matching "{query}".',
                hints=["List all: vogue designers"],
            )

    if as_json:
        print(json.dumps(designers))
        return len(designers)

    lines, notice = _truncate(designers)
    print("\n".join(lines))
    if notice:
        print(notice, file=sys.stderr)
    return len(designers)


def cmd_shows(args: list) -> int:
    """List shows for a designer. Tab-separated: slug<TAB>title."""
    as_json = _pop_flag(args, "--json", "-j")

    if not args:
        raise CLIError(
            "usage: vogue shows <designer> [--json]",
            hints=["Find designers: vogue designers <query>"],
        )

    designer = args[0]

    with _handle_errors(context=designer):
        session = create_session()
        shows = get_designer_shows(designer, session)

    if not shows:
        raise CLIError(f'No shows found for "{designer}".')

    if as_json:
        print(json.dumps([{"title": s.title, "slug": s.slug} for s in shows]))
        return len(shows)

    lines = [f"{s.slug}\t{s.title}" for s in shows]
    truncated, notice = _truncate(lines)
    print("\n".join(truncated))
    if notice:
        print(notice, file=sys.stderr)
    return len(shows)


def cmd_images(args: list) -> int:
    """List image URLs for a show. One URL per line."""
    as_json = _pop_flag(args, "--json", "-j")
    res = _pop_value(args, "-r", "--resolution", default="xl")

    if len(args) < 2:
        raise CLIError(
            "usage: vogue images <designer> <show> [-r RES] [--json]",
            hints=[
                "List shows first: vogue shows <designer>",
                f"Resolutions: {', '.join(RESOLUTIONS)} (default: xl)",
            ],
        )

    designer, show_slug = args[0], args[1]
    _validate_resolution(res)

    with _handle_errors(context=f"{designer}/{show_slug}"):
        session = create_session()
        images = get_show_images(designer, show_slug, session, res)

    if not images:
        raise CLIError(
            f'No images found for "{designer}" / "{show_slug}".',
            hints=[f'Check show slug: vogue shows "{designer}"'],
        )

    if as_json:
        print(json.dumps([{"index": i.index, "url": i.url} for i in images]))
        return len(images)

    print("\n".join(img.url for img in images))
    return len(images)


def cmd_download(args: list) -> int:
    """Download show images to disk. Returns total downloaded count."""
    as_json = _pop_flag(args, "--json", "-j")
    dl_all = _pop_flag(args, "--all")
    output_base = _pop_value(args, "-o", "--output", default="output")
    res = _pop_value(args, "-r", "--resolution", default="xl")
    workers = int(_pop_value(args, "-w", "--workers", default="4"))

    if not args:
        raise CLIError(
            "usage: vogue download <designer> [<show> | --all] [-o DIR] [-r RES] [-w N]",
            hints=[
                "<show>    Show slug (from 'vogue shows')",
                "--all     Download every show for this designer",
                "-o DIR    Output directory (default: output)",
                f"-r RES    Resolution: {', '.join(RESOLUTIONS)} (default: xl)",
                "-w N      Parallel download workers (default: 4)",
            ],
        )

    designer = args[0]
    show_slug = args[1] if len(args) > 1 else None
    _validate_resolution(res)

    if not show_slug and not dl_all:
        raise CLIError(
            "Specify a show slug or use --all.",
            hints=[
                f'List shows: vogue shows "{designer}"',
                f'Download all: vogue download "{designer}" --all',
            ],
        )

    with _handle_errors(context=designer):
        session = create_session()
        if dl_all:
            shows = get_designer_shows(designer, session)
            if not shows:
                raise CLIError(f'No shows found for "{designer}".')
        else:
            all_shows = get_designer_shows(designer, session)
            shows = _resolve_shows(all_shows, show_slug, designer)

    results = []
    for show in shows:
        outdir = f"{output_base}/{slugify(designer)}/{show.slug}"
        try:
            images = get_show_images(designer, show.slug, session, res)
            if not images:
                print(f"  {show.slug}: no images", file=sys.stderr)
                results.append({"show": show.slug, "images": 0, "path": outdir})
                continue
            count = download_images(images, outdir, session, workers)
            save_metadata(
                Collection(designer=designer, show=show, images=images), outdir
            )
            results.append({"show": show.slug, "images": count, "path": outdir})
            print(f"  {show.slug}: {count} images -> {outdir}", file=sys.stderr)
        except KeyboardInterrupt:
            raise
        except (requests.RequestException, ValueError, OSError) as e:
            print(f"  {show.slug}: error -- {e}", file=sys.stderr)
            results.append({"show": show.slug, "images": 0, "error": str(e)})

    total = sum(r["images"] for r in results)
    if as_json:
        print(json.dumps(results))
        return total

    for r in results:
        if "error" in r:
            print(f"{r['show']}: failed -- {r['error']}")
        else:
            print(f"{r['show']}: {r['images']} images -> {r.get('path', '')}")
    return total


def cmd_info(args: list) -> int:
    """Show metadata for a collection."""
    as_json = _pop_flag(args, "--json", "-j")

    if len(args) < 2:
        raise CLIError(
            "usage: vogue info <designer> <show> [--json]",
            hints=["List shows: vogue shows <designer>"],
        )

    designer, show_slug = args[0], args[1]

    with _handle_errors(context=designer):
        session = create_session()
        all_shows = get_designer_shows(designer, session)

    show = _resolve_shows(all_shows, show_slug, designer, fuzzy=False)[0]

    with _handle_errors(context=f"{designer}/{show_slug}"):
        images = get_show_images(designer, show_slug, session)

    url = f"{BASE_URL}/{show_slug}/{slugify(designer)}"
    info = {
        "designer": designer,
        "show": show.title,
        "slug": show.slug,
        "images": len(images),
        "url": url,
    }

    if as_json:
        print(json.dumps(info))
        return 1

    print(f"Designer:  {info['designer']}")
    print(f"Show:      {info['show']}")
    print(f"Slug:      {info['slug']}")
    print(f"Images:    {info['images']}")
    print(f"URL:       {info['url']}")
    return 1


# ---------------------------------------------------------------------------
# Command router
# ---------------------------------------------------------------------------

COMMANDS = {
    "designers": cmd_designers,
    "shows": cmd_shows,
    "images": cmd_images,
    "download": cmd_download,
    "info": cmd_info,
}


def _print_help():
    """Level 0 discovery: show all available commands."""
    print(f"""vogue v{__version__} -- Scrape fashion show images from Vogue Runway.

Commands:
  designers [<query>]              Search or list designers
  shows <designer>                 List shows for a designer
  images <designer> <show>         List image URLs for a show
  download <designer> <show|--all> Download show images
  info <designer> <show>           Show collection metadata

Flags:
  --json, -j   Output as JSON
  -r RES       Image resolution: xl, lg, md, sm (default: xl)
  -o DIR       Output directory (default: output)
  -w N         Download workers (default: 4)
  --help, -h   Show this help

Examples:
  vogue designers dior
  vogue shows "Christian Dior"
  vogue images "Christian Dior" fall-2024-ready-to-wear
  vogue download "Christian Dior" fall-2024-ready-to-wear
  vogue download "Christian Dior" --all -o ./runway""")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("help", "--help", "-h"):
        _print_help()
        return

    if args[0] in ("--version", "-v", "version"):
        print(f"vogue {__version__}")
        return

    cmd_name = args[0]
    rest = args[1:]

    if cmd_name not in COMMANDS:
        print(f"[error] unknown command: {cmd_name}", file=sys.stderr)
        print(f"Available: {', '.join(COMMANDS)}", file=sys.stderr)
        print("Run 'vogue help' for usage.", file=sys.stderr)
        sys.exit(1)

    # --help on any subcommand: invoke with no args to trigger usage error
    if _pop_flag(rest, "--help", "-h"):
        rest = []

    t = time.time()
    try:
        count = COMMANDS[cmd_name](rest)
        _footer(0, time.time() - t, count)
    except CLIError as e:
        print(f"[error] {e.message}", file=sys.stderr)
        for hint in e.hints:
            print(f"  {hint}", file=sys.stderr)
        _footer(1, time.time() - t)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        _footer(130, time.time() - t)
        sys.exit(130)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        _footer(1, time.time() - t)
        sys.exit(1)
