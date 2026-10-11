"""Smoke test for the match screen build."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest


class BuildTests(unittest.TestCase):
    def test_build_embeds_every_feed_and_all_captions_are_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "screen.html")
            subprocess.run([sys.executable, "-m", "web.build", "--out", out], check=True,
                           capture_output=True)
            html = open(out, encoding="utf-8").read()
        blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
        data = json.loads(blob.replace("<\\/", "</"))
        self.assertEqual(len(data["feeds"]), 3 * 2 * 3 * 3)
        self.assertNotIn("__DATA__", html)
        for key, feed in data["feeds"].items():
            lang = key.split("|")[0]
            self.assertEqual(feed["summary"]["held_back"], 0, key)
            for o in feed["overlays"]:
                self.assertIn(o["lang"], (lang, "en"), key)
            airs = [(o["air"], o["secs"]) for o in feed["overlays"]]
            for (a, d), (b, _) in zip(airs, airs[1:]):
                self.assertLessEqual(a + d, b, key)   # the editor never lets captions overlap
        self.assertEqual(data["timeline"]["home"][-1], 4)
        self.assertEqual(data["timeline"]["away"][-1], 3)


if __name__ == "__main__":
    unittest.main()
