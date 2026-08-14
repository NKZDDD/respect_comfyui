#!/usr/bin/env python3
"""Validate canonical asset IDs, registry records, files, and reference manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path


ALLOWED_STATUS = {
    "RESERVED",
    "CANDIDATE",
    "CANONICAL",
    "LOGICAL_ONLY",
    "DEFERRED",
    "DEPRECATED",
}
REFERENCEABLE_STATUS = {"CANONICAL"}
TARGET_STATUS = {"RESERVED", "CANONICAL"}
FILE_ROLES = {"PRIMARY", "DETAIL", "MASK", "SOURCE"}


class ValidationError(Exception):
    pass


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"JSON_READ_ERROR: {path}: {exc}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, code: str, message: str, errors: list[str]):
    if not condition:
        errors.append(f"{code}: {message}")


def validate_registry(registry_path: Path, check_files: bool = False):
    registry = load_json(registry_path)
    errors: list[str] = []

    project_id = registry.get("project_id", "")
    require(
        re.fullmatch(r"PRJ_[A-Z0-9]{3,16}", project_id) is not None,
        "PROJECT_ID_INVALID",
        f"expected PRJ_ plus 3-16 uppercase ASCII letters/digits, got {project_id!r}",
        errors,
    )
    require(bool(registry.get("registry_snapshot_id")), "SNAPSHOT_MISSING", "registry_snapshot_id is required", errors)
    assets = registry.get("assets")
    require(isinstance(assets, list), "ASSETS_INVALID", "assets must be a list", errors)
    if not isinstance(assets, list):
        raise ValidationError("\n".join(errors))

    revision_pattern = re.compile(rf"{re.escape(project_id)}__[A-Z][A-Z0-9_]*_R\d{{2,3}}$")
    family_pattern = re.compile(rf"{re.escape(project_id)}__[A-Z][A-Z0-9_]*$")
    by_id: dict[str, dict] = {}
    file_paths: dict[str, str] = {}
    filenames: dict[str, str] = {}

    for index, asset in enumerate(assets):
        prefix = f"assets[{index}]"
        require(isinstance(asset, dict), "ASSET_RECORD_INVALID", f"{prefix} must be an object", errors)
        if not isinstance(asset, dict):
            continue
        revision_id = asset.get("canonical_revision_id", "")
        family_id = asset.get("asset_family_id", "")
        status = asset.get("status", "")
        require(revision_pattern.fullmatch(revision_id) is not None, "ID_FORMAT_INVALID", f"{prefix} revision ID {revision_id!r}", errors)
        require(family_pattern.fullmatch(family_id) is not None, "FAMILY_ID_INVALID", f"{prefix} family ID {family_id!r}", errors)
        require(revision_id.startswith(family_id + "_R"), "ID_FAMILY_MISMATCH", f"{revision_id!r} is not a revision of {family_id!r}", errors)
        require(revision_id not in by_id, "ID_DUPLICATE", f"duplicate canonical_revision_id {revision_id!r}", errors)
        if revision_id:
            by_id[revision_id] = asset
        require(status in ALLOWED_STATUS, "STATUS_INVALID", f"{revision_id!r} has status {status!r}", errors)
        require(isinstance(asset.get("parent_ids", []), list), "PARENT_LIST_INVALID", f"{revision_id!r} parent_ids must be a list", errors)

        files = asset.get("files", [])
        require(isinstance(files, list), "FILES_INVALID", f"{revision_id!r} files must be a list", errors)
        if not isinstance(files, list):
            continue
        if status == "CANONICAL":
            require(bool(files), "CANONICAL_FILE_MISSING", f"{revision_id!r} has no registered file", errors)
            require(any(item.get("role") == "PRIMARY" for item in files if isinstance(item, dict)), "PRIMARY_FILE_MISSING", f"{revision_id!r} has no PRIMARY file", errors)
        if status == "LOGICAL_ONLY":
            require(not files, "LOGICAL_ONLY_HAS_FILE", f"{revision_id!r} must not occupy an image file", errors)

        for file_index, item in enumerate(files):
            file_prefix = f"{prefix}.files[{file_index}]"
            require(isinstance(item, dict), "FILE_RECORD_INVALID", f"{file_prefix} must be an object", errors)
            if not isinstance(item, dict):
                continue
            role = item.get("role", "")
            filename = item.get("canonical_filename", "")
            relative = item.get("relative_path", "")
            require(role in FILE_ROLES, "FILE_ROLE_INVALID", f"{file_prefix} role {role!r}", errors)
            require(filename.startswith(revision_id + "__"), "FILE_ID_MISMATCH", f"{filename!r} must start with {revision_id!r} + '__'", errors)
            require(Path(relative).name == filename, "FILE_PATH_NAME_MISMATCH", f"{relative!r} does not end with {filename!r}", errors)
            require(relative not in file_paths, "FILE_PATH_DUPLICATE", f"{relative!r} used by {file_paths.get(relative)!r} and {revision_id!r}", errors)
            require(filename not in filenames, "FILENAME_DUPLICATE", f"{filename!r} used by {filenames.get(filename)!r} and {revision_id!r}", errors)
            if relative:
                file_paths[relative] = revision_id
            if filename:
                filenames[filename] = revision_id
            if check_files and relative:
                resolved = (registry_path.parent / relative).resolve()
                require(resolved.exists(), "FILE_NOT_FOUND", f"{relative!r} for {revision_id!r}", errors)
                expected_hash = item.get("sha256", "")
                if resolved.exists() and expected_hash:
                    require(sha256(resolved).lower() == expected_hash.lower(), "HASH_MISMATCH", f"{relative!r} for {revision_id!r}", errors)

    for revision_id, asset in by_id.items():
        for parent_id in asset.get("parent_ids", []):
            require(parent_id in by_id, "DANGLING_PARENT", f"{revision_id!r} parent {parent_id!r} not found", errors)
            if parent_id in by_id:
                require(by_id[parent_id].get("status") in REFERENCEABLE_STATUS, "PARENT_NOT_CANONICAL", f"{revision_id!r} parent {parent_id!r} is not CANONICAL", errors)
        replacement_id = asset.get("replacement_id_or_none")
        if replacement_id:
            require(replacement_id in by_id, "DANGLING_REPLACEMENT", f"{revision_id!r} replacement {replacement_id!r} not found", errors)
            require(replacement_id != revision_id, "SELF_REPLACEMENT", f"{revision_id!r} replaces itself", errors)

    redirects = registry.get("redirects", [])
    require(isinstance(redirects, list), "REDIRECTS_INVALID", "redirects must be a list", errors)
    old_ids: set[str] = set()
    if isinstance(redirects, list):
        for index, redirect in enumerate(redirects):
            old_id = redirect.get("old_exact_id", "") if isinstance(redirect, dict) else ""
            new_id = redirect.get("new_canonical_revision_id", "") if isinstance(redirect, dict) else ""
            require(bool(old_id), "REDIRECT_OLD_ID_MISSING", f"redirects[{index}]", errors)
            require(old_id not in old_ids, "REDIRECT_DUPLICATE", f"duplicate old ID {old_id!r}", errors)
            require(new_id in by_id, "REDIRECT_TARGET_MISSING", f"{old_id!r} -> {new_id!r}", errors)
            old_ids.add(old_id)

    if errors:
        raise ValidationError("\n".join(errors))
    return registry, by_id


def validate_manifest(manifest_path: Path, registry: dict, by_id: dict):
    manifest = load_json(manifest_path)
    errors: list[str] = []
    require(manifest.get("project_id") == registry.get("project_id"), "MANIFEST_PROJECT_MISMATCH", str(manifest_path), errors)
    require(manifest.get("registry_snapshot_id") == registry.get("registry_snapshot_id"), "MANIFEST_SNAPSHOT_MISMATCH", str(manifest_path), errors)

    target_id = manifest.get("production_target_id", "")
    require(target_id in by_id, "TARGET_ID_NOT_FOUND", target_id, errors)
    if target_id in by_id:
        require(by_id[target_id].get("status") in TARGET_STATUS, "TARGET_STATUS_INVALID", f"{target_id!r} is {by_id[target_id].get('status')!r}", errors)

    references = manifest.get("references", [])
    require(isinstance(references, list), "REFERENCES_INVALID", "references must be a list", errors)
    image_slots: set[str] = set()
    if isinstance(references, list):
        for index, reference in enumerate(references):
            prefix = f"references[{index}]"
            if not isinstance(reference, dict):
                errors.append(f"REFERENCE_RECORD_INVALID: {prefix}")
                continue
            image = reference.get("image", "")
            reference_id = reference.get("reference_id", "")
            filename = reference.get("canonical_filename", "")
            relative = reference.get("relative_path", "")
            require(re.fullmatch(r"Image [1-9]\d*", image) is not None, "IMAGE_SLOT_INVALID", f"{prefix} {image!r}", errors)
            require(image not in image_slots, "IMAGE_SLOT_DUPLICATE", image, errors)
            image_slots.add(image)
            require(reference_id in by_id, "REFERENCE_ID_NOT_FOUND", reference_id, errors)
            if reference_id in by_id:
                asset = by_id[reference_id]
                require(asset.get("status") in REFERENCEABLE_STATUS, "STATUS_NOT_CANONICAL", f"{reference_id!r} is {asset.get('status')!r}", errors)
                registered = {(item.get("canonical_filename"), item.get("relative_path")) for item in asset.get("files", []) if isinstance(item, dict)}
                require((filename, relative) in registered, "REFERENCE_FILE_MISMATCH", f"{reference_id!r}: {(filename, relative)!r}", errors)

    if errors:
        raise ValidationError("\n".join(errors))


def run_self_test():
    project = "PRJ_TEST01"
    parent = f"{project}__CHAR_001_R01"
    target = f"{project}__CHAR_001_PH01_R01"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        asset_dir = root / "assets"
        asset_dir.mkdir()
        parent_file = asset_dir / f"{parent}__PRIMARY.png"
        parent_file.write_bytes(b"canonical-test")
        registry = {
            "schema_version": "1.0",
            "project_id": project,
            "registry_snapshot_id": "REGSNAP_0001",
            "id_policy": "FQID_CANONICAL_REVISION_REQUIRED",
            "assets": [
                {
                    "canonical_revision_id": parent,
                    "asset_family_id": f"{project}__CHAR_001",
                    "asset_type": "CHAR",
                    "display_name": "Test Character",
                    "status": "CANONICAL",
                    "parent_ids": [],
                    "files": [{"role": "PRIMARY", "canonical_filename": parent_file.name, "relative_path": f"assets/{parent_file.name}", "sha256": sha256(parent_file)}],
                },
                {
                    "canonical_revision_id": target,
                    "asset_family_id": f"{project}__CHAR_001_PH01",
                    "asset_type": "PH",
                    "display_name": "Test Phase",
                    "status": "RESERVED",
                    "parent_ids": [parent],
                    "files": [],
                },
            ],
            "redirects": [],
            "counter_ledger": {},
        }
        registry_path = root / "asset_registry.json"
        registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        manifest = {
            "project_id": project,
            "registry_snapshot_id": "REGSNAP_0001",
            "production_target_id": target,
            "references": [{"image": "Image 1", "reference_id": parent, "canonical_filename": parent_file.name, "relative_path": f"assets/{parent_file.name}"}],
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        loaded, by_id = validate_registry(registry_path, check_files=True)
        validate_manifest(manifest_path, loaded, by_id)

        broken = dict(manifest)
        broken["references"] = [dict(manifest["references"][0], reference_id="CHAR_001")]
        broken_path = root / "broken.json"
        broken_path.write_text(json.dumps(broken, indent=2), encoding="utf-8")
        try:
            validate_manifest(broken_path, loaded, by_id)
        except ValidationError as exc:
            if "REFERENCE_ID_NOT_FOUND" not in str(exc):
                raise
        else:
            raise ValidationError("SELF_TEST_FAILED: abbreviated ID was accepted")

        duplicate_registry = json.loads(json.dumps(registry))
        duplicate_registry["assets"].append(dict(duplicate_registry["assets"][0]))
        duplicate_path = root / "duplicate_registry.json"
        duplicate_path.write_text(json.dumps(duplicate_registry, indent=2), encoding="utf-8")
        try:
            validate_registry(duplicate_path)
        except ValidationError as exc:
            if "ID_DUPLICATE" not in str(exc):
                raise
        else:
            raise ValidationError("SELF_TEST_FAILED: duplicate ID was accepted")

        parent_file.write_bytes(b"tampered-canonical-test")
        try:
            validate_registry(registry_path, check_files=True)
        except ValidationError as exc:
            if "HASH_MISMATCH" not in str(exc):
                raise
        else:
            raise ValidationError("SELF_TEST_FAILED: fingerprint mismatch was accepted")
    print("SELF_TEST_PASS: valid registry accepted; abbreviated ID, duplicate ID, and fingerprint mismatch rejected")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", nargs="?", type=Path, help="Path to asset_registry.json")
    parser.add_argument("--manifest", action="append", default=[], type=Path, help="Reference manifest JSON to validate; repeatable")
    parser.add_argument("--check-files", action="store_true", help="Verify relative files and optional SHA-256 values")
    parser.add_argument("--self-test", action="store_true", help="Run deterministic built-in success/failure tests")
    args = parser.parse_args()

    try:
        if args.self_test:
            run_self_test()
            return
        if not args.registry:
            parser.error("registry is required unless --self-test is used")
        registry, by_id = validate_registry(args.registry, check_files=args.check_files)
        for manifest_path in args.manifest:
            validate_manifest(manifest_path, registry, by_id)
        print(f"PASS: registry={args.registry} assets={len(by_id)} manifests={len(args.manifest)}")
    except ValidationError as exc:
        print(f"FAIL:\n{exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
