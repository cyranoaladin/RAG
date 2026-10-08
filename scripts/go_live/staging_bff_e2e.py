#!/usr/bin/env python3
"""Épreuve HTTP réelle du BFF Cockpit, bornée par son scope signé pilote.

Lecture seule côté staging : aucune écriture DB, aucun repli mock, aucun secret
dans la preuve. Le mode ``public`` ne passe qu'après publication gouvernée.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SCOPE_ID = "libre_terminale_maths_nsi_real_v1"
NSI_COLLECTION = "rag_nexus_nsi_terminale_specialite"
OUT_OF_SCOPE_COLLECTION = "rag_nexus_svt_terminale_specialite"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ENV = (
    "NEXTAUTH_SECRET",
    "NEXUS_INTERNAL_TOKEN_SECRET",
    "NEXUS_INTERNAL_TOKEN_ISSUER",
    "NEXUS_INTERNAL_TOKEN_AUDIENCE",
    "NEXUS_SSO_ISSUER",
    "NEXUS_SSO_AUDIENCE",
)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} invalide")
    return value


def assess_positive(
    status: int,
    payload: Any,
    collection: str,
    allowed_contents: set[str],
) -> dict[str, Any]:
    """Exiger un vrai passage cité, revu et lié au registre de release."""
    if status != 200:
        raise ValueError(f"positive HTTP {status}")
    results = _object(payload, "response").get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("positive results empty")
    contents: set[str] = set()
    for result in results:
        hit = _object(result, "result")
        metadata = _object(hit.get("metadata"), "metadata")
        if metadata.get("collection") != collection:
            raise ValueError("collection hors scope")
        if metadata.get("review_status") != "reviewed":
            raise ValueError("review status invalide")
        content = metadata.get("content_sha256")
        if not isinstance(content, str) or not SHA256.fullmatch(content):
            raise ValueError("content identity manquante")
        if content not in allowed_contents:
            raise ValueError("content absent de la release scellée")
        if hit.get("doc_id") != content or metadata.get("artifact_id") != content:
            raise ValueError("content identity incohérente")
        citation = _object(hit.get("citation"), "citation")
        if not all(
            isinstance(citation.get(field), str) and citation[field].strip()
            for field in ("source_uri", "source_label", "rights")
        ):
            raise ValueError("citation incomplète")
        page = citation.get("page")
        if page is not None and (not isinstance(page, int) or isinstance(page, bool) or page < 1):
            raise ValueError("citation page invalide")
        contents.add(content)
    return {
        "results": len(results),
        "citations": len(results),
        "content_sha256": sorted(contents),
    }


def assess_internal_student(status: int, payload: Any) -> str:
    """La visibilité internal ne doit jamais donner un passage à student."""
    body = _object(payload, "student response")
    if status == 503 and body.get("error") == "launch_not_ready":
        return "launch_not_ready"
    if status == 200 and body.get("results") == []:
        return "empty"
    raise ValueError("student a obtenu un résultat ou un refus non diagnostique")


def assess_cross_scope(status: int, payload: Any) -> bool:
    if status != 403 or _object(payload, "scope response").get("error") != "forbidden_collection":
        raise ValueError("scope hors collection non refusé par le BFF")
    return True


def assess_signed_claims(
    claims: dict[str, Any], role: str, allowed_collections: list[str]
) -> None:
    if claims.get("role") != role:
        raise ValueError("role signé inattendu")
    if claims.get("scope_id") != SCOPE_ID or claims.get("allowed_collections") != allowed_collections:
        raise ValueError("scope signé inattendu")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_release_contents(registry_path: Path, expected_digest: str, collection: str) -> set[str]:
    if not SHA256.fullmatch(expected_digest) or _sha256(registry_path) != expected_digest:
        raise ValueError("release registry digest invalide")
    registry = _object(json.loads(registry_path.read_text(encoding="utf-8")), "registry")
    contents: set[str] = set()
    for release in registry.get("releases", []):
        if collection not in release.get("collections", []):
            continue
        manifest_path = registry_path.parent / release["manifest_path"]
        if _sha256(manifest_path) != release["expected_manifest_sha256"]:
            raise ValueError("release manifest digest invalide")
        manifest = _object(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
        artifact_ref = _object(manifest.get("artifact_registry"), "artifact registry ref")
        artifact_path = manifest_path.parent / artifact_ref["path"]
        if _sha256(artifact_path) != artifact_ref["sha256"]:
            raise ValueError("artifact registry digest invalide")
        artifacts = _object(json.loads(artifact_path.read_text(encoding="utf-8")), "artifacts")
        artifact_ids = {artifact["content_sha256"] for artifact in artifacts["artifacts"]}
        subject_refs = [
            subject for subject in manifest["subjects"] if subject["collection"] == collection
        ]
        if len(subject_refs) != 1:
            raise ValueError("subject de collection absent ou ambigu")
        subject_ref = subject_refs[0]
        subject_path = manifest_path.parent / subject_ref["path"]
        if _sha256(subject_path) != subject_ref["sha256"]:
            raise ValueError("subject release digest invalide")
        subject = _object(json.loads(subject_path.read_text(encoding="utf-8")), "subject")
        if subject.get("collection") != collection:
            raise ValueError("subject collection incohérente")
        scoped_ids = {placement["artifact_id"] for placement in subject["placements"]}
        if not scoped_ids <= artifact_ids:
            raise ValueError("subject hors registre artefact")
        contents.update(scoped_ids)
    if not contents:
        raise ValueError("collection absente des releases scellées")
    return contents


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _mint_session(root: Path, role: str) -> tuple[str, dict[str, Any]]:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise ValueError("configuration d'identité absente: " + ", ".join(missing))
    params = {
        "nextauth_secret": os.environ["NEXTAUTH_SECRET"],
        "internal_token_secret": os.environ["NEXUS_INTERNAL_TOKEN_SECRET"],
        "internal_token_issuer": os.environ["NEXUS_INTERNAL_TOKEN_ISSUER"],
        "internal_token_audience": os.environ["NEXUS_INTERNAL_TOKEN_AUDIENCE"],
        "sso_issuer": os.environ["NEXUS_SSO_ISSUER"],
        "sso_audience": os.environ["NEXUS_SSO_AUDIENCE"],
        "matieres": ["nsi"],
        "role": role,
    }
    completed = subprocess.run(
        ["node", str(root / "services/cockpit/scripts/mint-session-token.mjs")],
        input=json.dumps(params),
        text=True,
        capture_output=True,
        check=True,
        cwd=root / "services/cockpit",
    )
    minted = _object(json.loads(completed.stdout), "minted session")
    internal = minted["internal_access_token"]
    payload = internal.split(".")[1]
    claims = _object(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))), "claims")
    assess_signed_claims(
        {**claims, "role": _object(claims.get("identity"), "identity").get("role")},
        role,
        [subject["collection"] for subject in json.loads(
            (root / "services/cockpit/src/generated/pilot-retrieval-scope-v1.json").read_text(
                encoding="utf-8"
            )
        )["subjects"]],
    )
    return minted["session_token"], claims


def _post_search(url: str, session: str | None, query: str, collection: str) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if session is not None:
        cookie_name = "__Secure-next-auth.session-token" if url.startswith("https://") else "next-auth.session-token"
        headers["Cookie"] = f"{cookie_name}={session}"
    request = Request(
        url.rstrip("/") + "/api/search",
        data=json.dumps({"query": query, "collections": [collection], "k": 8}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        finally:
            exc.close()


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.repository_root.resolve()
    head = _git(root, "rev-parse", "HEAD")
    if head != args.expected_sha or _git(root, "rev-parse", "origin/main") != head:
        raise ValueError("checkout différent du main final attendu")
    if _git(root, "status", "--porcelain"):
        raise ValueError("checkout de qualification non propre")
    scope_path = root / "services/cockpit/src/generated/pilot-retrieval-scope-v1.json"
    scope = _object(json.loads(scope_path.read_text(encoding="utf-8")), "pilot scope")
    if scope.get("scope_id") != SCOPE_ID or args.collection not in [
        subject["collection"] for subject in scope["subjects"]
    ]:
        raise ValueError("collection absente du scope BFF signé")
    contents = load_release_contents(args.registry, args.registry_sha256, args.collection)
    teacher_session, _ = _mint_session(root, "teacher")
    student_session, _ = _mint_session(root, "student")
    unauth_status, unauth_body = _post_search(args.cockpit_url, None, args.query, args.collection)
    if unauth_status != 401 or _object(unauth_body, "unauth").get("error") != "unauthorized":
        raise ValueError("BFF sans session non refusé")
    cross_status, cross_body = _post_search(
        args.cockpit_url, teacher_session, args.query, OUT_OF_SCOPE_COLLECTION
    )
    assess_cross_scope(cross_status, cross_body)
    teacher_status, teacher_body = _post_search(
        args.cockpit_url, teacher_session, args.query, args.collection
    )
    teacher = assess_positive(teacher_status, teacher_body, args.collection, contents)
    student_status, student_body = _post_search(
        args.cockpit_url, student_session, args.query, args.collection
    )
    student: dict[str, Any]
    if args.student_mode == "public":
        student = assess_positive(student_status, student_body, args.collection, contents)
    else:
        student = {"refusal": assess_internal_student(student_status, student_body)}
    return {
        "kind": "NEXUS-FINAL-STAGING-BFF-E2E-V1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "checkout_sha": head,
        "checkout_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "release_registry_sha256": args.registry_sha256,
        "pilot_scope_sha256": _sha256(scope_path),
        "cockpit_url": args.cockpit_url,
        "collection": args.collection,
        "scope_id": SCOPE_ID,
        "population": "BFF signed pilot scope: one collection; final 11 need direct API qualification",
        "unauthenticated_status": unauth_status,
        "cross_scope_status": cross_status,
        "teacher_status": teacher_status,
        "teacher": teacher,
        "student_status": student_status,
        "student_mode": args.student_mode,
        "student": student,
        "verification_status": "VERIFIED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--cockpit-url", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--collection", default=NSI_COLLECTION)
    parser.add_argument("--query", default="Quel est le programme de spécialité NSI en terminale ?")
    parser.add_argument("--student-mode", choices=("internal", "public"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args)
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
        print("BFF_E2E_PASS=true")
        print(f"BFF_COLLECTION={args.collection}")
        print(f"STUDENT_MODE={args.student_mode}")
        return 0
    except (ValueError, TypeError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"BFF_E2E_PASS=false: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
