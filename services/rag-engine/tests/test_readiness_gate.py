"""Gate de readiness au runtime — ce qu'il refuse (ADR-0036).

Aucun fichier gouverné réel n'est écrit : chaque test installe une racine
gouvernée temporaire isolée, avec des graines Ed25519 triviales et
déterministes. Rien ici ne ressemble à un secret utilisable.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts.production_readiness import (
    PRODUCTION_READINESS_PROTOCOL_VERSION,
    ProductionReadinessManifestV1,
    public_readiness_key_hex,
    sign_production_readiness_manifest,
)

from ingestor.ingestion_profiles import readiness_gate as gate_module
from ingestor.ingestion_profiles.readiness_gate import (
    GOVERNED_TRUST_ANCHOR_PATH,
    ReadinessGateError,
    enforce_readiness_gate,
)

SEED = "33" * 32
OTHER_SEED = "44" * 32
KEY_ID = "nexus-readiness-test-1"
MERGE_SHA = "a" * 40
TREE_SHA = "b" * 40


@pytest.fixture(autouse=True)
def _pin_legacy_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        gate_module.EXPECTED_PROTOCOL_ENV, "NEXUS-PRODUCTION-READINESS-V1"
    )


def _manifest(**overrides: object) -> ProductionReadinessManifestV1:
    fields: dict[str, object] = {
        "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
        "repository": "cyranoaladin/RAG",
        "pr_number": 95,
        "pr_head_sha": "c" * 40,
        "pr_head_tree_sha": TREE_SHA,
        "merge_sha": MERGE_SHA,
        "merge_tree_sha": TREE_SHA,
        "release_tag": f"release/rag/20260811-{MERGE_SHA[:12]}",
        "environment": "production",
        "review_binding_digest": "11" * 32,
        "authorization_digest": "22" * 32,
        "trust_anchor_digest": "33" * 32,
        "revocation_registry_digest": "44" * 32,
        "catalog_digest": "55" * 32,
        "sealed_manifest_digest": "66" * 32,
        "h2b_report_digest": "77" * 32,
        "gate_result": "pass",
        "application_image_digests": {
            "ingestion-worker": "ghcr.io/o/rag-ingestion-worker@sha256:" + "1" * 64
        },
        "upstream_image_digests": {"pgvector": "pgvector/pgvector@sha256:" + "3" * 64},
        "compose_digest": "88" * 32,
        "workflow_path": ".github/workflows/promote-rag-production.yml",
        "workflow_ref": "refs/heads/main",
        "run_id": 4242,
        "run_attempt": 1,
        "issued_at": datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        "key_id": KEY_ID,
    }
    fields.update(overrides)
    return ProductionReadinessManifestV1(**fields)  # type: ignore[arg-type]


def _anchor_bytes(*, seed: str = SEED, environment: str = "production") -> bytes:
    return json.dumps(
        {
            "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
            "keys": [
                {
                    "key_id": KEY_ID,
                    "algorithm": "ed25519",
                    "public_key": public_readiness_key_hex(seed),
                    "environment": environment,
                }
            ],
        }
    ).encode("utf-8")


def _write_manifest(tmp_path: Path, *, seed: str = SEED, **overrides: object) -> Path:
    path = tmp_path / "readiness-manifest.json"
    path.write_bytes(
        sign_production_readiness_manifest(
            _manifest(**overrides), private_key_hex=seed, key_id=KEY_ID
        ).canonical_bytes()
    )
    path.chmod(0o444)
    return path


def _install_governed_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    anchor: bytes | None = None,
) -> Path:
    """Racine gouvernée temporaire.

    ``_GOVERNED_REPOSITORY_ROOT`` est dérivée du code et n'est
    surchargeable par aucun moyen de production : la remplacer dans le
    module est hors d'atteinte d'un opérateur. Des tests dédiés vérifient
    séparément qu'aucun vrai vecteur de redirection n'existe."""
    root = tmp_path / "governed_root"
    for marker in gate_module._GOVERNED_ROOT_MARKERS:
        (root / marker).mkdir(parents=True, exist_ok=True)
    if anchor is not None:
        target = root / GOVERNED_TRUST_ANCHOR_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(anchor)
    monkeypatch.setattr(gate_module, "_GOVERNED_REPOSITORY_ROOT", root)
    return root


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        gate_module.MANIFEST_PATH_ENV,
        gate_module.RELEASE_SHA_ENV,
        gate_module.ENVIRONMENT_ENV,
        gate_module.REHEARSAL_TRUST_ANCHOR_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


class TestProductionIsFailClosed:
    def test_a_missing_manifest_path_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        monkeypatch.setenv(gate_module.RELEASE_SHA_ENV, MERGE_SHA)
        with pytest.raises(ReadinessGateError, match="is not configured"):
            enforce_readiness_gate()

    def test_a_missing_release_sha_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        monkeypatch.setenv(
            gate_module.MANIFEST_PATH_ENV, str(_write_manifest(tmp_path))
        )
        with pytest.raises(ReadinessGateError, match="NEXUS_RELEASE_SHA"):
            enforce_readiness_gate()

    def test_an_absent_manifest_file_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        with pytest.raises(ReadinessGateError, match="does not exist"):
            enforce_readiness_gate(
                manifest_path=tmp_path / "absent.json", release_sha=MERGE_SHA
            )

    def test_a_symlinked_manifest_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        real = _write_manifest(tmp_path)
        link = tmp_path / "link.json"
        link.symlink_to(real)
        with pytest.raises(ReadinessGateError, match="is a symlink"):
            enforce_readiness_gate(manifest_path=link, release_sha=MERGE_SHA)

    def test_a_directory_is_not_a_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        directory = tmp_path / "a-directory"
        directory.mkdir()
        with pytest.raises(ReadinessGateError, match="not a regular file"):
            enforce_readiness_gate(manifest_path=directory, release_sha=MERGE_SHA)

    def test_a_world_writable_manifest_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le risque couvert est la substitution par un processus non
        privilégié : un fichier que n'importe quoi peut réécrire ne prouve
        rien."""
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        path.chmod(0o666)
        with pytest.raises(ReadinessGateError, match="world-writable"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_a_group_writable_manifest_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
        with pytest.raises(ReadinessGateError, match="writable"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_malformed_json_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = tmp_path / "readiness-manifest.json"
        path.write_text("{ not json", encoding="utf-8")
        path.chmod(0o444)
        with pytest.raises(ReadinessGateError, match="not valid UTF-8 JSON"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_an_unknown_protocol_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["manifest"]["protocol_version"] = "NEXUS-PRODUCTION-READINESS-V9"
        path.chmod(0o644)
        path.write_text(
            json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        path.chmod(0o444)
        with pytest.raises(ReadinessGateError, match="protocol_version is not"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_a_signature_from_another_key_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path, seed=OTHER_SEED)
        with pytest.raises(ReadinessGateError, match="signature is invalid"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_an_absent_governed_anchor_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=None)
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="does not exist"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_a_symlinked_governed_anchor_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _install_governed_root(monkeypatch, tmp_path, anchor=None)
        real = tmp_path / "real-anchor.json"
        real.write_bytes(_anchor_bytes())
        target = root / GOVERNED_TRUST_ANCHOR_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(real)
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="is a symlink"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_a_root_without_repository_markers_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stray = tmp_path / "site-packages-ish"
        (stray / Path(GOVERNED_TRUST_ANCHOR_PATH).parent).mkdir(parents=True)
        (stray / GOVERNED_TRUST_ANCHOR_PATH).write_bytes(_anchor_bytes())
        monkeypatch.setattr(gate_module, "_GOVERNED_REPOSITORY_ROOT", stray)
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="does not look like"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_another_release_sha_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="but the release being"):
            enforce_readiness_gate(manifest_path=path, release_sha="e" * 40)

    def test_a_branch_name_is_never_a_release(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="mutable"):
            enforce_readiness_gate(manifest_path=path, release_sha="main")

    def test_a_test_environment_key_never_validates_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(
            monkeypatch, tmp_path, anchor=_anchor_bytes(environment="test")
        )
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="can never be accepted"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_an_invalid_environment_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="must be 'production'"):
            enforce_readiness_gate(
                manifest_path=path, release_sha=MERGE_SHA, environment="whatever"
            )


class TestTheValidPathIsReachable:
    def test_a_valid_manifest_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Garde-fou de sensibilité : les refus ci-dessus viennent de leur
        cause, pas d'un gate qui refuserait tout."""
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        result = enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)
        assert result.manifest.merge_sha == MERGE_SHA
        assert result.environment == "production"
        assert result.manifest.gate_result == "pass"

    def test_the_environment_variables_are_honoured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        monkeypatch.setenv(gate_module.MANIFEST_PATH_ENV, str(path))
        monkeypatch.setenv(gate_module.RELEASE_SHA_ENV, MERGE_SHA)
        assert enforce_readiness_gate().manifest.merge_sha == MERGE_SHA

    def test_production_is_the_default_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-closed : ne rien déclarer signifie production, jamais un
        mode permissif."""
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        assert os.environ.get(gate_module.ENVIRONMENT_ENV) is None
        assert (
            enforce_readiness_gate(
                manifest_path=path, release_sha=MERGE_SHA
            ).environment
            == "production"
        )


class TestRehearsalIsIsolated:
    def test_rehearsal_never_reads_the_governed_anchor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'isolation tient au fichier consulté : en répétition, l'ancre
        gouvernée n'est simplement jamais ouverte."""
        _install_governed_root(monkeypatch, tmp_path, anchor=None)
        rehearsal_anchor = tmp_path / "rehearsal-anchor.json"
        rehearsal_anchor.write_bytes(_anchor_bytes())
        monkeypatch.setenv(
            gate_module.REHEARSAL_TRUST_ANCHOR_ENV, str(rehearsal_anchor)
        )
        path = _write_manifest(tmp_path)
        result = enforce_readiness_gate(
            manifest_path=path, release_sha=MERGE_SHA, environment="rehearsal"
        )
        assert result.environment == "rehearsal"

    def test_a_rehearsal_anchor_is_never_consulted_in_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le pendant : une clé de répétition déclarée ailleurs n'a aucun
        moyen d'être lue en production."""
        _install_governed_root(monkeypatch, tmp_path, anchor=None)
        rehearsal_anchor = tmp_path / "rehearsal-anchor.json"
        rehearsal_anchor.write_bytes(_anchor_bytes())
        monkeypatch.setenv(
            gate_module.REHEARSAL_TRUST_ANCHOR_ENV, str(rehearsal_anchor)
        )
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="does not exist"):
            enforce_readiness_gate(manifest_path=path, release_sha=MERGE_SHA)

    def test_rehearsal_without_its_own_anchor_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
        path = _write_manifest(tmp_path)
        with pytest.raises(ReadinessGateError, match="never borrows the production"):
            enforce_readiness_gate(
                manifest_path=path, release_sha=MERGE_SHA, environment="rehearsal"
            )


