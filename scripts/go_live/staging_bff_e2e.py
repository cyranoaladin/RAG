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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

NSI_COLLECTION = "rag_nexus_nsi_terminale_specialite"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ENV = (
    "NEXTAUTH_SECRET",
    "NEXUS_INTERNAL_TOKEN_SECRET",
    "NEXUS_INTERNAL_TOKEN_ISSUER",
    "NEXUS_INTERNAL_TOKEN_AUDIENCE",
    "NEXUS_SSO_ISSUER",
    "NEXUS_SSO_AUDIENCE",
)


class RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def safe_cockpit_url(raw: str) -> str:
    """N'envoyer les sessions de qualification qu'au BFF local de staging."""
    try:
        parsed = urlsplit(raw)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname in {"127.0.0.1", "::1"}
            and parsed.port is not None
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Cockpit URL non locale ou non assainie")
    return raw.rstrip("/")


def assert_scope_registry_parity(scope_collections: set[str], registry_collections: set[str]) -> None:
    if scope_collections != registry_collections:
        raise ValueError("scope signé incompatible avec la release scellée")


def canonical_scope_digest(scope: dict[str, Any]) -> str:
    encoded = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_final_scopes(
    generated_path: Path, artifact_dir: Path, registry_collections: set[str]
) -> dict[str, dict[str, Any]]:
    """Lier la projection BFF aux onze artefacts gouvernés et au registre final."""
    generated = json.loads(generated_path.read_text(encoding="utf-8"))
    if not isinstance(generated, list):
        raise TypeError("index final BFF invalide")
    scopes: dict[str, dict[str, Any]] = {}
    scope_ids: set[str] = set()
    for raw in generated:
        scope = _object(raw, "scope final")
        scope_id = scope.get("scope_id")
        subject = _object(scope.get("evidence_subject"), "subject final")
        collection = subject.get("collection")
        target = scope.get("target_policy")
        if (
            not isinstance(scope_id, str)
            or not re.fullmatch(r"prod_[a-z0-9_]+_v[0-9]+", scope_id)
            or not isinstance(collection, str)
            or scope_id in scope_ids
            or collection in scopes
            or scope.get("artifact_version") != "3"
            or scope.get("status") != "eligible_for_promotion"
            or subject.get("visibility") != "public"
            or not isinstance(target, dict)
            or not isinstance(target.get("roles"), list)
            or "student" not in target["roles"]
        ):
            raise ValueError("index de scopes V3 publics ambigu ou invalide")
        canonical = artifact_dir / f"retrieval-scope-{scope_id.replace('_', '-')}.json"
        if not canonical.is_file() or json.loads(canonical.read_text(encoding="utf-8")) != scope:
            raise ValueError("scope final différent de l'artefact gouverné")
        scopes[collection] = scope
        scope_ids.add(scope_id)
    assert_scope_registry_parity(set(scopes), registry_collections)
    return scopes


def assess_runtime_identity(status: int, payload: Any, expected_sha: str) -> str:
    body = _object(payload, "Cockpit health")
    build_sha = body.get("build_sha")
    if status != 200 or body.get("status") != "ok" or build_sha != expected_sha:
        raise ValueError("Cockpit build SHA différent du main qualifié")
    return build_sha


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} invalide")
    return value


def assert_final_successor_release(manifest: dict[str, Any]) -> None:
    """Ne jamais qualifier le candidat préparatoire ou une rehearsal interne."""
    if (
        not isinstance(manifest.get("release_id"), str)
        or not manifest["release_id"].startswith("student-public-successor-")
        or manifest.get("release_mode") != "production"
        or manifest.get("promotion_status") != "PROMOTABLE"
        or manifest.get("activation_status") != "PRODUCTION_ACTIVATION_ALLOWED"
        or manifest.get("review_status") != "APPROVED"
    ):
        raise ValueError("release publique finale non établie")


def assert_scope_subject_binding(
    scope: dict[str, Any], collection: str, subject_shas: dict[str, str]
) -> None:
    """Lier le scope V3 aux octets du sujet servi, pas à un ancien candidat."""
    if (
        _object(scope.get("evidence_subject"), "subject du scope").get("collection") != collection
        or not SHA256.fullmatch(subject_shas.get(collection, ""))
        or scope.get("source_sha256") != subject_shas[collection]
    ):
        raise ValueError("scope V3 non lié au subject final")


