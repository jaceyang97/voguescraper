"""Vogue Runway Scraper — scrape fashion show images from vogue.com.

Uses Vogue's embedded JSON data (window.__PRELOADED_STATE__) for reliable
extraction without browser automation.
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn
from unidecode import unidecode
from urllib3.util.retry import Retry

BASE_URL = "https://www.vogue.com/fashion-shows"

RESOLUTION_PRIORITY = ["xl", "lg", "md", "sm"]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ImageInfo:
    url: str
    index: int


@dataclass
class Show:
    title: str  # e.g. "Fall 2024 Ready-to-Wear"
    slug: str   # e.g. "fall-2024-ready-to-wear"


@dataclass
class Collection:
    designer: str
    show: Show
    images: list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Convert a display name to a Vogue-compatible URL slug."""
    slug = unidecode(name)
    slug = slug.lower()
    slug = slug.replace("&", "").replace("+", "")
    slug = re.sub(r"[\s.]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug


def _create_session() -> requests.Session:
    """Create an HTTP session with retries and a realistic User-Agent."""
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def _fetch_page(session: requests.Session, url: str) -> str:
    """Fetch a page and return its HTML text."""
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def _extract_preloaded_state(html_text: str) -> dict:
    """Extract the window.__PRELOADED_STATE__ JSON from the page HTML."""
    soup = BeautifulSoup(html_text, "html5lib")
    for script in soup.find_all("script", type="text/javascript"):
        text = script.string
        if not text or "window.__PRELOADED_STATE__" not in text:
            continue
        match = re.search(r"window\.__PRELOADED_STATE__\s*=\s*(\{.+\})", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    raise ValueError("Could not find __PRELOADED_STATE__ in page HTML")


def _pick_image_url(sources: dict, preferred: str = "xl") -> str | None:
    """Pick the best available image URL from source dict."""
    order = RESOLUTION_PRIORITY.copy()
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    for res in order:
        if res in sources and sources[res].get("url"):
            return sources[res]["url"]
    return None


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def get_all_designers(session: requests.Session | None = None) -> list[str]:
    """Fetch the full A-Z list of all designers from Vogue Runway."""
    session = session or _create_session()
    url = f"{BASE_URL}/designers"
    html = _fetch_page(session, url)
    state = _extract_preloaded_state(html)

    transformed = state.get("transformed", state)
    grouped = (
        transformed
        .get("allRunwayDesigners", {})
        .get("groupedLinks", [])
    )

    designers = []
    for group in grouped:
        for link in group.get("links", []):
            name = link.get("text", "").strip()
            if name:
                designers.append(name)

    return designers


def get_designer_shows(designer: str, session: requests.Session | None = None) -> list[Show]:
    """Fetch all shows for a designer."""
    session = session or _create_session()
    designer_slug = slugify(designer)
    url = f"{BASE_URL}/designer/{designer_slug}"
    html = _fetch_page(session, url)
    state = _extract_preloaded_state(html)

    transformed = state.get("transformed", state)
    collections = (
        transformed
        .get("runwayDesignerContent", {})
        .get("designerCollections", [])
    )

    shows = []
    for item in collections:
        title = item.get("hed") or item.get("title", "")
        if title:
            shows.append(Show(title=title, slug=slugify(title)))
    return shows


def get_show_images(
    designer: str,
    show_slug: str,
    session: requests.Session | None = None,
    preferred_resolution: str = "xl",
) -> list[ImageInfo]:
    """Fetch image URLs for a specific show."""
    session = session or _create_session()
    designer_slug = slugify(designer)
    url = f"{BASE_URL}/{show_slug}/{designer_slug}"
    html = _fetch_page(session, url)
    state = _extract_preloaded_state(html)

    transformed = state.get("transformed", state)
    galleries = (
        transformed
        .get("runwayShowGalleries", {})
        .get("galleries", [])
    )

    images = []
    for gallery in galleries:
        for idx, item in enumerate(gallery.get("items", []), start=1):
            image_data = item.get("image", {})
            sources = image_data.get("sources", {})
            img_url = _pick_image_url(sources, preferred_resolution)
            if img_url:
                images.append(ImageInfo(url=img_url, index=idx))
    return images


def download_images(
    images: list[ImageInfo],
    output_dir: Path,
    session: requests.Session | None = None,
    max_workers: int = 4,
) -> int:
    """Download images concurrently. Returns count of successfully downloaded images."""
    session = session or _create_session()
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0

    def _download_one(img: ImageInfo) -> bool:
        filepath = output_dir / f"{img.index:03d}.jpg"
        try:
            resp = session.get(img.url, timeout=30, stream=True)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except requests.RequestException:
            return False

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_download_one, img): img for img in images}
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("[dim]{task.fields[status]}"),
            ) as progress:
                task = progress.add_task("Downloading", total=len(images), status="")
                for future in as_completed(futures):
                    if future.result():
                        downloaded += 1
                    progress.update(task, advance=1, status=f"{downloaded} ok")
        except KeyboardInterrupt:
            for f in futures:
                f.cancel()
            raise

    return downloaded