# ---------------------------------------------------------------------------
# A3 — les deux ancres gouvernées ne désignent pas le même fichier.
#
# La séparation des clés était prouvée par type d'objet, par protocole
# d'ancre et par clé publique. Il manquait la propriété la plus simple et
# la plus facile à casser par accident : que les deux CHEMINS canoniques
# diffèrent. Une constante readiness pointant par erreur vers l'ancre de
# review binding ferait accepter, en production, une clé destinée à une
# tout autre autorité — sans qu'aucun test existant ne rougisse.
# ---------------------------------------------------------------------------

#: Verrou de gouvernance. Cette valeur appartient au gate H2-B de
#: ``rag-pedago`` (``_GOVERNED_TRUST_ANCHOR_PATH``) et est répétée ici
#: **délibérément** : ``rag-engine`` n'importe jamais ``rag-pedago``
#: (AGENTS.md, ADR-0001), et une dépendance interservice créée pour un
#: test serait un remède pire que le mal. Si l'un des deux chemins change,
#: ce test doit être relu — c'est précisément son rôle.
REVIEW_BINDING_ANCHOR_PATH = "governance/trust-anchors/review-binding-v1.json"


def _anchors_are_separated(readiness_path: str, review_path: str) -> bool:
    """Prédicat unique, partagé par l'assertion réelle et par la preuve de
    mutation — pour que la preuve porte sur ce qui est réellement asserté."""
    if readiness_path == review_path:
        return False
    if Path(readiness_path).name == Path(review_path).name:
        return False
    root = Path("/nexus-governed-root")
    return (root / readiness_path).resolve() != (root / review_path).resolve()