def assess_positive(
    status: int,
    payload: Any,
    collection: str,
    allowed_contents: set[str],
    release_placements: dict[str, dict[str, Any]] | None = None,
    *,
    require_public: bool = False,
) -> dict[str, Any]:
    """Exiger un vrai passage cité, revu et lié au registre de release."""
    if status != 200:
        raise ValueError(f"positive HTTP {status}")
    results = _object(payload, "response").get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("positive results empty")
    contents: set[str] = set()
    citations: list[dict[str, Any]] = []
    for result in results:
        hit = _object(result, "result")
        metadata = _object(hit.get("metadata"), "metadata")
        if metadata.get("collection") != collection:
            raise ValueError("collection hors scope")
        if metadata.get("review_status") != "reviewed":
            raise ValueError("review status invalide")
        content = metadata.get("content_sha256")
        if content is None:
            content = hit.get("content_sha256")
        if not isinstance(content, str) or not SHA256.fullmatch(content):
            raise ValueError("content identity manquante")
        if hit.get("content_sha256") is not None and hit["content_sha256"] != content:
            raise ValueError("content identity incohérente")
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
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError("citation page invalide")
        if release_placements is not None:
            placement_id = metadata.get("placement_id")
            sealed = release_placements.get(placement_id) if isinstance(placement_id, str) else None
            if sealed is None or sealed["artifact_id"] != metadata.get("artifact_id") or sealed["content_sha256"] != content:
                raise ValueError("placement absent de la release scellée")
            if require_public and sealed["visibility"] != "public":
                raise ValueError("placement non public")
            if require_public:
                if sealed.get("media_type") != "text/plain; charset=utf-8":
                    raise ValueError("artefact public non textuel")
                sealed_citation = _object(sealed.get("citation"), "attribution scellée")
                fields = ("source_uri", "source_label", "licensor", "licence_id", "source_updated_at", "derivative_notice")
                if (
                    sealed_citation.get("licence_id") != "ETALAB-2.0"
                    or any(
                        not isinstance(citation.get(field), str)
                        or not citation[field].strip()
                        or citation[field] != sealed_citation.get(field)
                        for field in fields
                    )
                ):
                    raise ValueError("attribution du dérivé public absente ou non scellée")
            if sealed["source_uri"] != citation["source_uri"] or sealed["source_label"] != citation["source_label"]:
                raise ValueError("citation non liée à l'artefact scellé")
            pages = sealed["chunks"].get(hit.get("chunk_id"))
            if pages is None or not pages[0] <= page <= pages[1]:
                raise ValueError("citation page hors chunk scellé")
        elif require_public:
            raise ValueError("placement public non vérifié")
        citations.append({
            "chunk_id": hit.get("chunk_id"),
            "placement_id": metadata.get("placement_id"),
            "content_sha256": content,
            "source_uri": citation["source_uri"],
            "source_label": citation["source_label"],
            "rights": citation["rights"],
            "page": page,
        })
        contents.add(content)
    return {
        "results": len(results),
        "citation_count": len(citations),
        "citations": citations,
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
    claims: dict[str, Any], role: str, scope: dict[str, Any]
) -> None:
    if claims.get("role") != role:
        raise ValueError("role signé inattendu")
    if (
        claims.get("scope_id") != scope["scope_id"]
        or claims.get("scope_digest") != canonical_scope_digest(scope)
        or claims.get("allowed_collections") != [scope["evidence_subject"]["collection"]]
    ):
        raise ValueError("scope signé inattendu")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_release_evidence(
    registry_path: Path, expected_digest: str, collection: str
) -> dict[str, dict[str, Any]]:
    if not SHA256.fullmatch(expected_digest) or _sha256(registry_path) != expected_digest:
        raise ValueError("release registry digest invalide")
    registry = _object(json.loads(registry_path.read_text(encoding="utf-8")), "registry")
    placements: dict[str, dict[str, Any]] = {}
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
        artifact_index = {artifact["artifact_id"]: artifact for artifact in artifacts["artifacts"]}
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
        for placement in subject["placements"]:
            artifact = artifact_index.get(placement["artifact_id"])
            if artifact is None or placement["placement_id"] in placements:
                raise ValueError("placement hors registre ou dupliqué")
            placements[placement["placement_id"]] = {
                "artifact_id": artifact["artifact_id"],
                "content_sha256": artifact["content_sha256"],
                "visibility": placement["visibility"],
                "media_type": artifact.get("media_type"),
                "citation": artifact.get("citation"),
                "source_uri": artifact["source_url"],
                "source_label": artifact["title"],
                "chunks": {
                    chunk["chunk_id"]: (chunk["page_start"], chunk["page_end"])
                    for chunk in artifact["chunks"]
                },
            }
    if not placements:
        raise ValueError("collection absente des releases scellées")
    return placements