def save_metadata(collection: Collection, output_dir: Path) -> None:
    """Write metadata.json alongside the downloaded images."""
    output_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "designer": collection.designer,
        "show": {
            "title": collection.show.title,
            "slug": collection.show.slug,
        },
        "image_count": len(collection.images),
        "images": [{"index": img.index, "url": img.url} for img in collection.images],
    }
    meta_path = output_dir / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def interactive():
    """Rich interactive terminal UI for casual users."""
    import questionary
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    session = _create_session()

    console.print(Panel.fit(
        "[bold]Vogue Runway Scraper[/bold]\n"
        "[dim]Interactive mode — download fashion show images from vogue.com[/dim]",
    ))

    try:
        _interactive_flow(console, session, questionary)
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted — exiting.[/dim]")


def _interactive_flow(console, session, questionary):
    """Inner interactive flow, separated so KeyboardInterrupt is caught cleanly."""
    # --- Load the global designer index ---
    with console.status("[bold green]Loading designer index from Vogue..."):
        all_designers = get_all_designers(session)

    if not all_designers:
        console.print("[red]No designers found. Vogue may have changed their site.[/red]")
        return

    console.print(f"  [dim]{len(all_designers)} designers loaded[/dim]\n")

    BACK = "<< Back"

    while True:
        # --- Pick a designer ---
        console.print("[dim]Ctrl+C to quit[/dim]")
        designer = questionary.autocomplete(
            "Designer (type to search):",
            choices=all_designers,
            validate=lambda val: val in all_designers or "Pick a designer from the list",
        ).ask()

        if designer is None:
            return

        # --- Fetch that designer's shows ---
        with console.status(f"[bold green]Fetching shows for {designer}..."):
            shows = get_designer_shows(designer, session)

        if not shows:
            console.print(f"[yellow]No shows found for '{designer}'.[/yellow]")
            continue

        console.print(f"  [dim]{len(shows)} shows found[/dim]\n")

        # --- How many shows? ---
        scope = questionary.select(
            "What would you like to download?",
            choices=[
                questionary.Choice("All shows", value="all"),
                questionary.Choice("Pick specific shows", value="pick"),
                questionary.Choice(BACK, value="back"),
            ],
            instruction="(Ctrl+C to quit)",
        ).ask()

        if scope is None:
            return
        if scope == "back":
            console.print()
            continue
        if scope == "all":
            selected_shows = shows
            break

        # --- Pick specific shows ---
        show_choices = [s.title for s in shows] + [BACK]

        console.print("[bold yellow]  TIP: press SPACE to check/uncheck shows, then ENTER to confirm[/bold yellow]\n")

        selected = questionary.checkbox(
            "Select shows:",
            choices=show_choices,
            instruction="(SPACE=toggle, ENTER=confirm, Ctrl+C=quit)",
        ).ask()

        if not selected or selected == [BACK]:
            if not selected:
                console.print("[yellow]Nothing selected. Use SPACE to check shows before pressing ENTER.[/yellow]\n")
            continue

        selected = [s for s in selected if s != BACK]
        if not selected:
            continue

        title_set = set(selected)
        selected_shows = [s for s in shows if s.title in title_set]
        break

    # --- Resolution ---
    resolution = questionary.select(
        "Image resolution:",
        choices=[
            questionary.Choice("XL (highest)", value="xl"),
            questionary.Choice("LG", value="lg"),
            questionary.Choice("MD", value="md"),
            questionary.Choice("SM (smallest)", value="sm"),
        ],
        default="xl",
        instruction="(Ctrl+C to quit)",
    ).ask()

    if resolution is None:
        return

    # --- Output directory ---
    console.print("[dim]Ctrl+C to quit[/dim]")
    output_dir = questionary.text(
        "Output directory:",
        default="./output",
    ).ask()

    if output_dir is None:
        return

    # --- Download ---
    from rich.panel import Panel

    output_base = Path(output_dir)
    designer_slug = slugify(designer)

    console.print()
    for show in selected_shows:
        console.rule(f"[bold]{designer} / {show.title}[/bold]")

        with console.status("[green]Fetching image list..."):
            images = get_show_images(designer, show.slug, session, resolution)

        if not images:
            console.print("[yellow]  No images found, skipping.[/yellow]")
            continue

        console.print(f"  Found [bold]{len(images)}[/bold] images")

        out_dir = output_base / designer_slug / show.slug
        collection = Collection(designer=designer, show=show, images=images)
        save_metadata(collection, out_dir)

        count = download_images(images, out_dir, session)
        console.print(f"  [green]Downloaded {count}/{len(images)} images[/green] -> {out_dir}\n")

    console.print(Panel.fit("[bold green]Done![/bold green]"))


