"""Project context-scope preflight (read-only).

Enforces the NEW PROJECT CONTEXT CHECK and the Brand Resolution Gate manifest
defined in `CONTEXT_SCOPE.md`. Never writes to a project.

A project records a `design_manifest` in `meta.json` describing:

  brand:            subject, product, source, identity_mode, reference_scope,
                    composition_language, inherited_from, inheritance_authorized,
                    project_identity (optional), neutral_approval (optional)
  user_identity:    x_handle, show_handle
  visual_reference: supplied, scope, promoted_to_template

The preflight fails when the manifest is missing or incomplete, when a scope is
not `project-only`, when a project reference has been promoted to a template
without a recorded authorization, or when a named prior project's one-off
composition is inherited without explicit authorization. Building on the shared
foundation (`composition_language: foundation`) needs no authorization.

It also fails when `brand.product` names a product/company (anything but
`none`) whose identity was never resolved: no supported profile in `"brand"`,
no user-supplied reference, no `project_identity`, and no `neutral_approval`.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from design.brand_reach import BRANDS_DIR

IDENTITY_MODES = ("official", "user-reference", "neutral")
# Literal the templates ship in place of the owner's social handle; never rendered.
HANDLE_PLACEHOLDER = "@your_handle"
UNBRANDED_PRODUCTS = ("none", "n/a")
PROJECT_IDENTITY_STATUSES = ("verified", "user-approved")
PROJECT_IDENTITY_COLOURS = ("primary", "accent", "background", "text")
COMPOSITION_LANGUAGES = ("foundation", "fresh", "inherited")


def _read_manifest(project_dir: str) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
    """Return (manifest, selected profile id from top-level "brand", error)."""
    path = os.path.join(project_dir, "meta.json")
    if not os.path.isfile(path):
        return None, None, "meta.json not found"
    try:
        with open(path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, None, "meta.json is not valid JSON: %s" % exc
    if not isinstance(meta, dict):
        return None, None, "meta.json is not a JSON object"
    manifest = meta.get("design_manifest")
    if manifest is None and isinstance(meta.get("brand"), dict):
        # Backward-compatible shape: brand/user_identity/visual_reference at top level.
        manifest = {
            "brand": meta.get("brand"),
            "user_identity": meta.get("user_identity", {}),
            "visual_reference": meta.get("visual_reference", {}),
        }
    if manifest is None:
        return None, None, "no design_manifest in meta.json (run the Brand Resolution Gate)"
    if not isinstance(manifest, dict):
        return None, None, "design_manifest is not an object"
    profile = meta.get("brand")
    return manifest, profile if isinstance(profile, str) else None, None


def _is_bool(value) -> bool:
    return isinstance(value, bool)


def _resolution_problems(brand: Dict, profile: Optional[str]) -> List[str]:
    """Brand Resolution Gate: a named product/company never falls through to generic."""
    product = str(brand.get("product", "")).strip()
    if not product or product.lower() in UNBRANDED_PRODUCTS:
        return []  # genuinely unbranded subject: generic is the correct profile
    if brand.get("identity_mode") == "user-reference":
        return []  # resolved from a current-project reference
    if profile and profile != "generic" and os.path.isfile(
            os.path.join(BRANDS_DIR, "%s.json" % os.path.basename(profile))):
        return []  # supported brand profile
    identity = brand.get("project_identity")
    if identity is not None:
        if not isinstance(identity, dict):
            return ["brand.project_identity must be an object"]
        problems = []
        if not str(identity.get("source", "")).strip():
            problems.append("brand.project_identity.source is missing (official/approved source of the identity)")
        if identity.get("status") not in PROJECT_IDENTITY_STATUSES:
            problems.append("brand.project_identity.status must be one of %s" % (PROJECT_IDENTITY_STATUSES,))
        missing = [k for k in PROJECT_IDENTITY_COLOURS if not str(identity.get(k, "")).strip()]
        if missing:
            problems.append("brand.project_identity is missing colour(s): %s" % ", ".join(missing))
        return problems
    if str(brand.get("neutral_approval", "")).strip():
        return []  # explicit user-approved neutral/generic treatment
    return [
        "named product/company %r detected but no verified brand identity was resolved "
        "(profile: %r). Select its profile from brands/, record brand.project_identity "
        "from official sources, or record brand.neutral_approval (the user's explicit "
        "request for a neutral treatment) before composition" % (product, profile)
    ]


def preflight(project_dir: str) -> Dict:
    problems: List[str] = []
    manifest, profile, err = _read_manifest(project_dir)
    if err is not None:
        return {"ok": False, "project": project_dir, "problems": [err], "manifest": None}

    brand = manifest.get("brand")
    if not isinstance(brand, dict):
        problems.append("brand must be an object")
        brand = {}
    for key in ("subject", "product", "source"):
        if not str(brand.get(key, "")).strip():
            problems.append("brand.%s is missing or empty" % key)
    if brand.get("identity_mode") not in IDENTITY_MODES:
        problems.append("brand.identity_mode must be one of %s" % (IDENTITY_MODES,))
    if brand.get("reference_scope") != "project-only":
        problems.append("brand.reference_scope must be 'project-only'")

    problems.extend(_resolution_problems(brand, profile))

    comp = brand.get("composition_language")
    if comp not in COMPOSITION_LANGUAGES:
        problems.append("brand.composition_language must be one of %s" % (COMPOSITION_LANGUAGES,))
    inherited_from = brand.get("inherited_from")
    inheritance_authorized = brand.get("inheritance_authorized")
    if not _is_bool(inheritance_authorized):
        problems.append("brand.inheritance_authorized must be a boolean")
    if comp in ("foundation", "fresh"):
        if inherited_from not in (None, ""):
            problems.append("brand.inherited_from must be null when composition_language is '%s'" % comp)
    elif comp == "inherited":
        if not str(inherited_from or "").strip():
            problems.append("brand.inherited_from is required when composition_language is 'inherited'")
        if inheritance_authorized is not True:
            problems.append(
                "brand.composition_language 'inherited' requires inheritance_authorized: true "
                "(explicit user authorization)"
            )

    user_identity = manifest.get("user_identity")
    if not isinstance(user_identity, dict):
        problems.append("user_identity must be an object")
        user_identity = {}
    show_handle = user_identity.get("show_handle")
    if not _is_bool(show_handle):
        problems.append("user_identity.show_handle must be a boolean")
    handle = str(user_identity.get("x_handle") or "").strip()
    if show_handle is not False:  # no handle is valid, but only as an explicit choice
        if not handle:
            problems.append("user_identity.x_handle is missing (set show_handle: false for a "
                            "video without a social handle)")
        elif handle == HANDLE_PLACEHOLDER:
            problems.append("user_identity.x_handle is still the placeholder %s: set your own "
                            "handle, or set show_handle: false" % HANDLE_PLACEHOLDER)

    vr = manifest.get("visual_reference")
    if not isinstance(vr, dict):
        problems.append("visual_reference must be an object")
        vr = {}
    if not _is_bool(vr.get("supplied")):
        problems.append("visual_reference.supplied must be a boolean")
    if vr.get("scope") != "project-only":
        problems.append("visual_reference.scope must be 'project-only'")
    promoted = vr.get("promoted_to_template")
    if not _is_bool(promoted):
        problems.append("visual_reference.promoted_to_template must be a boolean")
    elif promoted:
        authorized = (str(vr.get("promotion_authorized_by", "")).strip()
                      or str(vr.get("promotion_note", "")).strip())
        if not authorized:
            problems.append(
                "visual_reference.promoted_to_template is true without a recorded "
                "authorization (set promotion_authorized_by or promotion_note)"
            )

    return {"ok": not problems, "project": project_dir,
            "problems": problems, "manifest": manifest}