def load_release_contents(registry_path: Path, expected_digest: str, collection: str) -> set[str]:
    return {
        placement["content_sha256"]
        for placement in load_release_evidence(registry_path, expected_digest, collection).values()
    }


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _live_main_sha(root: Path) -> str:
    response = _git(root, "ls-remote", "origin", "refs/heads/main").split()
    if len(response) != 2 or not re.fullmatch(r"[0-9a-f]{40}", response[0]):
        raise ValueError("main distant indisponible")
    return response[0]


def identity_for_scope(scope: dict[str, Any], role: str) -> dict[str, Any]:
    target = _object(scope.get("target_policy"), "target policy")
    subject = _object(scope.get("evidence_subject"), "evidence subject")
    candidates = target.get("candidates")
    if not isinstance(candidates, list) or "libre" not in candidates:
        raise ValueError("candidat libre absent du scope final")
    roles = target.get("roles")
    if not isinstance(roles, list) or role not in roles:
        raise ValueError("role absent du scope final")
    audiences = target.get("audiences")
    if not isinstance(audiences, list) or "libre" not in audiences:
        raise ValueError("audience libre absente du scope final")
    return {
        "tenant": target["tenant"],
        "niveau": target["niveau"],
        "voie": target["voie"],
        "matieres": [target["matiere"]],
        "statut_enseignement": target["statut_enseignement"],
        "audience": "libre",
        "candidat": "libre",
        "school_year": subject["school_year"],
        "role": role,
    }


def _mint_session(root: Path, role: str, scope: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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
        **identity_for_scope(scope, role),
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
        scope,
    )
    return minted["session_token"], claims