class TestGovernedAnchorPathsAreSeparate:
    def test_the_readiness_anchor_is_the_expected_governed_path(self) -> None:
        assert (
            GOVERNED_TRUST_ANCHOR_PATH
            == "governance/trust-anchors/production-readiness-v1.json"
        )

    def test_the_two_governed_anchors_are_distinct(self) -> None:
        assert GOVERNED_TRUST_ANCHOR_PATH != REVIEW_BINDING_ANCHOR_PATH
        assert (
            Path(GOVERNED_TRUST_ANCHOR_PATH).name
            != Path(REVIEW_BINDING_ANCHOR_PATH).name
        )
        assert _anchors_are_separated(
            GOVERNED_TRUST_ANCHOR_PATH, REVIEW_BINDING_ANCHOR_PATH
        )

    def test_the_two_anchors_never_resolve_to_the_same_file(
        self, tmp_path: Path
    ) -> None:
        """Résolution réelle sous une racine commune : deux chemins
        distincts qui se résoudraient au même inode (lien, ``..``) seraient
        aussi dangereux qu'un seul chemin."""
        root = tmp_path / "governed_root"
        for relative in (GOVERNED_TRUST_ANCHOR_PATH, REVIEW_BINDING_ANCHOR_PATH):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
        readiness = (root / GOVERNED_TRUST_ANCHOR_PATH).resolve()
        review = (root / REVIEW_BINDING_ANCHOR_PATH).resolve()
        assert readiness != review
        assert readiness.stat().st_ino != review.stat().st_ino

    def test_pointing_readiness_at_the_review_anchor_is_detected(self) -> None:
        """Preuve de mutation, locale et sans effet de bord : si la
        constante readiness désignait l'ancre de review binding, le
        prédicat asserté ci-dessus deviendrait faux."""
        assert not _anchors_are_separated(
            REVIEW_BINDING_ANCHOR_PATH, REVIEW_BINDING_ANCHOR_PATH
        )

    def test_a_same_named_file_in_another_directory_is_still_a_collision(
        self,
    ) -> None:
        """Garde-fou de sensibilité : le prédicat ne se contente pas de
        comparer les chaînes, il refuse aussi un nom de fichier identique
        déplacé ailleurs — cas typique d'une réorganisation hâtive."""
        assert not _anchors_are_separated(
            "governance/other/review-binding-v1.json", REVIEW_BINDING_ANCHOR_PATH
        )


