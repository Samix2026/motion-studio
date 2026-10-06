"""Brand palette reach: an advisory, never a gate."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from design import brand_reach  # noqa: E402

PROFILE = {"id": "four", "identity": {"palette": ["#4285F4", "#ea4335", "#fbbc05", "#34a853"]}}
HTML = """<style>:root {
/* brand:start */
  --brand-primary: #4285f4;
  --brand-progress-fill: linear-gradient(90deg, #4285f4, #ea4335, #fbbc05, #34a853);
/* brand:end */
}
%s</style><div id="root"></div>"""


class BrandReachTest(unittest.TestCase):
    def setUp(self):
        self.p = tempfile.mkdtemp(prefix="ms-brand-")

    def tearDown(self):
        shutil.rmtree(self.p)

    def reach(self, css):
        with open(os.path.join(self.p, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(HTML % css)
        return brand_reach.reach(self.p, PROFILE)

    def test_one_accent_colour_is_flagged(self):
        r = self.reach(".a { color: var(--brand-primary); }")
        self.assertEqual(r["reached"], ["#4285f4"])
        self.assertIn("1 of 4", r["advisory"])

    def test_palette_used_in_scenes_is_quiet(self):
        r = self.reach(".bar { background: var(--brand-progress-fill); }")
        self.assertEqual((len(r["reached"]), r["advisory"]), (4, None))
        r = self.reach(".a{fill:#EA4335}.b{fill:#fbbc05}.c{fill:#34a853}")
        self.assertIsNone(r["advisory"])

    def test_single_colour_brand_is_not_applicable(self):
        with open(os.path.join(self.p, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(HTML % "")
        self.assertEqual(brand_reach.reach(self.p, {"identity": {"palette": ["#76b900"]}})["status"], "not_applicable")
        self.assertEqual(brand_reach.reach(self.p, None)["status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
