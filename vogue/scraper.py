"""Core scraping logic for Vogue Runway (Layer 1 — pure data, no formatting).

Extracts data from Vogue's embedded window.__PRELOADED_STATE__ JSON.
All functions return raw data; formatting is handled by the CLI layer.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from unidecode import unidecode
from urllib3.util.retry import Retry

BASE_URL = "https://www.vogue.com/fashion-shows"
RESOLUTIONS = ("xl", "lg", "md", "sm")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ImageInfo:
    url: str
    index: int


@dataclass
class Show:
    title: str
    slug: str


@dataclass
class Collection:
    designer: str
    show: Show
    images: list  # list[ImageInfo]


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
    return slug.strip("-")


def create_session() -> requests.Session:
    """Create an HTTP session with retries and a realistic User-Agent."""
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
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
        match = re.search(
            r"window\.__PRELOADED_STATE__\s*=\s*(\{.+\})", text, re.DOTALL
        )
        if match:
            return json.loads(match.group(1))
    raise ValueError("Could not find __PRELOADED_STATE__ in page HTML")


def _pick_image_url(sources: dict, preferred: str = "xl") -> str | None:
    """Pick the best available image URL from source dict."""
    order = list(RESOLUTIONS)
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
    session = session or create_session()
    html = _fetch_page(session, f"{BASE_URL}/designers")
    state = _extract_preloaded_state(html)

    transformed = state.get("transformed", state)
    grouped = transformed.get("allRunwayDesigners", {}).get("groupedLinks", [])

    designers = []
    for group in grouped:
        for link in group.get("links", []):
            name = link.get("text", "").strip()
            if name:
                designers.append(name)
    return designers


def get_designer_shows(
    designer: str, session: requests.Session | None = None
) -> list[Show]:
    """Fetch all shows for a designer."""
    session = session or create_session()
    designer_slug = slugify(designer)
    html = _fetch_page(session, f"{BASE_URL}/designer/{designer_slug}")
    state = _extract_preloaded_state(html)

    transformed = state.get("transformed", state)
    collections = (
        transformed.get("runwayDesignerContent", {}).get("designerCollections", [])
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
    session = session or create_session()
    designer_slug = slugify(designer)
    html = _fetch_page(session, f"{BASE_URL}/{show_slug}/{designer_slug}")
    state = _extract_preloaded_state(html)

    transformed = state.get("transformed", state)
    galleries = transformed.get("runwayShowGalleries", {}).get("galleries", [])

    images = []
    idx = 0
    for gallery in galleries:
        for item in gallery.get("items", []):
            sources = item.get("image", {}).get("sources", {})
            url = _pick_image_url(sources, preferred_resolution)
            if url:
                idx += 1
                images.append(ImageInfo(url=url, index=idx))
    return images


def download_images(
    images: list[ImageInfo],
    output_dir: str | Path,
    session: requests.Session | None = None,
    max_workers: int = 4,
) -> int:
    """Download images concurrently. Returns count of successes."""
    session = session or create_session()
    output_dir = Path(output_dir)
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
        for future in as_completed(futures):
            if future.result():
                downloaded += 1

    return downloaded


def save_metadata(collection: Collection, output_dir: str | Path) -> None:
    """Write metadata.json alongside the downloaded images."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "designer": collection.designer,
        "show": {"title": collection.show.title, "slug": collection.show.slug},
        "image_count": len(collection.images),
        "images": [{"index": img.index, "url": img.url} for img in collection.images],
    }
    (output_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