class TestTheRealGovernedRootResolvesOnAnActualCheckout:
    """Tous les autres tests de ce fichier installent une racine gouvernée
    synthétique via ``_install_governed_root`` (monkeypatch de
    ``_GOVERNED_REPOSITORY_ROOT``) — aucun n'exerce jamais la dérivation
    RÉELLE depuis l'emplacement de ``readiness_gate.py`` sur le disque. LOT
    H2-B remédiation : cette dérivation était fausse de deux niveaux
    (``parents[3]`` au lieu de ``parents[5]``), ce qui rendait
    ``enforce_readiness_gate(environment="production")`` incapable de
    résoudre les marqueurs sur *tout* checkout réel, indépendamment de la
    présence de l'ancre — et donc production totalement inatteignable,
    jamais détecté faute d'un test contre le vrai disque."""

    def test_the_unmocked_root_is_the_actual_repository_root(self) -> None:
        assert gate_module._GOVERNED_REPOSITORY_ROOT == Path(__file__).resolve().parents[3]

    def test_the_unmocked_root_carries_both_governed_markers(self) -> None:
        root = gate_module._GOVERNED_REPOSITORY_ROOT
        for marker in gate_module._GOVERNED_ROOT_MARKERS:
            assert (root / marker).is_dir(), f"missing governed root marker: {marker}"

    def test_production_with_a_provisioned_anchor_fails_on_the_manifest_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sensitivity guard: against the real (unmocked) root, the governed
        production readiness anchor is now provisioned at
        ``governance/trust-anchors/production-readiness-v1.json`` (H2-B
        Phase D). This proves ``PRODUCTION_TRUST_ANCHOR_PROVISIONED=true``:
        root/marker derivation resolves, the real anchor file is found and
        parses as a valid ``ProductionReadinessTrustAnchor``, and the
        failure boundary correctly moves past the anchor to manifest
        content validation — never a structural failure, and never a
        missing-anchor failure now that one is provisioned."""
        manifest_path = tmp_path / "readiness.json"
        manifest_path.write_bytes(b"{}")
        manifest_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        real_anchor = gate_module._GOVERNED_REPOSITORY_ROOT / GOVERNED_TRUST_ANCHOR_PATH
        assert real_anchor.is_file(), (
            f"expected the real governed anchor to exist at {real_anchor} — "
            "if this fails, PRODUCTION_TRUST_ANCHOR_PROVISIONED has regressed "
            "to false"
        )

        with pytest.raises(
            ReadinessGateError, match="readiness manifest protocol_version is not"
        ):
            enforce_readiness_gate(
                manifest_path=manifest_path,
                release_sha=MERGE_SHA,
                environment="production",
            )
