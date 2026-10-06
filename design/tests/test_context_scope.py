"""Context-scope preflight tests (stdlib unittest).

Run:  python3 -m unittest discover -s design/tests -v
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from design import context_scope  # noqa: E402


VALID = {
    "brand": "anthropic",
    "design_manifest": {
        "brand": {
            "subject": "subject",
            "product": "product",
            "source": "source",
            "identity_mode": "official",
            "reference_scope": "project-only",
            "composition_language": "fresh",
            "inherited_from": None,
            "inheritance_authorized": False,
        },
        "user_identity": {"x_handle": "@example_handle", "show_handle": True},
        "visual_reference": {
            "supplied": False,
            "scope": "project-only",
            "promoted_to_template": False,
        },
    }
}


class PreflightTest(unittest.TestCase):
    def _project(self, meta):
        root = tempfile.mkdtemp()
        with open(os.path.join(root, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        return root

    def test_valid_manifest_passes(self):
        res = context_scope.preflight(self._project(VALID))
        self.assertTrue(res["ok"], res["problems"])
        self.assertEqual([], res["problems"])

    def _with_identity(self, **identity):
        meta = copy.deepcopy(VALID)
        meta["design_manifest"]["user_identity"] = identity
        return context_scope.preflight(self._project(meta))

    def test_placeholder_handle_fails(self):
        res = self._with_identity(x_handle="@your_handle", show_handle=True)
        self.assertFalse(res["ok"])
        self.assertIn("placeholder", " ".join(res["problems"]))

    def test_shown_handle_must_be_set(self):
        self.assertFalse(self._with_identity(x_handle="", show_handle=True)["ok"])

    def test_no_handle_is_a_valid_choice(self):
        for identity in ({"show_handle": False}, {"x_handle": "", "show_handle": False},
                         {"x_handle": None, "show_handle": False}):
            res = context_scope.preflight(self._project(dict(
                copy.deepcopy(VALID), design_manifest=dict(
                    copy.deepcopy(VALID["design_manifest"]), user_identity=identity))))
            self.assertTrue(res["ok"], res["problems"])

    def test_missing_meta_fails(self):
        res = context_scope.preflight(tempfile.mkdtemp())
        self.assertFalse(res["ok"])

    def test_missing_manifest_fails(self):
        res = context_scope.preflight(self._project({"id": "x", "brand": "anthropic"}))
        self.assertFalse(res["ok"])
        self.assertIn("Brand Resolution Gate", res["problems"][0])

    def test_bad_identity_mode_fails(self):
        meta = copy.deepcopy(VALID)
        meta["design_manifest"]["brand"]["identity_mode"] = "leftover"
        self.assertFalse(context_scope.preflight(self._project(meta))["ok"])

    def test_non_project_scope_fails(self):
        meta = copy.deepcopy(VALID)
        meta["design_manifest"]["visual_reference"]["scope"] = "global"
        self.assertFalse(context_scope.preflight(self._project(meta))["ok"])

    def test_promotion_without_authorization_fails(self):
        meta = copy.deepcopy(VALID)
        meta["design_manifest"]["visual_reference"]["promoted_to_template"] = True
        res = context_scope.preflight(self._project(meta))
        self.assertFalse(res["ok"])
        self.assertTrue(any("authorization" in p for p in res["problems"]))

    def test_promotion_with_authorization_passes(self):
        meta = copy.deepcopy(VALID)
        vr = meta["design_manifest"]["visual_reference"]
        vr["promoted_to_template"] = True
        vr["promotion_note"] = "user: make this our default style"
        self.assertTrue(context_scope.preflight(self._project(meta))["ok"])

    def test_missing_composition_language_fails(self):
        meta = copy.deepcopy(VALID)
        del meta["design_manifest"]["brand"]["composition_language"]
        self.assertFalse(context_scope.preflight(self._project(meta))["ok"])

    def test_foundation_passes_without_authorization(self):
        meta = copy.deepcopy(VALID)
        meta["design_manifest"]["brand"]["composition_language"] = "foundation"
        self.assertTrue(context_scope.preflight(self._project(meta))["ok"])

    def test_inherited_without_authorization_fails(self):
        meta = copy.deepcopy(VALID)
        brand = meta["design_manifest"]["brand"]
        brand["composition_language"] = "inherited"
        brand["inherited_from"] = "motion-studio-repo-demo"
        res = context_scope.preflight(self._project(meta))
        self.assertFalse(res["ok"])
        self.assertTrue(any("inheritance_authorized" in p for p in res["problems"]))

    def test_inherited_with_authorization_passes(self):
        meta = copy.deepcopy(VALID)
        brand = meta["design_manifest"]["brand"]
        brand["composition_language"] = "inherited"
        brand["inherited_from"] = "some-series-v1"
        brand["inheritance_authorized"] = True
        self.assertTrue(context_scope.preflight(self._project(meta))["ok"])

    def test_fresh_with_inherited_from_fails(self):
        meta = copy.deepcopy(VALID)
        meta["design_manifest"]["brand"]["inherited_from"] = "motion-studio-repo-demo"
        self.assertFalse(context_scope.preflight(self._project(meta))["ok"])

    def test_top_level_brand_object_is_accepted(self):
        meta = {
            "brand": {
                "subject": "s", "product": "none", "source": "src",
                "identity_mode": "neutral", "reference_scope": "project-only",
                "composition_language": "fresh", "inherited_from": None,
                "inheritance_authorized": False,
            },
            "user_identity": {"x_handle": "@x", "show_handle": False},
            "visual_reference": {"supplied": True, "scope": "project-only",
                                  "promoted_to_template": False},
        }
        self.assertTrue(context_scope.preflight(self._project(meta))["ok"])


def _named_generic(**brand_extra):
    """A named product whose project selected the generic profile."""
    meta = copy.deepcopy(VALID)
    meta["brand"] = "generic"
    brand = meta["design_manifest"]["brand"]
    brand.update({"product": "HyperFrames Studio", "identity_mode": "neutral"})
    brand.update(brand_extra)
    return meta


class BrandResolutionTest(unittest.TestCase):
    def _ok(self, meta):
        return context_scope.preflight(PreflightTest._project(self, meta))

    def test_unbranded_topic_with_generic_passes(self):
        res = self._ok(_named_generic(product="none"))
        self.assertTrue(res["ok"], res["problems"])

    def test_named_product_with_supported_profile_passes(self):
        res = self._ok(VALID)
        self.assertTrue(res["ok"], res["problems"])

    def test_named_product_with_verified_project_identity_passes(self):
        identity = {"source": "https://example.com/brand", "status": "verified",
                    "primary": "#112233", "accent": "#445566",
                    "background": "#000000", "text": "#ffffff"}
        res = self._ok(_named_generic(identity_mode="official", project_identity=identity))
        self.assertTrue(res["ok"], res["problems"])

    def test_incomplete_project_identity_fails(self):
        identity = {"status": "guessed", "primary": "#112233"}
        res = self._ok(_named_generic(identity_mode="official", project_identity=identity))
        self.assertFalse(res["ok"])
        self.assertEqual(3, len(res["problems"]), res["problems"])

    def test_named_product_with_unresolved_generic_fails(self):
        for mode in ("neutral", "official"):
            res = self._ok(_named_generic(identity_mode=mode))
            self.assertFalse(res["ok"], mode)
            self.assertIn("no verified brand identity was resolved", res["problems"][0])

    def test_named_product_with_unknown_profile_fails(self):
        meta = _named_generic()
        meta["brand"] = "not-a-profile"
        self.assertFalse(self._ok(meta)["ok"])

    def test_named_product_with_explicit_neutral_approval_passes(self):
        res = self._ok(_named_generic(neutral_approval="user: no company branding, keep it neutral"))
        self.assertTrue(res["ok"], res["problems"])

    def test_named_product_with_user_reference_passes(self):
        res = self._ok(_named_generic(identity_mode="user-reference"))
        self.assertTrue(res["ok"], res["problems"])


_TEMPLATE = os.path.join(_ROOT, "templates", "tech-news-ar")
_CLAY = ("#d97757", "#a14e33")


def _read(*parts):
    with open(os.path.join(_TEMPLATE, *parts), encoding="utf-8") as fh:
        return fh.read().lower()


class GenericPaletteTest(unittest.TestCase):
    def test_generic_profile_is_achromatic(self):
        text = _read("brands", "generic.json")
        colours = re.findall(r"#[0-9a-f]{6}\b", text)
        self.assertTrue(colours)
        for colour in colours:
            self.assertTrue(colour[1:3] == colour[3:5] == colour[5:7], colour)

    def test_generic_does_not_share_the_anthropic_accent(self):
        generic = json.loads(_read("brands", "generic.json"))["tokens"]
        official = json.loads(_read("brands", "anthropic.json"))["officialcolors"]["primary"]
        for key in ("primary", "highlightcolor", "progressfill", "accentgradient"):
            self.assertNotIn(official, generic[key], key)

    def test_generic_defaults_carry_no_clay(self):
        for parts in (("brands", "generic.json"), ("starter", "standard.html"), ("index.html",),
                      ("lib", "type.css"), ("lib", "grammar.css")):
            text = _read(*parts)
            for colour in _CLAY:
                self.assertNotIn(colour, text, "%s in %s" % (colour, "/".join(parts)))

    def test_starters_match_the_generic_profile(self):
        tokens = json.loads(_read("brands", "generic.json"))["tokens"]
        for name in (os.path.join("starter", "standard.html"), "index.html"):
            html = _read(name)
            for key in ("primary", "background", "text", "accentgradient"):
                self.assertIn(tokens[key], html, "%s: %s" % (name, key))


if __name__ == "__main__":
    unittest.main()