# ---------------------------------------------------------------------------
# CLI (for scripts / LLM agents)
# ---------------------------------------------------------------------------


def cmd_designers(args):
    session = _create_session()
    designers = get_all_designers(session)
    if not designers:
        print("No designers found.")
        return

    if args.search:
        query = args.search.lower()
        designers = [d for d in designers if query in d.lower()]
        if not designers:
            print(f"No designers matching '{args.search}'.")
            return

    for d in designers:
        print(d)


def cmd_shows(args):
    session = _create_session()
    shows = get_designer_shows(args.designer, session)
    if not shows:
        print(f"No shows found for '{args.designer}'.")
        return
    print(f"Found {len(shows)} shows for {args.designer}:\n")
    for s in shows:
        print(f"  {s.title}")


def cmd_download(args):
    session = _create_session()
    output_base = Path(args.output)
    designer_slug = slugify(args.designer)
    resolution = args.resolution

    if args.all:
        shows = get_designer_shows(args.designer, session)
        if not shows:
            print(f"No shows found for '{args.designer}'.")
            return
        print(f"Downloading all {len(shows)} shows for {args.designer}...\n")
    elif args.season:
        show_slug = slugify(args.season)
        shows = [Show(title=args.season, slug=show_slug)]
    else:
        print("Error: provide --season or --all", file=sys.stderr)
        sys.exit(1)

    for show in shows:
        print(f"\n--- {args.designer} / {show.title} ---")
        images = get_show_images(args.designer, show.slug, session, resolution)
        if not images:
            print("  No images found, skipping.")
            continue

        out_dir = output_base / designer_slug / show.slug
        collection = Collection(designer=args.designer, show=show, images=images)
        save_metadata(collection, out_dir)

        count = download_images(images, out_dir, session, args.workers)
        print(f"  Downloaded {count}/{len(images)} images → {out_dir}")


def main():
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] == "interactive"):
        interactive()
        return

    parser = argparse.ArgumentParser(
        description="Vogue Runway Scraper — download fashion show images from vogue.com"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # interactive (so --help shows it)
    subparsers.add_parser("interactive", help="Launch interactive mode (default when no args)")

    # designers
    p_designers = subparsers.add_parser("designers", help="List all designers (optionally filter by search term)")
    p_designers.add_argument("-q", "--search", help="Filter designers by name (case-insensitive substring match)")

    # shows
    p_shows = subparsers.add_parser("shows", help="List shows for a designer")
    p_shows.add_argument("-d", "--designer", required=True, help="Designer/brand name")

    # download
    p_download = subparsers.add_parser("download", help="Download collection images")
    p_download.add_argument("-d", "--designer", required=True, help="Designer/brand name")
    p_download.add_argument("-s", "--season", help="Season name (for single collection)")
    p_download.add_argument("--all", action="store_true", help="Download all shows for designer")
    p_download.add_argument("-o", "--output", default=".", help="Output directory (default: current dir)")
    p_download.add_argument("-w", "--workers", type=int, default=4, help="Concurrent download workers (default: 4)")
    p_download.add_argument("-r", "--resolution", default="xl", choices=RESOLUTION_PRIORITY,
                            help="Preferred image resolution (default: xl)")

    args = parser.parse_args()
    commands = {
        "interactive": lambda _: interactive(),
        "designers": cmd_designers,
        "shows": cmd_shows,
        "download": cmd_download,
    }
    try:
        commands[args.command](args)
    except requests.ConnectionError:
        print("Error: Could not connect to vogue.com. Check your internet connection.", file=sys.stderr)
        sys.exit(1)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 404:
            print("Error: Page not found. Check the designer name and season.", file=sys.stderr)
        elif status == 403:
            print("Error: Access denied by vogue.com (403).", file=sys.stderr)
        else:
            print(f"Error: HTTP {status} from vogue.com.", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Vogue may have changed their page structure.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
