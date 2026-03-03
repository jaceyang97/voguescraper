"""Tests for vogue.py — uses mocked HTTP responses to validate parsing logic."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import StringIO

from vogue import (
    slugify,
    _extract_preloaded_state,
    _pick_image_url,
    get_designer_shows,
    get_show_images,
    get_seasons,
    get_season_designers,
    save_metadata,
    ImageInfo,
    Show,
    Collection,
)


# ---------------------------------------------------------------------------
# Sample fixtures — simulate Vogue's __PRELOADED_STATE__ JSON
# ---------------------------------------------------------------------------

SAMPLE_DESIGNER_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Yohji Yamamoto Fashion Shows</title></head>
<body>
<script type="text/javascript">
window.__PRELOADED_STATE__ = {
  "transformed": {
    "runwayDesignerContent": {
      "designerCollections": [
        {"hed": "Fall 2024 Ready-to-Wear"},
        {"hed": "Spring 2024 Ready-to-Wear"},
        {"hed": "Fall 2023 Ready-to-Wear"}
      ]
    }
  }
}
</script>
</body>
</html>
"""

SAMPLE_SHOW_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Yohji Yamamoto Fall 2024</title></head>
<body>
<script type="text/javascript">
window.__PRELOADED_STATE__ = {
  "transformed": {
    "runwayShowGalleries": {
      "galleries": [
        {
          "items": [
            {
              "image": {
                "sources": {
                  "sm": {"url": "https://assets.vogue.com/photos/abc/sm.jpg"},
                  "md": {"url": "https://assets.vogue.com/photos/abc/md.jpg"},
                  "lg": {"url": "https://assets.vogue.com/photos/abc/lg.jpg"},
                  "xl": {"url": "https://assets.vogue.com/photos/abc/xl.jpg"}
                }
              }
            },
            {
              "image": {
                "sources": {
                  "sm": {"url": "https://assets.vogue.com/photos/def/sm.jpg"},
                  "md": {"url": "https://assets.vogue.com/photos/def/md.jpg"}
                }
              }
            },
            {
              "image": {
                "sources": {
                  "xl": {"url": "https://assets.vogue.com/photos/ghi/xl.jpg"}
                }
              }
            }
          ]
        }
      ]
    }
  }
}
</script>
</body>
</html>
"""

SAMPLE_SEASONS_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Fashion Shows</title></head>
<body>
<script type="text/javascript">
window.__PRELOADED_STATE__ = {
  "transformed": {
    "runwaySeasonPage": {
      "seasonNavLinks": [
        {"hed": "Fall 2024 Ready-to-Wear"},
        {"hed": "Spring 2025 Couture"},
        {"hed": "Resort 2025"}
      ]
    }
  }
}
</script>
</body>
</html>
"""

SAMPLE_SEASON_DESIGNERS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Fall 2024 Ready-to-Wear</title></head>
<body>
<script type="text/javascript">
window.__PRELOADED_STATE__ = {
  "transformed": {
    "runwaySeasonPage": {
      "designers": [
        {"brand": "Yohji Yamamoto"},
        {"brand": "Comme des Garçons"},
        {"brand": "Issey Miyake"}
      ]
    }
  }
}
</script>
</body>
</html>
"""

NO_PRELOADED_STATE_HTML = """
<!DOCTYPE html>
<html><body><p>No data here</p></body></html>
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Yohji Yamamoto"), "yohji-yamamoto")

    def test_with_spaces(self):
        self.assertEqual(slugify("Fall 2024 Ready-to-Wear"), "fall-2024-ready-to-wear")

    def test_with_ampersand(self):
        self.assertEqual(slugify("Dolce & Gabbana"), "dolce-gabbana")

    def test_with_plus(self):
        self.assertEqual(slugify("A+B"), "ab")

    def test_with_accented_chars(self):
        self.assertEqual(slugify("Hermès"), "hermes")

    def test_with_dots(self):
        self.assertEqual(slugify("A.P.C."), "a-p-c")

    def test_already_slug(self):
        self.assertEqual(slugify("yohji-yamamoto"), "yohji-yamamoto")

    def test_multiple_spaces(self):
        self.assertEqual(slugify("Marc  Jacobs"), "marc-jacobs")

    def test_strips_leading_trailing_hyphens(self):
        self.assertEqual(slugify(" Test "), "test")


class TestExtractPreloadedState(unittest.TestCase):
    def test_extracts_json(self):
        state = _extract_preloaded_state(SAMPLE_DESIGNER_PAGE_HTML)
        self.assertIn("transformed", state)
        collections = state["transformed"]["runwayDesignerContent"]["designerCollections"]
        self.assertEqual(len(collections), 3)
        self.assertEqual(collections[0]["hed"], "Fall 2024 Ready-to-Wear")

    def test_raises_on_missing(self):
        with self.assertRaises(ValueError):
            _extract_preloaded_state(NO_PRELOADED_STATE_HTML)


