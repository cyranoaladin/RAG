"""Domaine de la bijection d'une adoption V2 complémentaire (ADR-0062), sans base.

Le défaut : ``load_acquired_rows(release_id=V4)`` chargeait les 479 placements de
V4 et la bijection les comparait aux 74 que le successeur prescrit — 405 « orphelins ».
La règle correcte : la bijection est stricte DANS les collections que le successeur
possède, dérivées de ses placements scellés, et seulement là.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pytest

from ingestor.ingestion_control import sealed_release_adoption as module
from ingestor.ingestion_control.sealed_release_adoption import (
    AcquiredRow,
    SealedReleaseAdoptionError,
    SuccessorIdentity,
    load_acquired_rows,
    load_acquired_rows_in_successor_scope,
    plan_successor_control_adoption,
    successor_scope_collections,
)

V4 = "production-profile-gate-2026-2027-v4"
V4_MANIFESTE = "bab9c398f59eb8b0f2f5324ed2853652" + "0" * 32
V5 = SuccessorIdentity(
    release_id="production-profile-gate-2026-2027-v5-hggsp",
    release_manifest_sha256="2" * 64,
    artifacts_release_sha256="3" * 64,
    candidate_inventory_sha256="4" * 64,
    artifact_transfer_manifest_sha256="5" * 64,
    currentness_evidence_sha256="6" * 64,
    pii_evidence_sha256="7" * 64,
)
HGGSP = ("rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite")
AUTRES = (
    "rag_nexus_dgemc_terminale_option", "rag_nexus_hlp_premiere_specialite",
    "rag_nexus_hlp_terminale_specialite", "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite", "rag_nexus_ses_premiere_specialite",
    "rag_nexus_ses_terminale_specialite", "rag_nexus_svt_premiere_specialite",
    "rag_nexus_svt_terminale_specialite",
)
PAR_HGGSP = (39, 35)  # 74 placements, comme sur le staging
PAR_AUTRE = 45  # 9 × 45 = 405


def _payload(sha: str, collection: str, *, release: str, manifeste: str, currentness: str) -> dict[str, Any]:
    return {
        "protocol_version": "SEALED-RELEASE-INGESTION-V1",
        "pipeline_kind": "sealed_release_pipeline",
        "release_id": release, "release_manifest_sha256": manifeste,
        "artifacts_release_sha256": "8" * 64, "candidate_inventory_sha256": "9" * 64,
        "artifact_transfer_manifest_sha256": "0" * 64,
        "collection": collection, "content_sha256": sha,
        "placement_id": f"placement-{sha[:12]}-{collection}",
        "source_placement_id": f"source-{sha[:12]}",
        "external_document_type": "diaporama", "type_doc": "ressource_officielle",
        "provenance_discovery_url": "https://eduscol.education.gouv.fr/p",
        "provenance_artifact_url": "https://eduscol.education.gouv.fr/p",
        "chunk_count": 12, "review_status": "reviewed", "placement_status": "active",
        "currentness": currentness,
    }


def _sha(collection: str, i: int) -> str:
    return hashlib.sha256(f"{collection}:{i}".encode()).hexdigest()


def _placements() -> list[tuple[str, str]]:
    """(sha, collection) : 74 HGGSP + 405 autres = 479."""
    lignes: list[tuple[str, str]] = []
    for collection, nombre in zip(HGGSP, PAR_HGGSP, strict=True):
        lignes += [(_sha(collection, i), collection) for i in range(nombre)]
    for collection in AUTRES:
        lignes += [(_sha(collection, i), collection) for i in range(PAR_AUTRE)]
    return lignes


def _acquis(placements: Sequence[tuple[str, str]]) -> list[AcquiredRow]:
    return [
        AcquiredRow(
            resource_id=uuid4(), artifact_id=uuid4(), content_sha256=sha, collection=collection,
            payload=_payload(sha, collection, release=V4, manifeste=V4_MANIFESTE, currentness="current"),
        )
        for sha, collection in placements
    ]


def _prescrits(placements: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    return [
        _payload(sha, collection, release=V5.release_id, manifeste=V5.release_manifest_sha256,
                 currentness="official_snapshot")
        for sha, collection in placements if collection in HGGSP
    ]


def _plan(acquis: Sequence[AcquiredRow], prescrits: Sequence[dict[str, Any]]) -> list[Any]:
    return plan_successor_control_adoption(
        acquired=acquis, successor_placements=prescrits, successor=V5,
        predecessor_release_id=V4, predecessor_release_manifest_sha256=V4_MANIFESTE,
    )


class _Curseur:
    def __init__(self, lignes: list[tuple[Any, ...]]) -> None:
        self.lignes = lignes

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.lignes

    def fetchone(self) -> tuple[Any, ...]:
        return (True,)


class _Connexion:
    """Rejoue la sélection SQL en mémoire : applique ``r.collection = ANY(%s)`` si présent."""

    def __init__(self, acquis: Sequence[AcquiredRow]) -> None:
        self.acquis = list(acquis)
        self.requetes: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Curseur:
        if "pg_attribute" in sql:
            return _Curseur([(True,)])
        self.requetes.append((sql, params))
        retenues = self.acquis
        if "r.collection = ANY(%s)" in sql:
            retenues = [row for row in retenues if row.collection in params[2]]
        return _Curseur([
            (row.resource_id, row.artifact_id, row.content_sha256, row.collection, row.payload)
            for row in retenues
        ])


# ── la baseline : 479 placements physiques, 74 possédés par le successeur ──────


def test_baseline_479_acquis_dont_74_dans_les_collections_du_successeur() -> None:
    placements = _placements()
    assert len(placements) == 479
    assert sum(1 for _, c in placements if c in HGGSP) == 74
    assert sum(1 for _, c in placements if c not in HGGSP) == 405
    assert len({c for _, c in placements}) == 11


def test_defaut_corrige_la_release_entiere_est_refusee_comme_avant() -> None:
    """Le comportement qui a refusé l'adoption réelle, figé : la bijection reste stricte."""
    placements = _placements()
    with pytest.raises(SealedReleaseAdoptionError, match="0 prescribed but never acquired, 405 acquired"):
        _plan(_acquis(placements), _prescrits(placements))


