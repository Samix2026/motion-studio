"""Phase 1 manifest tests: registration, revisions, integrity, and persistence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import contracts as c  # noqa: E402
from studio import manifest  # noqa: E402

TS = "2026-01-01T00:00:00+00:00"


def dir_hash(path: str) -> str:
    h = hashlib.sha256()
    for base, _d, names in os.walk(path):
        for n in sorted(names):
            p = os.path.join(base, n)
            h.update(os.path.relpath(p, path).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class ManifestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="studio-man-")
        self.ws = os.path.realpath(os.path.join(self.tmp, "ws"))
        self.proj = os.path.join(self.ws, "videos", "proj")
        self.rev2 = os.path.join(self.ws, "videos", "proj-rev2")
        self.rev3 = os.path.join(self.ws, "videos", "proj-rev3")
        for base in (self.proj, self.rev2, self.rev3):
            os.makedirs(os.path.join(base, "renders"))
        self.write(self.proj, "index.html", b"<html>rev1</html>")
        self.write(self.proj, "renders/video.mp4", b"AAAA")
        self.write(self.rev2, "index.html", b"<html>rev2</html>")
        self.write(self.rev2, "renders/video.mp4", b"BBBB")
        self.write(self.rev2, "renders/other.mp4", b"CCCC")
        manifest.register_project(self.ws, "proj", "videos/proj", created_at=TS)
        manifest.create_run(self.ws, "proj", "run-1", "rev1", "videos/proj", created_at=TS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, base, rel, payload):
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(payload)
        return path

    def build_valid_run(self, rid="run-1", comp="comp-1", render="render-1",
                        out="renders/video.mp4"):
        manifest.record_attempt(self.ws, "proj", rid, "att-comp", "composition", "external",
                                "succeeded", output_artifact_ids=[comp], created_at=TS)
        manifest.register_artifact(self.ws, "proj", rid, comp, "composition", "project",
                                   "index.html", producer_attempt_id="att-comp", created_at=TS)
        manifest.record_attempt(self.ws, "proj", rid, "att-render", "render", "external",
                                "succeeded", input_artifact_ids=[comp],
                                output_artifact_ids=[render], created_at=TS)
        manifest.register_artifact(self.ws, "proj", rid, render, "render", "project",
                                   out, producer_attempt_id="att-render", created_at=TS)


class TestRegistration(ManifestBase):
    def test_registration_is_opt_in(self):
        self.assertEqual(["proj.json"], sorted(os.listdir(manifest.projects_dir(self.ws))))
        self.assertEqual(1, len(manifest.list_runs(self.ws)))

    def test_no_automatic_registration(self):
        self.assertIsNone(manifest.load_project(self.ws, "proj-rev2"))
        self.assertEqual(1, len(os.listdir(manifest.projects_dir(self.ws))))

    def test_duplicate_identity_collisions(self):
        with self.assertRaises(c.DuplicateIdentityError):
            manifest.register_project(self.ws, "proj", "videos/proj", created_at=TS)
        with self.assertRaises(c.DuplicateIdentityError):
            manifest.register_project(self.ws, "proj-2", self.proj, created_at=TS)
        with self.assertRaises(c.DuplicateIdentityError):
            manifest.create_run(self.ws, "proj", "run-1", "rev1", "videos/proj", created_at=TS)

    def test_absolute_and_relative_resolve_consistently(self):
        self.assertEqual("videos/proj", manifest.load_project(self.ws, "proj")["project_dir"])
        with self.assertRaises(c.DuplicateIdentityError):
            manifest.register_project(self.ws, "alias", self.proj, created_at=TS)


class TestPathContainment(ManifestBase):
    def test_traversal_and_absolute_ids_rejected(self):
        for bad in ("../evil", "/etc/evil", "a/b", ".."):
            with self.assertRaises(c.MalformedRecordError):
                manifest.load_project(self.ws, bad)
            with self.assertRaises(c.MalformedRecordError):
                manifest.load_run(self.ws, "proj", bad)
            with self.assertRaises(c.MalformedRecordError):
                manifest.run_lock_path(self.ws, "proj", bad)

    def test_symlinked_registry_directory_rejected(self):
        ws = os.path.join(self.tmp, "ws-reg")
        os.makedirs(os.path.join(ws, "videos", "p"))
        os.makedirs(os.path.join(ws, "runs"))
        outside = os.path.join(self.tmp, "outside-projects")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(ws, "runs", "projects"))
        with self.assertRaises(c.PathSafetyError):
            manifest.register_project(os.path.realpath(ws), "p", "videos/p", created_at=TS)
        self.assertEqual([], os.listdir(outside))

    def test_symlinked_manifest_directory_rejected(self):
        ws = os.path.realpath(os.path.join(self.tmp, "ws-man"))
        os.makedirs(os.path.join(ws, "videos", "p"))
        os.makedirs(os.path.join(ws, "runs"))
        manifest.register_project(ws, "p", "videos/p", created_at=TS)
        outside = os.path.join(self.tmp, "outside-manifests")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(ws, "runs", "manifests"))
        with self.assertRaises(c.PathSafetyError):
            manifest.create_run(ws, "p", "r1", "rev1", "videos/p", created_at=TS)
        self.assertEqual([], os.listdir(outside))

    def test_symlinked_lock_directory_rejected(self):
        ws = os.path.realpath(os.path.join(self.tmp, "ws-lock"))
        os.makedirs(os.path.join(ws, "videos", "p"))
        os.makedirs(os.path.join(ws, "runs"))
        outside = os.path.join(self.tmp, "outside-locks")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(ws, "runs", ".locks"))
        with self.assertRaises(c.PathSafetyError):
            manifest.register_project(ws, "p", "videos/p", created_at=TS)
        self.assertEqual([], os.listdir(outside))

    def test_enumeration_rejects_refused_symlink_alias(self):
        ws = os.path.realpath(os.path.join(self.tmp, "ws-enum"))
        os.makedirs(os.path.join(ws, "videos", "p"))
        os.makedirs(os.path.join(ws, "runs", "projects"))
        with open(os.path.join(ws, ".env"), "w", encoding="utf-8") as fh:
            fh.write("SECRET=1")
        os.symlink(os.path.join(ws, ".env"),
                   os.path.join(ws, "runs", "projects", "evil.json"))
        with self.assertRaises(c.PathSafetyError):
            manifest.register_project(ws, "p", "videos/p", created_at=TS)


class TestRevisionBinding(ManifestBase):
    def test_two_revisions_resolve_independently(self):
        manifest.create_run(self.ws, "proj", "run-2", "rev2", "videos/proj-rev2", created_at=TS)
        self.build_valid_run("run-1", "comp-1", "render-1")
        self.build_valid_run("run-2", "comp-2", "render-2")
        first = manifest.inspect_run(self.ws, "proj", "run-1")
        second = manifest.inspect_run(self.ws, "proj", "run-2")
        self.assertEqual("videos/proj", first["revision_dir"])
        self.assertEqual("videos/proj-rev2", second["revision_dir"])
        self.assertEqual("ok", first["artifacts"][-1]["state"])
        self.assertEqual("ok", second["artifacts"][-1]["state"])
        self.assertNotEqual(first["artifacts"][-1]["expected_sha256"],
                            second["artifacts"][-1]["expected_sha256"])
        manifest.validate_run_manifest(manifest.load_run(self.ws, "proj", "run-1"), workspace=self.ws)
        manifest.validate_run_manifest(manifest.load_run(self.ws, "proj", "run-2"), workspace=self.ws)

    def test_workspace_relocation_preserves_bindings(self):
        manifest.create_run(self.ws, "proj", "run-2", "rev2", "videos/proj-rev2", created_at=TS)
        self.build_valid_run("run-1", "comp-1", "render-1")
        self.build_valid_run("run-2", "comp-2", "render-2")
        moved = os.path.join(self.tmp, "ws-moved")
        shutil.move(self.ws, moved)
        first = manifest.inspect_run(moved, "proj", "run-1")
        second = manifest.inspect_run(moved, "proj", "run-2")
        self.assertEqual("videos/proj", first["revision_dir"])
        self.assertEqual("videos/proj-rev2", second["revision_dir"])
        self.assertEqual("ok", first["artifacts"][-1]["state"])
        self.assertEqual("ok", second["artifacts"][-1]["state"])

    def test_ambiguous_names_do_not_auto_link(self):
        manifest.register_project(self.ws, "proj-rev2", "videos/proj-rev2", created_at=TS)
        manifest.register_project(self.ws, "proj-rev3", "videos/proj-rev3", created_at=TS)
        for pid in ("proj", "proj-rev2", "proj-rev3"):
            self.assertIsNone(manifest.load_project(self.ws, pid)["parent_revision"])
        self.assertEqual(3, len(os.listdir(manifest.projects_dir(self.ws))))

    def test_revision_dir_must_be_contained_and_exist(self):
        with self.assertRaises(c.PathSafetyError):
            manifest.create_run(self.ws, "proj", "run-x", "revx", "../outside", created_at=TS)
        with self.assertRaises(c.PathSafetyError):
            manifest.create_run(self.ws, "proj", "run-y", "revy", "videos/missing", created_at=TS)


class TestSchemaValidation(ManifestBase):
    def test_malformed_existing_record_is_rejected(self):
        path = os.path.join(manifest.projects_dir(self.ws), "broken.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(c.MalformedRecordError):
            manifest.load_project(self.ws, "broken")

    def test_unsupported_workflow_contract_version_on_load(self):
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        run = manifest.load_run(self.ws, "proj", "run-1")
        run["workflow_contract_version"] = "bogus"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run, fh)
        with self.assertRaises(c.SchemaVersionError):
            manifest.load_run(self.ws, "proj", "run-1")

    def test_unsupported_stage_contract_version_on_load(self):
        self.build_valid_run()
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        run = manifest.load_run(self.ws, "proj", "run-1")
        run["attempts"]["att-comp"]["stage_contract_version"] = "bogus"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run, fh)
        with self.assertRaises(c.SchemaVersionError):
            manifest.load_run(self.ws, "proj", "run-1")

    def test_stored_identity_must_match_storage_path(self):
        src = manifest.manifest_path(self.ws, "proj", "run-1")
        with open(src, "r", encoding="utf-8") as fh:
            run = json.load(fh)
        dst = os.path.join(manifest.manifests_dir(self.ws), "proj", "run-2.json")
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump(run, fh)
        with self.assertRaises(c.MalformedRecordError):
            manifest.load_run(self.ws, "proj", "run-2")

    def test_missing_required_key(self):
        run = manifest.load_run(self.ws, "proj", "run-1")
        del run["revision_dir"]
        with self.assertRaises(c.MalformedRecordError):
            manifest.validate_run_structure(run)

    def test_duplicate_artifact_id(self):
        os.makedirs(os.path.join(self.ws, "runs"), exist_ok=True)
        legacy = os.path.join(self.ws, "runs", "legacy.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            fh.write("{}")
        manifest.register_artifact(self.ws, "proj", "run-1", "leg-1", "legacy_run_summary",
                                   "workspace", "runs/legacy.json", legacy_external=True,
                                   created_at=TS)
        with self.assertRaises(c.DuplicateIdentityError):
            manifest.register_artifact(self.ws, "proj", "run-1", "leg-1", "script",
                                       "project", "index.html", legacy_external=True,
                                       created_at=TS)

    def test_invalid_references_fail_clearly(self):
        with self.assertRaises(c.UnknownReferenceError):
            manifest.record_attempt(self.ws, "proj", "run-1", "att-x", "render", "external",
                                    "succeeded", input_artifact_ids=["ghost"], created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "render", "external",
                                "succeeded", output_artifact_ids=["ghost"], created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        with self.assertRaises(c.UnknownReferenceError):
            manifest.validate_run_manifest(run)

    def test_unknown_producer_reference(self):
        with self.assertRaises(c.UnknownReferenceError):
            manifest.register_artifact(self.ws, "proj", "run-1", "render-1", "render",
                                       "project", "renders/video.mp4",
                                       producer_attempt_id="missing", created_at=TS)

    def test_existing_structure_validated_before_mutation(self):
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        with open(path, "r", encoding="utf-8") as fh:
            run = json.load(fh)
        del run["narration_enabled"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run, fh)
        with open(path, "rb") as fh:
            before = fh.read()
        with self.assertRaises(c.MalformedRecordError):
            manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "render", "external",
                                    "unknown", created_at=TS)
        with open(path, "rb") as fh:
            self.assertEqual(before, fh.read())


class TestRelationships(ManifestBase):
    def test_output_producer_must_agree_at_registration(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-comp", "composition", "external",
                                "succeeded", output_artifact_ids=["comp-1"], created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-1", "comp-1", "composition", "project",
                                   "index.html", producer_attempt_id="att-comp", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-1", "att-render", "render", "external",
                                "succeeded", input_artifact_ids=["comp-1"],
                                output_artifact_ids=["render-1"], created_at=TS)
        with self.assertRaises(c.ContractError):
            manifest.register_artifact(self.ws, "proj", "run-1", "render-1", "render", "project",
                                       "renders/video.mp4", producer_attempt_id="att-comp",
                                       created_at=TS)

    def test_stored_producer_conflict_detected(self):
        self.build_valid_run()
        run = manifest.load_run(self.ws, "proj", "run-1")
        run["artifacts"]["render-1"]["producer_attempt_id"] = "att-comp"
        with self.assertRaises(c.ContractError):
            manifest.validate_run_manifest(run)

    def test_validation_evidence_must_be_registered(self):
        with self.assertRaises(c.UnknownReferenceError):
            manifest.record_validation(self.ws, "proj", "run-1", "val-1", "ffprobe", "6.0",
                                       "reports/ffprobe.txt", "ghost-evidence", "passed",
                                       "render", created_at=TS)

    def test_missing_or_changed_evidence_detected(self):
        self.build_valid_run()
        evidence = self.write(self.proj, "evidence.txt", b"EVIDENCE")
        manifest.register_artifact(self.ws, "proj", "run-1", "ev-1", "validation_evidence",
                                   "project", "evidence.txt", legacy_external=True,
                                   created_at=TS)
        manifest.record_validation(self.ws, "proj", "run-1", "val-1", "ffprobe", "6.0",
                                   "evidence.txt", "ev-1", "passed", "render",
                                   subject_artifact_ids=["render-1"], created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        manifest.validate_run_manifest(run, workspace=self.ws)
        os.unlink(evidence)
        with self.assertRaises(c.ContractError):
            manifest.validate_run_manifest(manifest.load_run(self.ws, "proj", "run-1"),
                                           workspace=self.ws)
        self.write(self.proj, "evidence.txt", b"TAMPERED")
        with self.assertRaises(c.ContractError):
            manifest.validate_run_manifest(manifest.load_run(self.ws, "proj", "run-1"),
                                           workspace=self.ws)

    def test_dangling_supersession_rejected(self):
        with self.assertRaises(c.UnknownReferenceError):
            manifest.record_attempt(self.ws, "proj", "run-1", "att-2", "render", "external",
                                    "failed", supersedes="ghost", created_at=TS)

    def test_historical_reference_must_agree_with_artifact(self):
        os.makedirs(os.path.join(self.ws, "runs"), exist_ok=True)
        with open(os.path.join(self.ws, "runs", "legacy.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        manifest.historical_reference(self.ws, "proj", "run-1", "legacy-1", "workspace",
                                      "runs/legacy.json", created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        tampered = json.loads(json.dumps(run))
        tampered["historical_references"][0]["sha256"] = "d" * 64
        with self.assertRaises(c.ContractError):
            manifest.validate_run_manifest(tampered)

    def test_genuine_legacy_artifact_needs_no_producer(self):
        os.makedirs(os.path.join(self.ws, "runs"), exist_ok=True)
        with open(os.path.join(self.ws, "runs", "legacy.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        manifest.historical_reference(self.ws, "proj", "run-1", "legacy-1", "workspace",
                                      "runs/legacy.json", created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        self.assertTrue(run["artifacts"]["legacy-1"]["legacy_external"])
        self.assertIsNone(run["artifacts"]["legacy-1"]["producer_attempt_id"])
        manifest.validate_run_manifest(run)


class TestDeferredReferences(ManifestBase):
    def test_deferred_output_state_is_explicit_and_read_only(self):
        manifest.create_run(self.ws, "proj", "run-defer", "rev1", "videos/proj", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-defer", "att-comp", "composition",
                                "external", "succeeded", output_artifact_ids=["comp-1"],
                                created_at=TS)
        runs_before = dir_hash(os.path.join(self.ws, "runs"))
        first = manifest.inspect_run(self.ws, "proj", "run-defer")
        self.assertFalse(first["reference_resolution"])
        self.assertFalse(first["reference_validity"])
        self.assertFalse(first["complete"])
        self.assertIn("comp-1", first["unresolved_reference_ids"])
        attempt = first["attempts"][0]
        self.assertFalse(attempt["complete"])
        self.assertIn("comp-1", attempt["unresolved_output_ids"])
        self.assertEqual(runs_before, dir_hash(os.path.join(self.ws, "runs")))

        original = manifest.load_run(self.ws, "proj", "run-defer")["attempts"]["att-comp"]
        manifest.register_artifact(self.ws, "proj", "run-defer", "comp-1", "composition",
                                   "project", "index.html", producer_attempt_id="att-comp",
                                   created_at=TS)
        second = manifest.inspect_run(self.ws, "proj", "run-defer")
        self.assertTrue(second["reference_resolution"])
        self.assertTrue(second["relationship_validity"])
        self.assertTrue(second["stage_contract_validity"])
        self.assertTrue(second["complete"])
        self.assertEqual([], second["unresolved_reference_ids"])
        self.assertTrue(second["attempts"][0]["complete"])
        after = manifest.load_run(self.ws, "proj", "run-defer")["attempts"]["att-comp"]
        self.assertEqual(original, after)

    def test_historical_reference_labeled(self):
        os.makedirs(os.path.join(self.ws, "runs"), exist_ok=True)
        with open(os.path.join(self.ws, "runs", "legacy.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        manifest.historical_reference(self.ws, "proj", "run-1", "legacy-1", "workspace",
                                      "runs/legacy.json", note="imported", created_at=TS)
        report = manifest.inspect_run(self.ws, "proj", "run-1")
        self.assertEqual("historical_reference_only",
                         report["historical_references"][0]["verification_state"])


class TestStageHandoffs(ManifestBase):
    def test_narration_input_and_composition_output_pass(self):
        manifest.create_run(self.ws, "proj", "run-narr", "rev1", "videos/proj",
                            narration_enabled=True, created_at=TS)
        self.write(self.proj, "narration.txt", b"VOICE")
        manifest.record_attempt(self.ws, "proj", "run-narr", "att-narr", "narration", "external",
                                "succeeded", output_artifact_ids=["n-1"], created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-narr", "n-1", "narration", "project",
                                   "narration.txt", producer_attempt_id="att-narr", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-narr", "att-comp", "composition", "external",
                                "succeeded", input_artifact_ids=["n-1"],
                                output_artifact_ids=["c-1"], created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-narr", "c-1", "composition", "project",
                                   "index.html", producer_attempt_id="att-comp", created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-narr")
        manifest.validate_run_manifest(run, narration_enabled=True, workspace=self.ws)

    def test_missing_narration_input_fails_when_enabled(self):
        manifest.create_run(self.ws, "proj", "run-narr", "rev1", "videos/proj",
                            narration_enabled=True, created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-narr", "att-comp", "composition", "external",
                                "succeeded", output_artifact_ids=["c-1"], created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-narr", "c-1", "composition", "project",
                                   "index.html", producer_attempt_id="att-comp", created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-narr")
        with self.assertRaises(c.ContractError):
            manifest.validate_run_manifest(run, narration_enabled=True)
        manifest.validate_run_manifest(run, narration_enabled=False)

    def test_required_render_input_missing_fails(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-render", "render", "external",
                                "succeeded", output_artifact_ids=["render-1"], created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-1", "render-1", "render", "project",
                                   "renders/video.mp4", producer_attempt_id="att-render",
                                   created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        with self.assertRaises(c.ContractError):
            manifest.validate_run_manifest(run)

    def test_failed_and_unknown_attempts_preserve_partial(self):
        manifest.create_run(self.ws, "proj", "run-partial", "rev1", "videos/proj", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-partial", "att-f", "render", "external",
                                "failed", error="renderer exited", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-partial", "att-u", "render", "external",
                                "unknown", created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-partial")
        manifest.validate_run_manifest(run)

    def test_succeeded_attempt_requires_outputs(self):
        self.build_valid_run()
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        run = manifest.load_run(self.ws, "proj", "run-1")
        del run["attempts"]["att-comp"]["output_artifact_ids"]
        with self.assertRaises(c.MalformedRecordError):
            manifest.validate_run_structure(run)
        self.assertTrue(os.path.exists(path))


class TestImmutabilityAndPersistence(ManifestBase):
    def test_mutate_cannot_edit_terminal_attempt(self):
        self.build_valid_run()
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        with open(path, "rb") as fh:
            before = fh.read()

        def edit(run):
            run["attempts"]["att-comp"]["origin"] = "human"
            return run

        with self.assertRaises(c.ImmutabilityError):
            manifest.mutate_run(self.ws, "proj", "run-1", edit)
        with open(path, "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_mutate_cannot_delete_terminal_attempt(self):
        self.build_valid_run()

        def remove(run):
            del run["attempts"]["att-comp"]
            return run

        with self.assertRaises(c.ImmutabilityError):
            manifest.mutate_run(self.ws, "proj", "run-1", remove)
        self.assertIn("att-comp", manifest.load_run(self.ws, "proj", "run-1")["attempts"])

    def test_superseding_attempt_appends_and_original_unchanged(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "render", "external",
                                "unknown", created_at=TS)
        before = manifest.load_run(self.ws, "proj", "run-1")["attempts"]["att-1"]
        manifest.record_attempt(self.ws, "proj", "run-1", "att-2", "render", "external",
                                "failed", supersedes="att-1", created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        self.assertEqual({"att-1", "att-2"}, set(run["attempts"]))
        self.assertEqual("att-1", run["attempts"]["att-2"]["supersedes"])
        self.assertEqual(before, run["attempts"]["att-1"])

    def test_atomic_write_failure_leaves_previous_record(self):
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        with open(path, "rb") as fh:
            before = fh.read()
        with mock.patch.object(manifest.os, "replace", side_effect=OSError("simulated")):
            with self.assertRaises(OSError):
                manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "render", "external",
                                        "unknown", created_at=TS)
        with open(path, "rb") as fh:
            self.assertEqual(before, fh.read())
        leftovers = [n for n in os.listdir(os.path.dirname(path)) if n.startswith(".tmp-")]
        self.assertEqual([], leftovers)

    def test_concurrent_writer_and_stale_lock(self):
        lock = manifest.run_lock_path(self.ws, "proj", "run-1")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        with open(lock, "w", encoding="utf-8") as fh:
            fh.write("held-by-other")
        with self.assertRaises(c.ConcurrentWriterError):
            manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "render", "external",
                                    "unknown", created_at=TS)
        with open(lock, "r", encoding="utf-8") as fh:
            self.assertEqual("held-by-other", fh.read())

    def test_read_only_inspection(self):
        self.build_valid_run()
        before = dir_hash(os.path.join(self.ws, "runs"))
        manifest.inspect_run(self.ws, "proj", "run-1")
        manifest.validate_run_manifest(manifest.load_run(self.ws, "proj", "run-1"))
        manifest.list_runs(self.ws)
        self.assertEqual(before, dir_hash(os.path.join(self.ws, "runs")))


class TestLockIdentity(ManifestBase):
    def test_structured_lock_identity_is_collision_free(self):
        first = manifest.run_lock_path(self.ws, "a__b", "c")
        second = manifest.run_lock_path(self.ws, "a", "b__c")
        self.assertNotEqual(first, second)

    def test_same_identity_rejects_second_writer(self):
        lock = manifest.FileLock(manifest.run_lock_path(self.ws, "proj", "run-1"))
        lock.acquire()
        try:
            with self.assertRaises(c.ConcurrentWriterError):
                manifest.FileLock(manifest.run_lock_path(self.ws, "proj", "run-1")).acquire()
        finally:
            lock.release()


class TestArtifactsAndProvenance(ManifestBase):
    def test_explicit_artifact_selection(self):
        self.build_valid_run()
        self.write(self.proj, "renders/other.mp4", b"CCCC")
        manifest.register_artifact(self.ws, "proj", "run-1", "other-render", "render", "project",
                                   "renders/other.mp4", legacy_external=True, created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        self.assertIn("other-render", run["artifacts"])
        self.assertEqual("renders/video.mp4", run["artifacts"]["render-1"]["path"])

    def test_missing_and_changed_artifact_detected(self):
        self.build_valid_run()
        os.unlink(os.path.join(self.proj, "renders", "video.mp4"))
        report = manifest.inspect_run(self.ws, "proj", "run-1")
        states = {a["artifact_id"]: a["state"] for a in report["artifacts"]}
        self.assertEqual("missing", states["render-1"])
        self.write(self.proj, "renders/video.mp4", b"ZZZZ")
        report = manifest.inspect_run(self.ws, "proj", "run-1")
        states = {a["artifact_id"]: a["state"] for a in report["artifacts"]}
        self.assertEqual("changed", states["render-1"])

    def test_legacy_reference_is_external_and_unmodified(self):
        legacy = os.path.join(self.ws, "runs", "2026-01-01-legacy.json")
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        with open(legacy, "w", encoding="utf-8") as fh:
            fh.write('{"run_id": "old"}')
        with open(legacy, "rb") as fh:
            before = fh.read()
        manifest.historical_reference(self.ws, "proj", "run-1", "legacy-1", "workspace",
                                      "runs/2026-01-01-legacy.json", note="imported", created_at=TS)
        with open(legacy, "rb") as fh:
            self.assertEqual(before, fh.read())
        run = manifest.load_run(self.ws, "proj", "run-1")
        self.assertTrue(run["artifacts"]["legacy-1"]["legacy_external"])
        self.assertIsNone(run["artifacts"]["legacy-1"]["producer_attempt_id"])

    def test_unknown_accounting_stays_null(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "render", "external",
                                "unknown", created_at=TS)
        att = manifest.load_run(self.ws, "proj", "run-1")["attempts"]["att-1"]
        self.assertIsNone(att["usage"])

    def test_accounting_round_trip_and_credentials(self):
        usage = {"input_units": 10, "billed_cost": 0.0, "cost_provenance": "invoice-1"}
        manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "render", "external",
                                "unknown", usage=usage, created_at=TS)
        att = manifest.load_run(self.ws, "proj", "run-1")["attempts"]["att-1"]
        self.assertEqual(10, att["usage"]["input_units"])
        self.assertEqual(0.0, att["usage"]["billed_cost"])
        with self.assertRaises(c.ContractError):
            manifest.record_attempt(self.ws, "proj", "run-1", "att-2", "render", "external",
                                    "unknown", usage={"api_key": "SECRET"}, created_at=TS)

    def test_project_directory_is_byte_identical(self):
        before = dir_hash(self.proj) + dir_hash(self.rev2)
        self.build_valid_run()
        manifest.inspect_run(self.ws, "proj", "run-1")
        self.assertEqual(before, dir_hash(self.proj) + dir_hash(self.rev2))


class TestStartedResolution(ManifestBase):
    def test_started_attempt_resolved_by_new_attempt(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-start", "narration", "external",
                                "started", started_at=TS, created_at=TS)
        before = manifest.load_run(self.ws, "proj", "run-1")["attempts"]["att-start"]
        manifest.record_attempt(self.ws, "proj", "run-1", "att-done", "narration", "external",
                                "succeeded", output_artifact_ids=["n-1"], supersedes="att-start",
                                created_at=TS)
        self.write(self.proj, "narration.txt", b"VOICE")
        manifest.register_artifact(self.ws, "proj", "run-1", "n-1", "narration", "project",
                                   "narration.txt", producer_attempt_id="att-done", created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        self.assertEqual({"att-start", "att-done"}, set(run["attempts"]))
        self.assertEqual("att-start", run["attempts"]["att-done"]["supersedes"])
        self.assertEqual(before, run["attempts"]["att-start"])
        manifest.validate_run_manifest(run, workspace=self.ws)

    def test_started_attempt_cannot_be_directly_mutated(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-start", "narration", "external",
                                "started", created_at=TS)

        def edit(run):
            run["attempts"]["att-start"]["reported_execution_outcome"] = "succeeded"
            return run

        with self.assertRaises(c.ImmutabilityError):
            manifest.mutate_run(self.ws, "proj", "run-1", edit)


class TestRecorderStorageContainment(ManifestBase):
    def fresh_ws(self, name):
        ws = os.path.realpath(os.path.join(self.tmp, name))
        os.makedirs(os.path.join(ws, "videos", "proj"))
        with open(os.path.join(ws, "videos", "proj", "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html></html>")
        os.makedirs(os.path.join(ws, "runs"))
        return ws

    def test_projects_symlinked_to_videos_rejected(self):
        ws = self.fresh_ws("ws-projects")
        target = os.path.join(ws, "videos", "project")
        os.makedirs(target)
        os.symlink(target, os.path.join(ws, "runs", "projects"))
        with self.assertRaises(c.PathSafetyError):
            manifest.register_project(ws, "p", "videos/proj", created_at=TS)
        self.assertEqual([], os.listdir(target))

    def test_manifests_symlinked_to_videos_rejected(self):
        ws = self.fresh_ws("ws-manifests")
        manifest.register_project(ws, "p", "videos/proj", created_at=TS)
        target = os.path.join(ws, "videos", "project")
        os.makedirs(target)
        os.symlink(target, os.path.join(ws, "runs", "manifests"))
        with self.assertRaises(c.PathSafetyError):
            manifest.create_run(ws, "p", "r1", "rev1", "videos/proj", created_at=TS)
        self.assertEqual([], os.listdir(target))

    def test_locks_symlinked_to_videos_rejected(self):
        ws = self.fresh_ws("ws-locks")
        target = os.path.join(ws, "videos", "project")
        os.makedirs(target)
        os.symlink(target, os.path.join(ws, "runs", ".locks"))
        with self.assertRaises(c.PathSafetyError):
            manifest.register_project(ws, "p", "videos/proj", created_at=TS)
        self.assertEqual([], os.listdir(target))

    def test_alias_into_legacy_runs_area_rejected(self):
        ws = self.fresh_ws("ws-alias")
        legacy = os.path.join(ws, "runs", "2026-legacy.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            fh.write('{"run_id": "old"}')
        with open(legacy, "rb") as fh:
            before = fh.read()
        os.makedirs(os.path.join(ws, "runs", "projects"), exist_ok=True)
        os.symlink(legacy, os.path.join(ws, "runs", "projects", "proj.json"))
        with self.assertRaises(c.PathSafetyError):
            manifest.load_project(ws, "proj")
        with open(legacy, "rb") as fh:
            self.assertEqual(before, fh.read())


class TestRunContextImmutability(ManifestBase):
    def test_context_fields_are_immutable(self):
        self.build_valid_run()
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        with open(path, "rb") as fh:
            before = fh.read()
        cases = [
            ("revision_dir", "videos/proj-rev2"),
            ("revision", "rev2"),
            ("workflow_contract_version", "workflow-contract-9"),
            ("narration_enabled", True),
        ]
        for field, value in cases:
            def edit(run, field=field, value=value):
                run[field] = value
                return run
            with self.assertRaises(c.ImmutabilityError):
                manifest.mutate_run(self.ws, "proj", "run-1", edit)
            with open(path, "rb") as fh:
                self.assertEqual(before, fh.read())

    def test_ordinary_append_still_succeeds(self):
        self.build_valid_run()
        self.write(self.proj, "renders/other.mp4", b"CCCC")
        manifest.register_artifact(self.ws, "proj", "run-1", "other-render", "render", "project",
                                   "renders/other.mp4", legacy_external=True, created_at=TS)
        run = manifest.load_run(self.ws, "proj", "run-1")
        self.assertIn("other-render", run["artifacts"])
        manifest.validate_run_manifest(run, workspace=self.ws)


class TestStructuralEdgeCases(ManifestBase):
    def test_top_level_array_document_rejected(self):
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[]")
        with open(path, "rb") as fh:
            before = fh.read()
        with self.assertRaises(c.MalformedRecordError):
            manifest.load_run(self.ws, "proj", "run-1")
        with open(path, "rb") as fh:
            self.assertEqual(before, fh.read())
        ppath = manifest.project_path(self.ws, "proj")
        with open(ppath, "w", encoding="utf-8") as fh:
            fh.write("[]")
        with self.assertRaises(c.MalformedRecordError):
            manifest.load_project(self.ws, "proj")

    def test_malformed_historical_reference_rejected(self):
        self.build_valid_run()
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        run = manifest.load_run(self.ws, "proj", "run-1")
        run["historical_references"] = ["raw-string"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run, fh)
        with open(path, "rb") as fh:
            before = fh.read()
        with self.assertRaises(c.MalformedRecordError):
            manifest.load_run(self.ws, "proj", "run-1")
        with open(path, "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_reverse_producer_consistency(self):
        self.write(self.proj, "alt.html", b"<html>alt</html>")
        manifest.record_attempt(self.ws, "proj", "run-1", "att-comp", "composition", "external",
                                "succeeded", output_artifact_ids=["comp-1"], created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-1", "comp-1", "composition", "project",
                                   "index.html", producer_attempt_id="att-comp", created_at=TS)
        with self.assertRaises(c.ContractError):
            manifest.register_artifact(self.ws, "proj", "run-1", "comp-2", "composition",
                                       "project", "alt.html", producer_attempt_id="att-comp",
                                       created_at=TS)

    def test_self_supersession_rejected(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "narration", "external",
                                "failed", created_at=TS)
        with self.assertRaises(c.ContractError):
            manifest.record_attempt(self.ws, "proj", "run-1", "att-1", "narration", "external",
                                    "failed", supersedes="att-1", created_at=TS)

    def _two_node_cycle(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-b", "narration", "external",
                                "failed", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-1", "att-a", "narration", "external",
                                "failed", supersedes="att-b", created_at=TS)
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        run = manifest.load_run(self.ws, "proj", "run-1")
        run["attempts"]["att-b"]["supersedes"] = "att-a"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run, fh)
        return path

    def test_two_node_supersession_cycle_rejected(self):
        self._two_node_cycle()
        with self.assertRaises(c.ContractError):
            manifest.validate_run_manifest(manifest.load_run(self.ws, "proj", "run-1"))

    def test_longer_supersession_cycle_rejected(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-b", "narration", "external",
                                "failed", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-1", "att-a", "narration", "external",
                                "failed", supersedes="att-b", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-1", "att-c", "narration", "external",
                                "failed", supersedes="att-a", created_at=TS)
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        run = manifest.load_run(self.ws, "proj", "run-1")
        run["attempts"]["att-b"]["supersedes"] = "att-c"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run, fh)
        with self.assertRaises(c.ContractError):
            manifest.validate_run_manifest(manifest.load_run(self.ws, "proj", "run-1"))

    def test_valid_supersession_chain_passes(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-b", "narration", "external",
                                "failed", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-1", "att-a", "narration", "external",
                                "failed", supersedes="att-b", created_at=TS)
        manifest.record_attempt(self.ws, "proj", "run-1", "att-c", "narration", "external",
                                "failed", supersedes="att-a", created_at=TS)
        manifest.validate_run_manifest(manifest.load_run(self.ws, "proj", "run-1"))


class TestInspectionSemantics(ManifestBase):
    def test_producer_conflict_is_not_complete(self):
        self.build_valid_run()
        path = manifest.manifest_path(self.ws, "proj", "run-1")
        run = manifest.load_run(self.ws, "proj", "run-1")
        run["artifacts"]["render-1"]["producer_attempt_id"] = "att-comp"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run, fh)
        report = manifest.inspect_run(self.ws, "proj", "run-1")
        self.assertTrue(report["reference_resolution"])
        self.assertFalse(report["relationship_validity"])
        self.assertFalse(report["complete"])
        attempts = {a["attempt_id"]: a for a in report["attempts"]}
        self.assertFalse(attempts["att-render"]["complete"])

    def test_missing_render_input_fails_stage_contract(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-render", "render", "external",
                                "succeeded", output_artifact_ids=["render-1"], created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-1", "render-1", "render", "project",
                                   "renders/video.mp4", producer_attempt_id="att-render",
                                   created_at=TS)
        report = manifest.inspect_run(self.ws, "proj", "run-1")
        self.assertTrue(report["reference_resolution"])
        self.assertTrue(report["relationship_validity"])
        self.assertFalse(report["stage_contract_validity"])
        self.assertFalse(report["complete"])

    def test_inspection_stays_read_only(self):
        self.build_valid_run()
        before = dir_hash(os.path.join(self.ws, "runs"))
        manifest.inspect_run(self.ws, "proj", "run-1")
        self.assertEqual(before, dir_hash(os.path.join(self.ws, "runs")))


class TestRegistrationPreflight(ManifestBase):
    def fresh_ws(self, name):
        ws = os.path.realpath(os.path.join(self.tmp, name))
        os.makedirs(os.path.join(ws, "videos", "proj"))
        with open(os.path.join(ws, "videos", "proj", "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html></html>")
        os.makedirs(os.path.join(ws, "runs"))
        return ws

    def test_registry_root_symlink_rejected_before_any_lock(self):
        ws = self.fresh_ws("ws-order-projects")
        target = os.path.join(ws, "videos", "project")
        os.makedirs(target)
        os.symlink(target, os.path.join(ws, "runs", "projects"))
        with self.assertRaises(c.PathSafetyError):
            manifest.register_project(ws, "p", "videos/proj", created_at=TS)
        self.assertFalse(os.path.exists(os.path.join(ws, "runs", ".locks")))
        self.assertEqual([], os.listdir(target))
        self.assertEqual(["projects"], os.listdir(os.path.join(ws, "runs")))

    def test_target_record_symlink_rejected_before_any_lock(self):
        ws = self.fresh_ws("ws-order-record")
        os.makedirs(os.path.join(ws, "runs", "projects"), exist_ok=True)
        legacy = os.path.join(ws, "runs", "2026-legacy.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            fh.write('{"run_id": "old"}')
        with open(legacy, "rb") as fh:
            before = fh.read()
        os.symlink(legacy, os.path.join(ws, "runs", "projects", "proj.json"))
        with self.assertRaises(c.PathSafetyError):
            manifest.register_project(ws, "proj", "videos/proj", created_at=TS)
        self.assertFalse(os.path.exists(os.path.join(ws, "runs", ".locks")))
        with open(legacy, "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_normal_registration_still_succeeds(self):
        ws = self.fresh_ws("ws-normal")
        doc = manifest.register_project(ws, "p", "videos/proj", created_at=TS)
        self.assertEqual("p", doc["project_id"])
        self.assertTrue(os.path.isfile(manifest.project_path(ws, "p")))
        self.assertFalse(os.path.exists(manifest.registry_lock_path(ws)))

    def test_registry_lock_still_rejects_second_writer(self):
        ws = self.fresh_ws("ws-concurrent")
        lock = manifest.registry_lock_path(ws)
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        with open(lock, "w", encoding="utf-8") as fh:
            fh.write("held-by-other")
        with self.assertRaises(c.ConcurrentWriterError):
            manifest.register_project(ws, "p", "videos/proj", created_at=TS)
        self.assertFalse(os.path.isfile(manifest.project_path(ws, "p")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