class TestPickImageUrl(unittest.TestCase):
    def test_preferred_available(self):
        sources = {"sm": {"url": "sm.jpg"}, "xl": {"url": "xl.jpg"}}
        self.assertEqual(_pick_image_url(sources, "xl"), "xl.jpg")

    def test_fallback(self):
        sources = {"sm": {"url": "sm.jpg"}, "md": {"url": "md.jpg"}}
        self.assertEqual(_pick_image_url(sources, "xl"), "md.jpg")

    def test_empty_sources(self):
        self.assertIsNone(_pick_image_url({}, "xl"))

    def test_empty_url(self):
        sources = {"xl": {"url": ""}, "md": {"url": "md.jpg"}}
        self.assertEqual(_pick_image_url(sources, "xl"), "md.jpg")


class TestGetDesignerShows(unittest.TestCase):
    @patch("vogue._fetch_page")
    def test_parses_shows(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_DESIGNER_PAGE_HTML
        session = MagicMock()
        shows = get_designer_shows("Yohji Yamamoto", session)

        self.assertEqual(len(shows), 3)
        self.assertEqual(shows[0].title, "Fall 2024 Ready-to-Wear")
        self.assertEqual(shows[0].slug, "fall-2024-ready-to-wear")
        self.assertEqual(shows[1].title, "Spring 2024 Ready-to-Wear")
        self.assertEqual(shows[2].title, "Fall 2023 Ready-to-Wear")


class TestGetShowImages(unittest.TestCase):
    @patch("vogue._fetch_page")
    def test_parses_images(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_SHOW_PAGE_HTML
        session = MagicMock()
        images = get_show_images("Yohji Yamamoto", "fall-2024-ready-to-wear", session, "xl")

        self.assertEqual(len(images), 3)
        self.assertEqual(images[0].url, "https://assets.vogue.com/photos/abc/xl.jpg")
        self.assertEqual(images[0].index, 1)
        # Second image has no xl, should fall back to lg then md
        self.assertEqual(images[1].url, "https://assets.vogue.com/photos/def/md.jpg")
        self.assertEqual(images[1].index, 2)
        # Third image only has xl
        self.assertEqual(images[2].url, "https://assets.vogue.com/photos/ghi/xl.jpg")
        self.assertEqual(images[2].index, 3)

    @patch("vogue._fetch_page")
    def test_prefers_md(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_SHOW_PAGE_HTML
        session = MagicMock()
        images = get_show_images("Yohji Yamamoto", "fall-2024-ready-to-wear", session, "md")

        # First image: md is available, should pick md
        self.assertEqual(images[0].url, "https://assets.vogue.com/photos/abc/md.jpg")


class TestGetSeasons(unittest.TestCase):
    @patch("vogue._fetch_page")
    def test_parses_seasons(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_SEASONS_PAGE_HTML
        session = MagicMock()
        seasons = get_seasons(session)

        self.assertEqual(len(seasons), 3)
        self.assertEqual(seasons[0], "Fall 2024 Ready-to-Wear")
        self.assertEqual(seasons[1], "Spring 2025 Couture")
        self.assertEqual(seasons[2], "Resort 2025")


class TestGetSeasonDesigners(unittest.TestCase):
    @patch("vogue._fetch_page")
    def test_parses_designers(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_SEASON_DESIGNERS_HTML
        session = MagicMock()
        designers = get_season_designers("Fall 2024 Ready-to-Wear", session)

        self.assertEqual(len(designers), 3)
        self.assertEqual(designers[0], "Yohji Yamamoto")
        self.assertEqual(designers[1], "Comme des Garçons")
        self.assertEqual(designers[2], "Issey Miyake")


class TestSaveMetadata(unittest.TestCase):
    def test_writes_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "test_collection"
            images = [
                ImageInfo(url="https://example.com/1.jpg", index=1),
                ImageInfo(url="https://example.com/2.jpg", index=2),
            ]
            show = Show(title="Fall 2024 Ready-to-Wear", slug="fall-2024-ready-to-wear")
            collection = Collection(designer="Yohji Yamamoto", show=show, images=images)

            save_metadata(collection, out)

            meta_path = out / "metadata.json"
            self.assertTrue(meta_path.exists())

            with open(meta_path) as f:
                meta = json.load(f)

            self.assertEqual(meta["designer"], "Yohji Yamamoto")
            self.assertEqual(meta["show"]["title"], "Fall 2024 Ready-to-Wear")
            self.assertEqual(meta["image_count"], 2)
            self.assertEqual(len(meta["images"]), 2)
            self.assertEqual(meta["images"][0]["url"], "https://example.com/1.jpg")


class TestCLI(unittest.TestCase):
    """Test CLI argument parsing."""

    @patch("vogue.get_designer_shows")
    @patch("vogue._create_session")
    def test_shows_command(self, mock_session, mock_get_shows):
        mock_get_shows.return_value = [
            Show(title="Fall 2024 Ready-to-Wear", slug="fall-2024-ready-to-wear"),
        ]
        import sys
        with patch.object(sys, 'argv', ['vogue.py', 'shows', '-d', 'Yohji Yamamoto']):
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                from vogue import main
                main()
                output = mock_stdout.getvalue()
                self.assertIn("Fall 2024 Ready-to-Wear", output)
                self.assertIn("1 shows", output)


if __name__ == "__main__":
    unittest.main()