def test_perimetre_derive_des_placements_scelles_du_successeur() -> None:
    assert successor_scope_collections(_prescrits(_placements())) == sorted(HGGSP)


@pytest.mark.parametrize("prescrits", [[], [{"collection": ""}], [{"collection": None}], [{}], [{"collection": 3}]])
def test_perimetre_non_derivable_refuse(prescrits: list[dict[str, Any]]) -> None:
    with pytest.raises(SealedReleaseAdoptionError):
        successor_scope_collections(prescrits)


def test_selection_scopee_charge_74_sur_479_et_v1_garde_la_release_entiere() -> None:
    placements = _placements()
    connexion = _Connexion(_acquis(placements))
    scopes = load_acquired_rows_in_successor_scope(
        connexion, release_id=V4, successor_placements=_prescrits(placements))
    assert len(scopes) == 74 and {row.collection for row in scopes} == set(HGGSP)
    sql, params = connexion.requetes[-1]
    assert "r.collection = ANY(%s)" in sql and params[2] == sorted(HGGSP)
    # V1 / historique : aucun domaine, toute la release.
    historique = load_acquired_rows(connexion, release_id=V4)
    assert len(historique) == 479
    assert "r.collection = ANY(%s)" not in connexion.requetes[-1][0]


def test_domaine_vide_n_est_jamais_une_selection_de_tout() -> None:
    with pytest.raises(SealedReleaseAdoptionError, match="empty collection scope"):
        load_acquired_rows(_Connexion(_acquis(_placements())), release_id=V4, collections=[])


def test_adoption_74_sur_74_dans_le_perimetre_du_successeur() -> None:
    placements = _placements()
    connexion = _Connexion(_acquis(placements))
    prescrits = _prescrits(placements)
    scopes = load_acquired_rows_in_successor_scope(
        connexion, release_id=V4, successor_placements=prescrits)
    lignes = _plan(scopes, prescrits)
    assert len(lignes) == 74
    assert {ligne.collection for ligne in lignes} == set(HGGSP)
    assert len({ligne.successor_resource_id for ligne in lignes}) == 74
    assert len({ligne.successor_artifact_id for ligne in lignes}) == 74
    # aucune des 405 n'est concernée
    non_hggsp = {row.resource_id for row in connexion.acquis if row.collection not in HGGSP}
    assert len(non_hggsp) == 405 and not (non_hggsp & {ligne.resource_id for ligne in lignes})


# ── refus à l'intérieur du périmètre : jamais « les 74 qui correspondent » ──────


def _scope(placements: Sequence[tuple[str, str]], acquis: list[AcquiredRow],
           prescrits: list[dict[str, Any]]) -> list[AcquiredRow]:
    return load_acquired_rows_in_successor_scope(
        _Connexion(acquis), release_id=V4, successor_placements=prescrits)


