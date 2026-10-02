"""Adoption V2 complémentaire sur PostgreSQL réel : 479 placements V4, 74 possédés (ADR-0062).

Le défaut venait de ce que les épreuves précédentes réduisaient le prédécesseur à ce
que le successeur prescrit (``if row.content_sha256 in contents`` côté Python) : la
vraie sélection, qui charge toute la release, n'était jamais exercée. Ici le
prédécesseur est complet — 479 placements physiques, onze collections, 405 hors du
périmètre du successeur — et la sélection est celle que le CLI utilise.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    adopter_dsn,
    attestor_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

from ingestor.ingestion_control.sealed_release_adoption import (  # noqa: E402
    SealedReleaseAdoptionError,
    SuccessorIdentity,
    bind_publication_authorities,
    load_acquired_rows,
    load_acquired_rows_in_successor_scope,
    load_adopted_rows,
    persist_successor_control_adoption,
    plan_successor_control_adoption,
)

pytestmark = [pytest.mark.integration, requires_docker]

OPERATEUR = "Alaeddine Ben Rhouma"
V4_MANIFESTE = "e" * 64
HGGSP = ("rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite")
AUTRES = (
    "rag_nexus_dgemc_terminale_option", "rag_nexus_hlp_premiere_specialite",
    "rag_nexus_hlp_terminale_specialite", "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite", "rag_nexus_ses_premiere_specialite",
    "rag_nexus_ses_terminale_specialite", "rag_nexus_svt_premiere_specialite",
    "rag_nexus_svt_terminale_specialite",
)
PAR_HGGSP = {HGGSP[0]: 39, HGGSP[1]: 35}  # 74
PAR_AUTRE = 45  # 9 × 45 = 405


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("adoption-collection-scope")


def _sha(collection: str, i: int) -> str:
    return hashlib.sha256(f"{collection}:{i}".encode()).hexdigest()


def _scope(collection: str) -> Any:
    from nexus_contracts.ingestion import ResourceScope

    _, _, matiere, niveau, *_ = collection.split("_")
    return ResourceScope(
        tenant=f"libre_{niveau}", collection=collection, niveau=niveau, voie="generale",
        matiere=matiere, candidat="libre", audience=["aefe", "libre"], visibility="public",
        school_year="2026-2027", programme_version="EDUSCOL_CORPUS_20260808",
    )


def _payload(sha: str, collection: str, *, release: str, manifeste: str, currentness: str) -> dict[str, Any]:
    return {
        "protocol_version": "SEALED-RELEASE-INGESTION-V1", "pipeline_kind": "sealed_release_pipeline",
        "release_id": release, "release_manifest_sha256": manifeste,
        "artifacts_release_sha256": "8" * 64, "candidate_inventory_sha256": "9" * 64,
        "artifact_transfer_manifest_sha256": "0" * 64, "collection": collection,
        "content_sha256": sha, "placement_id": f"placement-{sha[:12]}",
        "source_placement_id": f"source-{sha[:12]}", "external_document_type": "diaporama",
        "type_doc": "ressource_officielle",
        "provenance_discovery_url": "https://eduscol.education.gouv.fr/5793/ressources",
        "provenance_artifact_url": "https://eduscol.education.gouv.fr/5793/ressources",
        "chunk_count": 23, "review_status": "reviewed", "placement_status": "active",
        "currentness": currentness, "scope_authorization_id": f"adoption-scope-{collection}",
        "scope_authorization_digest": "f" * 64,
    }


def _autorisation(conn: psycopg.Connection[Any], collection: str, *, identifiant: str | None = None,
                  protocole: str = "LOT41A-V1", contenus: tuple[str, ...] | None = None) -> None:
    from test_migration_016_release_identity import _valeur_de_test

    scope = _scope(collection)
    obligatoires = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        " WHERE table_schema='ingestion_control' AND table_name='scope_authorizations' "
        "   AND is_nullable='NO' AND column_default IS NULL ORDER BY ordinal_position"
    ).fetchall()
    donnees = {nom: _valeur_de_test(nom, t) for nom, t in obligatoires}
    donnees.update({
        "authorization_id": identifiant or f"adoption-scope-{collection}", "collection": collection,
        "protocol_version": protocole, "decision": "AUTHORIZE_INGESTION_SCOPE",
        "allowed_content_sha256": list(contenus) if contenus else None,
    })
    for champ in ("tenant", "niveau", "voie", "matiere", "candidat", "visibility",
                  "school_year", "programme_version"):
        if champ in donnees:
            donnees[champ] = getattr(scope, champ)
    if "audience" in donnees:
        donnees["audience"] = list(scope.audience)
    if "allowed_domains" in donnees:
        donnees["allowed_domains"] = ["eduscol.education.gouv.fr"]
    if "rights_categories" in donnees:
        donnees["rights_categories"] = ["officiel_public"]
    if "pii_absence_attested" in donnees:
        donnees["pii_absence_attested"] = True
    if "artifact_path" in donnees:
        donnees["artifact_path"] = f"governance/authorizations/{identifiant or f'adoption-scope-{collection}'}.json"
    noms = ", ".join(donnees)
    valeurs = ", ".join(f"%({nom})s" for nom in donnees)
    conn.execute(
        f"INSERT INTO ingestion_control.scope_authorizations ({noms}) "
        f"VALUES ({valeurs}) ON CONFLICT DO NOTHING", donnees,
    )


def _construire_v4(pg: dict[str, str], release: str, *, hggsp: dict[str, int] | None = None,
                   supplementaires: tuple[tuple[str, str], ...] = ()) -> list[tuple[str, str]]:
    """Le prédécesseur V4 complet, par le chemin de provisionnement canonique.

    Rend les (sha, collection) acquis. ``hggsp`` et ``supplementaires`` fabriquent les
    écarts (73/75) sans toucher aux 405 autres."""
    from ingestor.ingestion_control.provisioning import (
        SEALED_RELEASE_PIPELINE,
        create_ingestion_run,
        create_resource,
        persist_sealed_release_artifact,
    )

    nombres = {**{c: PAR_AUTRE for c in AUTRES}, **(hggsp or PAR_HGGSP)}
    placements = [(_sha(f"{release}:{c}", i), c) for c, n in nombres.items() for i in range(n)]
    placements += list(supplementaires)
    with psycopg.connect(superuser_dsn(pg)) as conn:
        for collection in nombres:
            _autorisation(conn, collection)
        runs = {
            c: create_ingestion_run(conn, scope=_scope(c), profile_version="v2-livraison-319",
                                    trigger="manual")
            for c in nombres
        }
        for sha, collection in placements:
            resource_id = create_resource(
                conn, run_id=runs[collection], scope=_scope(collection), dedup_key=f"{release}:{sha}",
                pipeline_kind=SEALED_RELEASE_PIPELINE,
            )
            persist_sealed_release_artifact(
                conn, resource_id=resource_id, run_id=runs[collection], sha256=sha, size_bytes=1000,
                mime_declared="application/pdf", mime_detected="application/pdf",
                provenance_url="https://eduscol.education.gouv.fr/5793/ressources",
                payload=_payload(sha, collection, release=release, manifeste=V4_MANIFESTE,
                                 currentness="current"),
            )
        conn.commit()
    _attribuer(pg, placements)
    return placements


def _attribuer(pg: dict[str, str], placements: list[tuple[str, str]]) -> None:
    """Attribution gouvernée des artefacts prédécesseurs, comme l'acquisition V4 l'a écrite.

    L'adoption V2 la relit et refuse un prédécesseur qui n'en porte pas."""
    from ingestor.ingestion_control.artifact_attribution import (
        derive_sealed_release_artifact_attribution,
        persist_artifact_attribution,
    )
    from ingestor.ingestion_profiles.registry import load_profile_registry

    profils = {
        p.scope.collection: p
        for p in load_profile_registry(ENGINE_ROOT / "configs/ingestion_profiles/v3_livraison_315").values()
    }
    assert set(HGGSP) <= set(profils), "les deux profils HGGSP doivent exister"
    shas = [sha for sha, _ in placements]
    with psycopg.connect(superuser_dsn(pg)) as conn:
        lignes = conn.execute(
            "SELECT a.artifact_id, a.run_id, a.original_url, r.collection"
            " FROM ingestion_control.artifacts a JOIN ingestion_control.resources r USING (resource_id)"
            " WHERE a.sha256 = ANY(%s)", (shas,),
        ).fetchall()
        for artifact_id, run_id, url, collection in lignes:
            if collection not in profils:
                continue
            persist_artifact_attribution(
                conn,
                attribution=derive_sealed_release_artifact_attribution(
                    ingestion_artifact_id=artifact_id,
                    catalog_entry={"type_doc": "ressource_officielle", "source_url": url},
                    profile=profils[collection]),
                run_id=run_id, actor="adoption-collection-scope-test",
            )
        conn.commit()


def _successeur(case: str) -> SuccessorIdentity:
    return SuccessorIdentity(
        release_id=f"production-profile-gate-2026-2027-v5-hggsp-{case}",
        release_manifest_sha256="2" * 64, artifacts_release_sha256="3" * 64,
        candidate_inventory_sha256="4" * 64, artifact_transfer_manifest_sha256="5" * 64,
        currentness_evidence_sha256="6" * 64, pii_evidence_sha256="7" * 64,
    )


def _prescrits(placements: list[tuple[str, str]], successeur: SuccessorIdentity) -> list[dict[str, Any]]:
    prescrits = []
    for sha, collection in placements:
        if collection not in HGGSP:
            continue
        payload = _payload(sha, collection, release=successeur.release_id,
                           manifeste=successeur.release_manifest_sha256,
                           currentness="official_snapshot")
        payload.pop("scope_authorization_id")
        payload.pop("scope_authorization_digest")
        prescrits.append(payload)
    return prescrits


def _selection_du_cli(conn: psycopg.Connection[Any], release: str, prescrits: list[dict[str, Any]],
                      successeur: SuccessorIdentity) -> list[Any]:
    """Exactement ce que fait ``adopt-predecessor-release`` en V2 : sélection scopée, puis plan."""
    return plan_successor_control_adoption(
        acquired=load_acquired_rows_in_successor_scope(
            conn, release_id=release, successor_placements=prescrits),
        successor_placements=prescrits, successor=successeur,
        predecessor_release_id=release, predecessor_release_manifest_sha256=V4_MANIFESTE,
    )


def _etat_predecesseur(pg: dict[str, str], release: str, *, hors_perimetre: bool) -> list[tuple[Any, ...]]:
    filtre = "AND r.collection <> ALL(%s)" if hors_perimetre else ""
    params: tuple[Any, ...] = (release, list(HGGSP)) if hors_perimetre else (release,)
    with psycopg.connect(superuser_dsn(pg)) as conn:
        return conn.execute(
            "SELECT r.resource_id, r.collection, r.resource_state, r.state_version, a.artifact_id,"
            " a.sha256, a.payload::text FROM ingestion_control.resources r"
            " JOIN ingestion_control.artifacts a ON a.resource_id = r.resource_id"
            f" WHERE a.payload->>'release_id' = %s {filtre} ORDER BY r.resource_id", params,
        ).fetchall()


def _compte(pg: dict[str, str], sql: str, *params: Any) -> int:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        return int(conn.execute(sql, params).fetchone()[0])


# ── le cas réel : 479 physiques, 74 possédés, 74 adoptés, 405 intacts ──────────


def test_479_physiques_74_adoptes_405_intacts_rejeu_et_chaine(pg: dict[str, str]) -> None:
    release, successeur = "production-profile-gate-2026-2027-v4-nominal", _successeur("nominal")
    placements = _construire_v4(pg, release)
    prescrits = _prescrits(placements, successeur)
    assert len(placements) == 479 and len(prescrits) == 74
    assert len({c for _, c in placements}) == 11
    avant_tout, avant_hors = (_etat_predecesseur(pg, release, hors_perimetre=False),
                              _etat_predecesseur(pg, release, hors_perimetre=True))
    assert len(avant_tout) == 479 and len(avant_hors) == 405

    with psycopg.connect(adopter_dsn(pg)) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        # 479 physiques ; 74 seulement dans les collections du successeur.
        assert len(load_acquired_rows(conn, release_id=release)) == 479
        assert len(load_acquired_rows_in_successor_scope(
            conn, release_id=release, successor_placements=prescrits)) == 74
        # Le défaut corrigé, sur PostgreSQL réel : charger toute la release V4 comparait 479 acquis
        # aux 74 prescrits, et refusait 405 « orphelins ». La bijection elle-même reste stricte.
        with pytest.raises(SealedReleaseAdoptionError, match="0 prescribed but never acquired, 405 acquired"):
            plan_successor_control_adoption(
                acquired=load_acquired_rows(conn, release_id=release), successor_placements=prescrits,
                successor=successeur, predecessor_release_id=release,
                predecessor_release_manifest_sha256=V4_MANIFESTE)
        lignes = _selection_du_cli(conn, release, prescrits, successeur)
        ressources, artefacts, ecrites, deja = persist_successor_control_adoption(
            conn, lignes=lignes, adopted_by=OPERATEUR)
        conn.commit()
    assert (len(lignes), ressources, artefacts, ecrites, deja) == (74, 74, 74, 74, 0)

    # exactement 74 adoptions V2, deux collections, aucune pour les 405
    sql = ("SELECT count(*) FROM ingestion_control.sealed_release_adoptions"
           " WHERE release_id = %s")
    assert _compte(pg, sql, successeur.release_id) == 74
    assert _compte(pg, sql + " AND adoption_version = 'SEALED-RELEASE-ADOPTION-V2'",
                   successeur.release_id) == 74
    assert _compte(pg, sql + " AND collection <> ALL(%s)", successeur.release_id, list(HGGSP)) == 0
    assert _compte(pg, "SELECT count(DISTINCT successor_resource_id) FROM ingestion_control.sealed_release_adoptions"
                       " WHERE release_id = %s", successeur.release_id) == 74
    assert _compte(pg, "SELECT count(DISTINCT successor_artifact_id) FROM ingestion_control.sealed_release_adoptions"
                       " WHERE release_id = %s", successeur.release_id) == 74
    # aucune adoption n'a touché les 405 (ni leurs ressources ni leurs artefacts), ni les 479
    assert _etat_predecesseur(pg, release, hors_perimetre=True) == avant_hors
    assert _etat_predecesseur(pg, release, hors_perimetre=False) == avant_tout
    assert _compte(pg, "SELECT count(*) FROM ingestion_control.sealed_release_adoptions"
                       " WHERE predecessor_release_id = %s AND release_id <> %s",
                   release, successeur.release_id) == 0

    # rejeu : written=0, already_present=74, aucune 75e adoption
    with psycopg.connect(adopter_dsn(pg)) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        relance = _selection_du_cli(conn, release, prescrits, successeur)
        assert persist_successor_control_adoption(
            conn, lignes=relance, adopted_by=OPERATEUR) == (0, 0, 0, 74)
        conn.commit()
    assert _compte(pg, sql, successeur.release_id) == 74

    # la chaîne en aval ne voit que ces 74
    with psycopg.connect(attestor_dsn(pg)) as conn:  # le rôle qui lit la chaîne, pas l'adopter
        adoptees = load_adopted_rows(conn, release_id=successeur.release_id)
    assert len(adoptees) == 74 and {ligne[3] for ligne in adoptees} == set(HGGSP)
    # les identités rendues sont celles du SUCCESSEUR (V2), jamais celles des 74 prédécesseurs V4
    assert {ligne[0] for ligne in adoptees} == {row.successor_resource_id for row in lignes}
    assert {ligne[1] for ligne in adoptees} == {row.successor_artifact_id for row in lignes}
    assert not ({ligne[0] for ligne in adoptees} & {row.resource_id for row in lignes})
    shas = {c: tuple(s for s, col in placements if col == c) for c in HGGSP}
    autorites = {
        c: SimpleNamespace(
            protocol_version="LOT41A-V2", authorization_id=f"adoption-scope-successor-r4-{c}",
            authorization_digest="d" * 64, allowed_content_sha256=shas[c],
            scope=SimpleNamespace(collection=c))
        for c in HGGSP
    }
    with psycopg.connect(superuser_dsn(pg)) as conn:  # les deux r4 successeur, enregistrées avant la liaison
        for c in HGGSP:
            _autorisation(conn, c, identifiant=f"adoption-scope-successor-r4-{c}",
                          protocole="LOT41A-V2", contenus=tuple(sorted(shas[c])))
        conn.commit()
    with psycopg.connect(attestor_dsn(pg)) as conn:
        assert bind_publication_authorities(
            conn, release_id=successeur.release_id, authorities=autorites, bound_by=OPERATEUR) == (74, 0)
        conn.commit()
    lien = "SELECT count(*) FROM ingestion_control.sealed_release_publication_authorizations WHERE release_id = %s"
    assert _compte(pg, lien, successeur.release_id) == 74
    assert _compte(pg, lien, release) == 0
    assert _compte(pg, "SELECT count(DISTINCT collection) FROM ingestion_control.sealed_release_publication_authorizations"
                       " WHERE release_id = %s", successeur.release_id) == 2
    # l'identité d'audit est stockée telle quelle, sans guillemets
    assert _compte(pg, "SELECT count(*) FROM ingestion_control.sealed_release_adoptions"
                       " WHERE release_id = %s AND adopted_by = %s", successeur.release_id, OPERATEUR) == 74
    assert _compte(pg, "SELECT count(*) FROM ingestion_control.sealed_release_publication_authorizations"
                       " WHERE release_id = %s AND bound_by = %s", successeur.release_id, OPERATEUR) == 74


# ── refus dans le périmètre : avant toute écriture ────────────────────────────


def _refus_sans_ecriture(pg: dict[str, str], release: str, successeur: SuccessorIdentity,
                         prescrits: list[dict[str, Any]], motif: str) -> None:
    avant = _etat_predecesseur(pg, release, hors_perimetre=False)
    with psycopg.connect(adopter_dsn(pg)) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        with pytest.raises(SealedReleaseAdoptionError, match=motif):
            persist_successor_control_adoption(
                conn, lignes=_selection_du_cli(conn, release, prescrits, successeur),
                adopted_by=OPERATEUR)
        conn.rollback()
    assert _compte(pg, "SELECT count(*) FROM ingestion_control.sealed_release_adoptions"
                       " WHERE release_id = %s", successeur.release_id) == 0
    assert _etat_predecesseur(pg, release, hors_perimetre=False) == avant


def test_75_acquis_dans_le_perimetre_pour_74_prescrits_refuse(pg: dict[str, str]) -> None:
    release, successeur = "production-profile-gate-2026-2027-v4-extra", _successeur("extra")
    placements = _construire_v4(pg, release, supplementaires=(("e" * 64, HGGSP[0]),))
    prescrits = _prescrits(placements[:-1], successeur)  # 74 prescrits, 75 acquis dans les 2 collections
    assert len(prescrits) == 74
    _refus_sans_ecriture(pg, release, successeur, prescrits, "0 prescribed but never acquired, 1 acquired")


def test_73_acquis_dans_le_perimetre_pour_74_prescrits_refuse(pg: dict[str, str]) -> None:
    release, successeur = "production-profile-gate-2026-2027-v4-manque", _successeur("manque")
    placements = _construire_v4(pg, release, hggsp={HGGSP[0]: 38, HGGSP[1]: 35})  # 73 acquis
    prescrits = _prescrits(placements, successeur)
    prescrits.append(_prescrits([(_sha("jamais-acquis", 0), HGGSP[0])], successeur)[0])  # 74 prescrits
    assert len(prescrits) == 74
    _refus_sans_ecriture(pg, release, successeur, prescrits, "1 prescribed but never acquired, 0 acquired")


def test_placement_divergent_dans_le_perimetre_refuse(pg: dict[str, str]) -> None:
    release, successeur = "production-profile-gate-2026-2027-v4-diverge", _successeur("diverge")
    placements = _construire_v4(pg, release)
    prescrits = _prescrits(placements, successeur)
    prescrits[0] = {**prescrits[0], "placement_id": "un-autre-placement"}
    _refus_sans_ecriture(pg, release, successeur, prescrits, "not in bijection")


def test_fait_invariant_divergent_dans_le_perimetre_refuse(pg: dict[str, str]) -> None:
    release, successeur = "production-profile-gate-2026-2027-v4-fait", _successeur("fait")
    placements = _construire_v4(pg, release)
    prescrits = _prescrits(placements, successeur)
    prescrits[0] = {**prescrits[0], "chunk_count": 999}
    _refus_sans_ecriture(pg, release, successeur, prescrits, "differs from what was acquired")