def _post_search(url: str, session: str | None, query: str, collection: str) -> tuple[int, Any]:
    url = safe_cockpit_url(url)
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
        with build_opener(RefuseRedirects).open(request, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        try:
            if 300 <= exc.code < 400:
                raise ValueError("redirection Cockpit refusée")
            return exc.code, json.load(exc)
        finally:
            exc.close()


def _get_health(url: str) -> tuple[int, Any]:
    request = Request(safe_cockpit_url(url) + "/api/health", method="GET")
    try:
        with build_opener(RefuseRedirects).open(request, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        try:
            if 300 <= exc.code < 400:
                raise ValueError("redirection Cockpit refusée")
            return exc.code, json.load(exc)
        finally:
            exc.close()


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.repository_root.resolve()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{2,64}", args.operator_id):
        raise ValueError("identifiant opérateur invalide")
    cockpit_url = safe_cockpit_url(args.cockpit_url)
    head = _git(root, "rev-parse", "HEAD")
    live_main_sha = _live_main_sha(root)
    if head != args.expected_sha or _git(root, "rev-parse", "origin/main") != head or live_main_sha != head:
        raise ValueError("checkout différent du main final attendu")
    if _git(root, "status", "--porcelain"):
        raise ValueError("checkout de qualification non propre")
    scope_path = args.scope_index.resolve()
    if not scope_path.is_relative_to(root):
        raise ValueError("index de scopes hors checkout")
    if _sha256(args.registry) != args.registry_sha256:
        raise ValueError("release registry digest invalide")
    registry = _object(json.loads(args.registry.read_text(encoding="utf-8")), "registry")
    registry_collections = {
        collection for release in registry["releases"] for collection in release["collections"]
    }
    if len(registry_collections) != 11:
        raise ValueError("registre final BFF attendu à 11 collections")
    if len(registry["releases"]) != 1:
        raise ValueError("registre successeur public non unique")
    release = registry["releases"][0]
    manifest_path = args.registry.parent / release["manifest_path"]
    if _sha256(manifest_path) != release["expected_manifest_sha256"]:
        raise ValueError("release manifest digest invalide")
    manifest = _object(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    assert_final_successor_release(manifest)
    scopes = load_final_scopes(
        scope_path,
        root / "packages/contracts/src/nexus_contracts/artifacts",
        registry_collections,
    )
    subject_refs = manifest.get("subjects")
    if not isinstance(subject_refs, list) or len(subject_refs) != 11:
        raise ValueError("subjects de release finale incomplets")
    subject_shas = {
        ref["collection"]: ref["sha256"]
        for ref in subject_refs if isinstance(ref, dict) and isinstance(ref.get("collection"), str)
    }
    if set(subject_shas) != registry_collections:
        raise ValueError("subjects de release finale hors collection")
    for collection, final_scope in scopes.items():
        assert_scope_subject_binding(final_scope, collection, subject_shas)
    scope = scopes.get(args.collection)
    if scope is None:
        raise ValueError("collection absente du scope BFF signé")
    health_status, health_body = _get_health(cockpit_url)
    runtime_build_sha = assess_runtime_identity(health_status, health_body, head)
    release_placements = load_release_evidence(args.registry, args.registry_sha256, args.collection)
    contents = {placement["content_sha256"] for placement in release_placements.values()}
    student_session, _ = _mint_session(root, "student", scope)
    teacher_allowed = "teacher" in scope["target_policy"]["roles"]
    teacher_session: str | None = None
    if teacher_allowed:
        teacher_session, _ = _mint_session(root, "teacher", scope)
    unauth_status, unauth_body = _post_search(cockpit_url, None, args.query, args.collection)
    if unauth_status != 401 or _object(unauth_body, "unauth").get("error") != "unauthorized":
        raise ValueError("BFF sans session non refusé")
    cross_status, cross_body = _post_search(
        cockpit_url,
        teacher_session if teacher_allowed else student_session,
        args.query,
        next(collection for collection in sorted(registry_collections) if collection != args.collection),
    )
    assess_cross_scope(cross_status, cross_body)
    teacher_status: int | None = None
    teacher: dict[str, Any] = {"status": "NOT_RUN_SCOPE_ROLE_NOT_ISSUED"}
    if teacher_allowed:
        teacher_status, teacher_body = _post_search(
            cockpit_url, teacher_session, args.query, args.collection
        )
        teacher = assess_positive(
            teacher_status, teacher_body, args.collection, contents, release_placements
        )
    student_status, student_body = _post_search(
        cockpit_url, student_session, args.query, args.collection
    )
    student: dict[str, Any]
    if args.student_mode == "public":
        student = assess_positive(
            student_status, student_body, args.collection, contents, release_placements,
            require_public=True,
        )
    else:
        student = {"refusal": assess_internal_student(student_status, student_body)}
    return {
        "kind": "NEXUS-FINAL-STAGING-BFF-E2E-V1",
        "observed_at": datetime.now(UTC).isoformat(),
        "checkout_sha": head,
        "live_main_sha": live_main_sha,
        "cockpit_runtime_build_sha": runtime_build_sha,
        "checkout_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "release_registry_sha256": args.registry_sha256,
        "final_scope_index_sha256": _sha256(scope_path),
        "selected_scope_digest": canonical_scope_digest(scope),
        "cockpit_url": cockpit_url,
        "query": args.query,
        "decision_author": args.operator_id,
        "invocation": {
            "repository_root": ".",
            "cockpit_url": cockpit_url,
            "registry": str(args.registry.resolve().relative_to(root)),
            "registry_sha256": args.registry_sha256,
            "scope_index": str(scope_path.relative_to(root)),
            "expected_sha": args.expected_sha,
            "collection": args.collection,
            "query": args.query,
            "student_mode": args.student_mode,
        },
        "collection": args.collection,
        "scope_id": scope["scope_id"],
        "population": "BFF signed final scope: one of 11 collections; direct API acceptance covers all 11",
        "unauthenticated_status": unauth_status,
        "cross_scope_status": cross_status,
        "cross_scope_role": "teacher" if teacher_allowed else "student",
        "teacher_status": teacher_status,
        "teacher_e2e_verified": teacher_allowed,
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
    parser.add_argument("--scope-index", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--collection", default=NSI_COLLECTION)
    parser.add_argument("--query", default="Quel est le programme de spécialité NSI en terminale ?")
    parser.add_argument("--operator-id", required=True)
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