def test_75_acquis_dans_le_perimetre_pour_74_prescrits_refuse() -> None:
    placements = _placements()
    extra = ("e" * 64, HGGSP[0])
    acquis = _acquis([*placements, extra])
    prescrits = _prescrits(placements)
    assert len(_scope(placements, acquis, prescrits)) == 75
    with pytest.raises(SealedReleaseAdoptionError, match="0 prescribed but never acquired, 1 acquired"):
        _plan(_scope(placements, acquis, prescrits), prescrits)


def test_73_acquis_dans_le_perimetre_pour_74_prescrits_refuse() -> None:
    placements = _placements()
    manquant = next(p for p in placements if p[1] in HGGSP)
    acquis = _acquis([p for p in placements if p != manquant])
    prescrits = _prescrits(placements)
    assert len(_scope(placements, acquis, prescrits)) == 73
    with pytest.raises(SealedReleaseAdoptionError, match="1 prescribed but never acquired, 0 acquired"):
        _plan(_scope(placements, acquis, prescrits), prescrits)


def test_placement_divergent_dans_le_perimetre_refuse() -> None:
    placements = _placements()
    acquis = _acquis(placements)
    cible = next(row for row in acquis if row.collection in HGGSP)
    cible.payload["placement_id"] = "autre-placement"
    prescrits = _prescrits(placements)
    with pytest.raises(SealedReleaseAdoptionError, match="not in bijection"):
        _plan(_scope(placements, acquis, prescrits), prescrits)


def test_sha_divergent_dans_le_perimetre_refuse() -> None:
    placements = _placements()
    prescrits = _prescrits(placements)
    prescrits[0] = {**prescrits[0], "content_sha256": "d" * 64}
    with pytest.raises(SealedReleaseAdoptionError, match="not in bijection"):
        _plan(_scope(placements, _acquis(placements), prescrits), prescrits)


def test_fait_invariant_divergent_dans_le_perimetre_refuse() -> None:
    placements = _placements()
    prescrits = _prescrits(placements)
    prescrits[0] = {**prescrits[0], "chunk_count": 999}
    with pytest.raises(SealedReleaseAdoptionError, match="differs from what was acquired"):
        _plan(_scope(placements, _acquis(placements), prescrits), prescrits)


def test_doublon_acquis_dans_le_perimetre_refuse() -> None:
    placements = _placements()
    acquis = _acquis(placements)
    prescrits = _prescrits(placements)
    doublon = next(row for row in acquis if row.collection in HGGSP)
    acquis.append(AcquiredRow(
        resource_id=uuid4(), artifact_id=uuid4(), content_sha256=doublon.content_sha256,
        collection=doublon.collection, payload=dict(doublon.payload)))
    with pytest.raises(SealedReleaseAdoptionError, match="acquired twice"):
        _plan(_scope(placements, acquis, prescrits), prescrits)


def test_un_acquis_hors_perimetre_ne_masque_jamais_un_manque_dans_le_perimetre() -> None:
    """Les 405 hors périmètre ne « complètent » pas un manque HGGSP."""
    placements = _placements()
    prescrits = _prescrits(placements)
    acquis = _acquis([p for p in placements if p[1] not in HGGSP][:1])  # aucun HGGSP acquis
    with pytest.raises(SealedReleaseAdoptionError, match="no placement was acquired|74 prescribed but never acquired"):
        _plan(_scope(placements, acquis, prescrits), prescrits)


# ── l'opérateur ne décide pas du périmètre ───────────────────────────────────


def test_la_cli_n_offre_aucun_moyen_de_choisir_le_perimetre() -> None:
    from ingestor.ingestion_worker.attest_publication_cli import _build_arg_parser

    sous_parseurs = next(
        action for action in _build_arg_parser()._actions if hasattr(action, "choices") and action.choices
    )
    options = set(sous_parseurs.choices["adopt-predecessor-release"]._option_string_actions)
    interdites = {"--collection", "--collections", "--scope", "--placement", "--placements",
                  "--resource-id", "--resource-ids", "--only", "--include", "--exclude"}
    assert not (options & interdites), options & interdites


def test_la_cli_v2_derive_son_domaine_des_placements_scelles() -> None:
    import ast
    from pathlib import Path

    source = Path(module.__file__).resolve().parents[1] / "ingestion_worker/attest_publication_cli.py"
    arbre = ast.parse(source.read_text(encoding="utf-8"))
    appels = [
        n for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "load_acquired_rows_in_successor_scope"
    ]
    assert len(appels) == 1
    mots = {kw.arg: ast.unparse(kw.value) for kw in appels[0].keywords}
    assert mots["successor_placements"] == "prescrits"  # jamais une liste fournie
    texte = source.read_text(encoding="utf-8")
    assert "load_acquired_rows(conn, release_id=args.predecessor_release_id)" in texte  # V1 inchangé
