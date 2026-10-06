"""Visual-first check: storyboard block, declared visual roles, text-only limit."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from design import visual_story  # noqa: E402

SCENE = '<section id="s%d" class="clip" data-start="%d" data-duration="1"%s>%s</section>'
IMG = '<img src="assets/a.png" alt=""><h1>caption</h1>'
OBJ = '<div class="bar" data-object></div><p>caption</p>'
TXT = "<h1>headline only</h1>"

BEAT = "### Beat %d\n- SEE: the context window as a strip that keeps extending\n" \
       "- DOES: the strip grows from 64K to 1M\n- READ: 1M\n"


def storyboard(n, assets="- hero.png — official product image (blog)"):
    return "# Storyboard\n\n## Source assets\n%s\n\n## Visual story\n%s" % (assets, "".join(BEAT % i for i in range(n)))


class VisualStoryTest(unittest.TestCase):
    def setUp(self):
        self.p = tempfile.mkdtemp(prefix="ms-visual-")

    def tearDown(self):
        shutil.rmtree(self.p)

    def project(self, scenes, board=None):
        html = "".join(SCENE % (i, i, (' data-visual="%s"' % role) if role else "", body)
                       for i, (role, body) in enumerate(scenes))
        with open(os.path.join(self.p, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html><body><div id='root'>%s</div></body></html>" % html)
        if board is not None:
            with open(os.path.join(self.p, "storyboard.md"), "w", encoding="utf-8") as fh:
                fh.write(board)
        return [e["code"] for e in visual_story.check(self.p)["errors"]]

    def test_visual_scenes_with_one_text_takeaway_pass(self):
        scenes = [("source-image", IMG), ("object", OBJ), ("data", OBJ), ("interface", IMG), ("text", TXT)]
        self.assertEqual(self.project(scenes, storyboard(5)), [])

    def test_missing_visual_story_block_fails(self):
        scenes = [("object", OBJ), ("text", TXT)]
        codes = self.project(scenes, "# Storyboard\n\n| 1 | hook | kinetic_word | headline |\n")
        self.assertEqual(set(codes), {"visual_story_missing"})
        self.assertEqual(len(codes), 4)  # source assets + SEE + DOES + READ

    def test_unfilled_template_placeholders_do_not_count(self):
        board = "## Source assets\n[[list or none usable]]\n\n- SEE: [[what the viewer sees]]\n- DOES: [[motion]]\n- READ: [[text]]\n"
        self.assertEqual(set(self.project([("object", OBJ)], board)), {"visual_story_missing"})

    def test_scene_without_a_visual_role_fails(self):
        self.assertEqual(self.project([("object", OBJ), (None, TXT)], storyboard(2)), ["visual_role_missing"])

    def test_more_than_one_text_only_scene_fails(self):
        scenes = [("text", TXT), ("object", OBJ), ("text", TXT), ("text", TXT)]
        self.assertEqual(self.project(scenes, storyboard(4)), ["too_many_text_scenes"])
        self.assertEqual(visual_story.check(self.p, max_text_only=3)["errors"], [])

    def test_headline_on_a_blank_background_is_not_a_visual_scene(self):
        self.assertEqual(self.project([("object", TXT)], storyboard(1)), ["visual_role_unbacked"])

    def test_custom_roles_and_scenes_without_a_grammar_are_valid(self):
        scenes = [("globe-map", '<canvas id="c"></canvas>'), ("object diagram", OBJ)]
        res_codes = self.project(scenes, storyboard(2))
        self.assertEqual(res_codes, [])
        self.assertTrue(visual_story.check(self.p)["advisories"], "an uncommon role is only an advisory")

    def test_source_assets_are_optional_when_none_are_usable(self):
        scenes = [("object", OBJ), ("diagram", OBJ)]
        board = storyboard(2, assets="none usable — the announcement page has only a generic banner")
        self.assertEqual(self.project(scenes, board), [])

    def test_legacy_project_is_not_enforced(self):
        self.assertEqual(self.project([(None, TXT), (None, TXT)]), [])
        self.assertFalse(visual_story.check(self.p)["enforced"])


if __name__ == "__main__":
    unittest.main()
