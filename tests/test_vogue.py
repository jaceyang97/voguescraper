"""Tests for the vogue CLI and scraper — mocked HTTP, no network required."""

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from vogue.cli import CLIError, _pop_flag, _pop_value, _truncate, cmd_designers, cmd_shows
from vogue.scraper import (
    Collection,
    ImageInfo,
    Show,
    _extract_preloaded_state,
    _pick_image_url,
    get_designer_shows,
    get_show_images,
    save_metadata,
    slugify,
)


# ---------------------------------------------------------------------------
# Fixtures — simulate Vogue's __PRELOADED_STATE__ JSON
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

NO_PRELOADED_STATE_HTML = """
<!DOCTYPE html>
<html><body><p>No data here</p></body></html>
"""


# ---------------------------------------------------------------------------
# Scraper tests
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
    @patch("vogue.scraper._fetch_page")
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
    @patch("vogue.scraper._fetch_page")
    def test_parses_images(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_SHOW_PAGE_HTML
        session = MagicMock()
        images = get_show_images("Yohji Yamamoto", "fall-2024-ready-to-wear", session, "xl")

        self.assertEqual(len(images), 3)
        self.assertEqual(images[0].url, "https://assets.vogue.com/photos/abc/xl.jpg")
        self.assertEqual(images[0].index, 1)
        self.assertEqual(images[1].url, "https://assets.vogue.com/photos/def/md.jpg")
        self.assertEqual(images[1].index, 2)
        self.assertEqual(images[2].url, "https://assets.vogue.com/photos/ghi/xl.jpg")
        self.assertEqual(images[2].index, 3)

    @patch("vogue.scraper._fetch_page")
    def test_prefers_md(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_SHOW_PAGE_HTML
        session = MagicMock()
        images = get_show_images("Yohji Yamamoto", "fall-2024-ready-to-wear", session, "md")
        self.assertEqual(images[0].url, "https://assets.vogue.com/photos/abc/md.jpg")


class TestSaveMetadata(unittest.TestCase):
    def test_writes_json(self):
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

            meta = json.loads(meta_path.read_text())
            self.assertEqual(meta["designer"], "Yohji Yamamoto")
            self.assertEqual(meta["show"]["title"], "Fall 2024 Ready-to-Wear")
            self.assertEqual(meta["image_count"], 2)
            self.assertEqual(len(meta["images"]), 2)
            self.assertEqual(meta["images"][0]["url"], "https://example.com/1.jpg")


# ---------------------------------------------------------------------------
# CLI helper tests
# ---------------------------------------------------------------------------


class TestPopFlag(unittest.TestCase):
    def test_found(self):
        args = ["foo", "--json", "bar"]
        self.assertTrue(_pop_flag(args, "--json"))
        self.assertEqual(args, ["foo", "bar"])

    def test_not_found(self):
        args = ["foo", "bar"]
        self.assertFalse(_pop_flag(args, "--json"))
        self.assertEqual(args, ["foo", "bar"])

    def test_multiple_names(self):
        args = ["foo", "-j"]
        self.assertTrue(_pop_flag(args, "--json", "-j"))
        self.assertEqual(args, ["foo"])

    def test_duplicate(self):
        args = ["--json", "foo", "--json"]
        self.assertTrue(_pop_flag(args, "--json"))
        self.assertEqual(args, ["foo"])


class TestPopValue(unittest.TestCase):
    def test_found(self):
        args = ["foo", "-r", "lg", "bar"]
        self.assertEqual(_pop_value(args, "-r"), "lg")
        self.assertEqual(args, ["foo", "bar"])

    def test_not_found(self):
        args = ["foo", "bar"]
        self.assertIsNone(_pop_value(args, "-r"))

    def test_default(self):
        args = ["foo"]
        self.assertEqual(_pop_value(args, "-r", default="xl"), "xl")

    def test_long_flag(self):
        args = ["--resolution", "md", "foo"]
        self.assertEqual(_pop_value(args, "-r", "--resolution"), "md")
        self.assertEqual(args, ["foo"])


class TestTruncate(unittest.TestCase):
    def test_short_list(self):
        lines = ["a", "b", "c"]
        result, notice = _truncate(lines)
        self.assertEqual(result, lines)
        self.assertIsNone(notice)

    def test_long_list(self):
        lines = [f"line-{i}" for i in range(300)]
        result, notice = _truncate(lines)
        self.assertEqual(len(result), 200)
        self.assertEqual(result[0], "line-0")
        self.assertIn("300", notice)
        self.assertIn("truncated", notice)


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestCmdDesigners(unittest.TestCase):
    @patch("vogue.cli.create_session")
    @patch("vogue.cli.get_all_designers")
    def test_search(self, mock_designers, mock_session):
        mock_designers.return_value = ["Christian Dior", "Dior Homme", "Prada"]
        with patch("sys.stdout", new_callable=StringIO) as out:
            count = cmd_designers(["dior"])
        self.assertEqual(count, 2)
        self.assertIn("Christian Dior", out.getvalue())
        self.assertIn("Dior Homme", out.getvalue())
        self.assertNotIn("Prada", out.getvalue())

    @patch("vogue.cli.create_session")
    @patch("vogue.cli.get_all_designers")
    def test_no_match(self, mock_designers, mock_session):
        mock_designers.return_value = ["Prada", "Gucci"]
        with self.assertRaises(CLIError) as ctx:
            cmd_designers(["dior"])
        self.assertIn("No designers found", ctx.exception.message)

    @patch("vogue.cli.create_session")
    @patch("vogue.cli.get_all_designers")
    def test_json_output(self, mock_designers, mock_session):
        mock_designers.return_value = ["Prada", "Gucci"]
        with patch("sys.stdout", new_callable=StringIO) as out:
            count = cmd_designers(["--json"])
        self.assertEqual(count, 2)
        data = json.loads(out.getvalue())
        self.assertEqual(data, ["Prada", "Gucci"])


class TestCmdShows(unittest.TestCase):
    @patch("vogue.cli.create_session")
    @patch("vogue.cli.get_designer_shows")
    def test_lists_shows(self, mock_shows, mock_session):
        mock_shows.return_value = [
            Show(title="Fall 2024 Ready-to-Wear", slug="fall-2024-ready-to-wear"),
        ]
        with patch("sys.stdout", new_callable=StringIO) as out:
            count = cmd_shows(["Yohji Yamamoto"])
        self.assertEqual(count, 1)
        self.assertIn("fall-2024-ready-to-wear", out.getvalue())
        self.assertIn("Fall 2024 Ready-to-Wear", out.getvalue())

    def test_missing_designer(self):
        with self.assertRaises(CLIError) as ctx:
            cmd_shows([])
        self.assertIn("usage:", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
