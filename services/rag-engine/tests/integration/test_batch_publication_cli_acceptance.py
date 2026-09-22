"""Test d'acceptation du parcours BATCH, depuis le vrai CLI (lot CU).

Il part de données au **format historique** — celles qu'écrit le point
d'entrée de release scellée — et exige qu'un job batch parcoure la chaîne
jusqu'à l'index produit, puis que son contenu soit récupérable.

Il commence en échec : c'est ce qui montre quel maillon manque réellement.
Chaque refus rencontré est consigné tel quel, jamais maquillé en succès
attendu.

Les autorités utilisées ici sont des **données de test**, explicitement
nommées comme telles. Elles n'autorisent aucune publication réelle.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _banc_multiniveaux import (  # noqa: E402
    PROFILS_DIR,
    VERSION_DE_PROFIL,
    ContexteDuBanc,
    construire_contexte_du_banc,
    contenus_du_banc,
    environnement_de_readiness,
)
from _local_github import (  # noqa: E402
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    local_github_server,
)
from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    start_rag_product_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

if os.environ.get("NEXUS_BATCH_CLI_ACCEPTANCE") != "1":
    pytest.skip(
        "batch CLI acceptance not requested (NEXUS_BATCH_CLI_ACCEPTANCE=1)",
        allow_module_level=True,
    )

#: Périmètre de la release scellée réelle — ses OCTETS servent de matière,
#: ses autorités ne sont pas rejouées comme autorités de publication.
RELEASE_DIR = REPOSITORY_ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
    "release-1b9eba0c0eb0ab13/profile_gate"
)
TRANSFER_MANIFEST = REPOSITORY_ROOT / (
    "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
)
PROFILES_DIR = ENGINE_ROOT / "configs/ingestion_profiles/v2_livraison_319"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("batch-cli-acceptance")


@pytest.fixture(scope="module")
def product_pg() -> Iterator[dict[str, str]]:
    """La base PRODUIT du banc — celle que Worker B remplit reellement."""
    yield from start_rag_product_postgres("batch-cli-product")


def _run(
    module: str, args: Sequence[str], env: Mapping[str, str], timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    child_env = {
        **os.environ,
        **env,
        "PYTHONPATH": f"{ENGINE_ROOT / 'src'}:{REPOSITORY_ROOT / 'packages/contracts/src'}",
    }
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=child_env,
        cwd=REPOSITORY_ROOT,
        check=False,
    )


def test_les_prerequis_du_banc_sont_reunis() -> None:
    """Un skip n'est pas une exécution : les prérequis sont vérifiés ici."""
    assert RELEASE_DIR.is_dir(), RELEASE_DIR
    assert (RELEASE_DIR / "production-profile-gate.release.json").is_file()
    assert (RELEASE_DIR / "artifacts.release.json").is_file()
    assert TRANSFER_MANIFEST.is_file(), TRANSFER_MANIFEST
    assert PROFILES_DIR.is_dir(), PROFILES_DIR
    assert len(list(PROFILES_DIR.glob("*.yml"))) == 11


def test_le_catalogue_scelle_se_charge_depuis_le_manifeste(
    control_pg: dict[str, str],
) -> None:
    """Maillon 1 — le catalogue vient du fichier que le manifeste nomme."""
    from ingestor.ingestion_control.sealed_release_catalog import (
        load_sealed_release_catalog,
    )

    manifeste = RELEASE_DIR / "production-profile-gate.release.json"
    catalogue = load_sealed_release_catalog(
        RELEASE_DIR,
        expected_release_manifest_sha256=_sha(manifeste),
        transfer_manifest_path=TRANSFER_MANIFEST,
        expected_transfer_manifest_sha256=_sha(TRANSFER_MANIFEST),
    )
    assert len(catalogue) == 315
    assert catalogue.media_type_invariant == "application/pdf"


def test_le_producteur_d_attestation_batch_existe() -> None:
    """Maillon 2 — l'outil qui produit l'artefact de revue batch.

    Le protocole ``LOT42-RELEASE-BATCH-V1`` a son contrat et son stockage.
    Cette épreuve établit si un PRODUCTEUR existe : sans lui, aucune
    attestation batch ne peut être proposée ni enregistrée, et la chaîne
    s'arrête avant le job.
    """
    aide = _run("ingestor.ingestion_worker.attest_publication_cli", ["--help"], {})
    assert aide.returncode == 0, aide.stderr
    sous_commandes = aide.stdout
    assert "release-batch" in sous_commandes or "batch" in sous_commandes, (
        "aucune sous-commande batch dans attest_publication_cli — le "
        "producteur d'attestation batch n'existe pas encore.\n"
        f"sous-commandes disponibles :\n{sous_commandes}"
    )


def test_un_job_batch_sans_identite_d_artefact_est_refuse(
    control_pg: dict[str, str],
) -> None:
    """Maillon 3 — « le plus récent » n'est pas une règle d'autorité."""
    from ingestor.ingestion_control.provisioning import (
        SealedReleaseRowError,
        find_authorised_artifact,
    )

    inconnu = uuid.uuid4()
    with psycopg.connect(app_dsn(control_pg)) as conn:
        with pytest.raises(SealedReleaseRowError, match="does not belong to resource"):
            find_authorised_artifact(
                conn, resource_id=uuid.uuid4(), artifact_id=inconnu
            )
        conn.rollback()


def test_le_schema_porte_l_identite_de_release_pour_une_attestation_batch(
    control_pg: dict[str, str],
) -> None:
    """Maillon 4 — la migration additive.

    Une ligne d'attestation batch doit pouvoir dire de QUELLE release elle
    relève. Sans colonne d'identité, ``require_release_batch_review_matches_release``
    n'aurait aucune donnée persistée à relire.
    """
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        colonnes = {
            ligne[0]
            for ligne in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='ingestion_control' "
                "  AND table_name='publication_attestations'"
            ).fetchall()
        }
        conn.rollback()
    assert "release_id" in colonnes, (
        "publication_attestations ne porte aucune identité de release : une "
        "attestation batch ne pourrait pas nommer la release qu'elle atteste.\n"
        f"colonnes présentes : {sorted(colonnes)}"
    )


#: Autorites de TEST du banc. Elles ne valent jamais autorisation reelle.
#: Identites du BANC, distinctes a chaque execution du module : la base est
#: partagee, et des identites fixes rendraient les tests dependants de leur
#: ordre. Elles ne valent jamais autorisation reelle.
_EMPREINTE_DU_BANC = uuid.uuid4().hex[:12]
REVUE_DE_TEST = f"revue-batch-acceptance-{_EMPREINTE_DU_BANC}"


def _autorisation_de(release_id: str, collection: str) -> str:
    """UNE autorisation par (release, collection).

    Le publisher confronte le scope de l'AUTORISATION a celui du
    placement : une autorisation unique couvrant deux collections
    publierait la seconde sous le perimetre de la premiere.
    """
    suffixe = release_id.rsplit("-", 1)[-1]
    return f"acceptance-scope-{suffixe}-{collection}"


def _contexte_du_banc(tmp_path: Path) -> ContexteDuBanc:
    """La chaine d'autorites du banc, produite ENSEMBLE.

    Chemins, empreintes et identites viennent d'un seul assemblage : c'est
    ce que Worker B exige, et c'est ce qu'une trentaine de valeurs
    independantes ne peut pas garantir.
    """
    contenus = contenus_du_banc(tmp_path / "store", empreinte=uuid.uuid4().hex[:8])
    return construire_contexte_du_banc(
        tmp_path / "release", tmp_path / "store", contenus=contenus
    )


def _semer_etat_historique(
    pg: dict[str, str],
    *,
    contexte: ContexteDuBanc,
    github: LocalGitHub,
    env: Mapping[str, str],
) -> list[dict[str, object]]:
    """Ecrit des lignes au FORMAT HISTORIQUE — celui qu'ecrit l'ingestion de
    release scellee : ``canonical_url`` nulle, payload de release, aucun fait
    unitaire.

    C'est une preparation d'etat initial, pas un contournement : les
    controles que le parcours doit exercer restent tous en place. Les scopes
    ne sont pas ecrits a la main : ils viennent des PROFILS gouvernes, ceux
    que le worker chargera.
    """
    from _banc_multiniveaux import LISTING_OFFICIEL, PROFILS_DIR

    from ingestor.ingestion_control.artifact_attribution import (
        derive_sealed_release_artifact_attribution,
        persist_artifact_attribution,
    )
    from ingestor.ingestion_control.provisioning import (
        SEALED_RELEASE_PIPELINE,
        create_ingestion_run,
        create_resource,
        persist_sealed_release_artifact,
        persist_sealed_release_candidate,
    )
    from ingestor.ingestion_profiles.registry import load_profile_registry

    profils = load_profile_registry(PROFILS_DIR)
    artefacts: list[dict[str, object]] = []
    # Les autorisations D'ABORD, par le vrai CLI d'autorite : une ressource
    # ne peut pas referencer une autorisation qui n'existe pas encore.
    for index, collection in enumerate(contexte.collections, start=1):
        _enregistrer_autorisation(
            github=github,
            profil=profils[(collection, VERSION_DE_PROFIL)],
            autorisation_id=_autorisation_de(contexte.release_id, collection),
            contexte=contexte,
            numero=7100 + index,
            env=env,
        )
    with psycopg.connect(superuser_dsn(pg)) as conn:
        for collection in contexte.collections:
            profil = profils[(collection, VERSION_DE_PROFIL)]
            autorisation_id = _autorisation_de(contexte.release_id, collection)
            run_id = create_ingestion_run(
                conn,
                scope=profil.scope,
                profile_version=VERSION_DE_PROFIL,
                trigger="manual",
            )
            for contenu in contexte.contenus:
                payload = {
                    "release_id": contexte.release_id,
                    # Les digests REELS de la release ecrite : la garde du
                    # catalogue refuse toute valeur qui ne serait pas la sienne.
                    "release_manifest_sha256": contexte.digests[
                        "release_manifest_sha256"
                    ],
                    "artifacts_release_sha256": contexte.digests[
                        "artifacts_release_sha256"
                    ],
                    "candidate_inventory_sha256": contexte.digests[
                        "candidate_inventory_sha256"
                    ],
                    "artifact_transfer_manifest_sha256": contexte.digests[
                        "artifact_transfer_manifest_sha256"
                    ],
                    "content_sha256": contenu.content_sha256,
                    "collection": collection,
                    "chunk_count": contenu.pages,
                    "scope_authorization_id": autorisation_id,
                    "provenance_artifact_url": contenu.url_telechargement,
                    "provenance_discovery_url": LISTING_OFFICIEL,
                    "review_status": "reviewed",
                    "placement_status": "active",
                    "currentness": "current",
                    "type_doc": contexte.type_doc,
                    "pipeline_kind": SEALED_RELEASE_PIPELINE,
                    "protocol_version": "LOT42-RELEASE-BATCH-V1",
                }
                resource_id = create_resource(
                    conn, run_id=run_id, scope=profil.scope,
                    dedup_key=contenu.content_sha256,
                    pipeline_kind=SEALED_RELEASE_PIPELINE,
                )
                persist_sealed_release_candidate(
                    conn, resource_id=resource_id, run_id=run_id,
                    dedup_key=contenu.content_sha256,
                    source_url=LISTING_OFFICIEL,
                    domain="eduscol.education.gouv.fr",
                    proposed_type_doc=contexte.type_doc, payload=payload,
                )
                artifact_id = persist_sealed_release_artifact(
                    conn, resource_id=resource_id, run_id=run_id,
                    sha256=contenu.content_sha256, size_bytes=len(contenu.octets),
                    mime_declared="application/pdf",
                    mime_detected="application/pdf",
                    provenance_url=contenu.url_telechargement,
                    payload=payload,
                )
                # Les quatre faits d'attribution, derives des autorites de la
                # release elle-meme : c'est ce que l'ingestion scellee ecrit
                # desormais, et ce que l'attestation batch relit.
                persist_artifact_attribution(
                    conn,
                    attribution=derive_sealed_release_artifact_attribution(
                        ingestion_artifact_id=artifact_id,
                        catalog_entry={
                            "type_doc": contexte.type_doc,
                            "source_url": contenu.url_telechargement,
                        },
                        profile=profil,
                    ),
                    run_id=run_id,
                    actor="acceptance-bench",
                )
                # Les dix transitions HISTORIQUES, comme l'ingestion de
                # release scellee les ecrit. Elles sont referencees par
                # l'attestation, jamais reecrites.
                _semer_transitions(conn, resource_id=resource_id, run_id=run_id)
                artefacts.append({
                    "resource_id": resource_id, "artifact_id": artifact_id,
                    "content_sha256": contenu.content_sha256,
                    "collection": collection,
                })
        conn.commit()
    return artefacts


_SEQUENCE_HISTORIQUE = (
    ("DISCOVERED", "CANDIDATE"), ("CANDIDATE", "FETCHED"),
    ("FETCHED", "STORED"), ("STORED", "EXTRACTED"),
    ("EXTRACTED", "CLASSIFIED"), ("CLASSIFIED", "RIGHTS_CHECKED"),
    ("RIGHTS_CHECKED", "QUALITY_CHECKED"), ("QUALITY_CHECKED", "ROUTED"),
    ("ROUTED", "STAGED"), ("STAGED", "NEEDS_REVIEW"),
)


def _semer_transitions(
    conn: psycopg.Connection, *, resource_id: object, run_id: object
) -> None:
    """Les dix transitions du chemin scelle, au format historique."""
    for depuis, vers in _SEQUENCE_HISTORIQUE:
        conn.execute(
            "INSERT INTO ingestion_control.workflow_events "
            "  (event_id, run_id, resource_id, event_type, from_state,"
            "   to_state, actor) "
            "VALUES (%s, %s, %s, 'transition', %s, %s, 'acceptance-bench')",
            (uuid.uuid4(), run_id, resource_id, depuis, vers),
        )
    conn.execute(
        "UPDATE ingestion_control.resources "
        "   SET resource_state = 'NEEDS_REVIEW', state_version = 10 "
        " WHERE resource_id = %s", (resource_id,)
    )


def _autorisation_v2(
    profil: object, *, autorisation_id: str, contexte: ContexteDuBanc
) -> object:
    """L'artefact d'autorisation de scope du BANC, au protocole LOT41A-V2.

    C'est le protocole que le publisher exige : une autorisation V1 est
    refusee a l'ecriture produit, et le banc ne doit pas prouver le parcours
    avec une autorite d'un autre regime que celui qui publie. L'artefact est
    SERVI, relu en direct a chaque usage, et lie aux contenus exacts.
    """
    from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2
    from nexus_contracts.document import Rights

    from ingestor.ingestion_profiles.registry import profile_fingerprint

    return ScopeAuthorizationArtifactV2.model_validate({
        "protocol_version": "LOT41A-V2",
        "authorization_id": autorisation_id,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": profil.scope.model_dump(mode="json"),
        "manifest_digest": contexte.digests["profile_manifest_sha256"],
        "profile_id": profil.scope.collection,
        "profile_version": profil.profile_version,
        "profile_fingerprint": profile_fingerprint(profil),
        "allowed_domains": sorted(profil.allowed_domains),
        "rights_categories": [Rights.officiel_public.value],
        "exclusions": [],
        # Liaison au CONTENU : l'autorisation ne couvre que les octets de
        # cette release de banc, nommes un par un.
        "allowed_content_sha256": sorted(
            contenu.content_sha256 for contenu in contexte.contenus
        ),
        "pii_absence_attested": True,
        "pii_absence_evidence": (
            f"acceptance bench PII sha256={contexte.digests['pii_evidence_sha256']}; "
            "CLEARED"
        ),
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2027-09-01T00:00:00Z",
    })


def _enregistrer_autorisation(
    *,
    github: LocalGitHub,
    profil: object,
    autorisation_id: str,
    contexte: ContexteDuBanc,
    numero: int,
    env: Mapping[str, str],
) -> None:
    """Fait enregistrer l'autorisation par le VRAI CLI d'autorite.

    Le banc ne pose pas la ligne en base a la main : il sert l'artefact sur
    sa forge locale, fait approuver la PR de test, et laisse
    ``authorize_scope_cli`` relire, verifier et ecrire. Ce qui est atteste
    est donc ce qui a ete relu, pas ce que le test voulait ecrire.
    """
    from nexus_contracts.authority_artifacts import canonical_authorization_path

    tete = hashlib.sha1(f"auth:{autorisation_id}".encode()).hexdigest()
    github.add_approved_pr(
        number=numero, head_sha=tete, base_sha="9" * 40, review_id=numero + 10
    )
    github.put_blob(
        path=canonical_authorization_path(autorisation_id),
        ref=tete,
        content=_autorisation_v2(
            profil, autorisation_id=autorisation_id, contexte=contexte
        ).canonical_bytes(),
    )
    enregistre = _run(
        "ingestor.ingestion_worker.authorize_scope_cli",
        [
            "record-authorization",
            "--authorization-id", autorisation_id,
            "--repository", REPOSITORY,
            "--pull-request", str(numero),
            "--expected-head", tete,
        ],
        env,
    )
    assert enregistre.returncode == 0, enregistre.stderr


def test_la_projection_et_la_proposition_de_revue_batch(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Maillon 5 — la projection est persistee et l'artefact est produit.

    Le programme fait le travail : le test ne construit ni la projection ni
    l'artefact a sa place.
    """
    # La release est ecrite D'ABORD : ses digests sont ensuite ceux que les
    # lignes scellees declarent. L'inverse ferait refuser le catalogue, et
    # c'est bien ce que la garde doit faire.
    contexte = _contexte_du_banc(tmp_path)
    github, jeton = LocalGitHub(), tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(github) as github_url:
        env = _environnement_d_autorite(control_pg, github_url=github_url, jeton=jeton)
        artefacts = _semer_etat_historique(
            control_pg, contexte=contexte, github=github, env=env
        )
        propose = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_proposition(contexte),
            env,
        )
    assert propose.returncode == 0, propose.stderr
    assert "PROJECTION_PERSISTED" in propose.stdout, propose.stdout
    assert "REVIEW_ARTIFACT_DIGEST" in propose.stdout, propose.stdout

    # Lecture INDEPENDANTE : la projection existe bien en base.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        projetees = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE gate_passed) "
            "  FROM ingestion_control.sealed_release_projections "
            " WHERE release_id = %s", (contexte.release_id,)
        ).fetchone()
        conn.rollback()
    assert projetees == (len(artefacts), len(artefacts)), projetees


def test_l_attestation_batch_est_enregistree_apres_approbation(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Maillon 6 — l'enregistrement apres une revue de TEST approuvee.

    La revue est simulee par ``LocalGitHub`` : c'est une autorite de banc,
    nommee comme telle, qui ne sort jamais de cet environnement isole.
    """
    contexte = _contexte_du_banc(tmp_path)
    github = LocalGitHub()
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    head = hashlib.sha1(b"acceptance-batch-head").hexdigest()
    github.add_approved_pr(
        number=7001, head_sha=head, base_sha="9" * 40, review_id=7011
    )

    with local_github_server(github) as github_url:
        env = _environnement_d_autorite(control_pg, github_url=github_url, jeton=jeton)
        _semer_etat_historique(
            control_pg, contexte=contexte, github=github, env=env
        )
        propose = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_proposition(contexte),
            env,
        )
        assert propose.returncode == 0, propose.stderr
        chemin, octets = _artefact_propose(propose.stdout)
        github.put_blob(path=chemin, ref=head, content=octets)

        enregistre = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_d_enregistrement(contexte, chemin=chemin, head=head),
            env,
        )
    assert enregistre.returncode == 0, enregistre.stderr
    assert "RELEASE_BATCH_ATTESTATIONS_RECORDED" in enregistre.stdout

    # Lecture INDEPENDANTE du plan de controle.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        lignes = conn.execute(
            "SELECT count(*), count(DISTINCT release_batch_review_digest),"
            "       count(*) FILTER (WHERE canonical_url IS NOT NULL),"
            "       count(*) FILTER (WHERE attributed_facts_digest IS NOT NULL)"
            "  FROM ingestion_control.publication_attestations"
            " WHERE protocol_version = 'LOT42-RELEASE-BATCH-V1'"
            "   AND release_id = %s", (contexte.release_id,)
        ).fetchone()
        conn.rollback()
    # Quatre placements, UNE seule revue, aucune URL canonique, aucun digest
    # d'attribution unitaire.
    assert lignes == (4, 1, 0, 0), lignes


def _artefact_propose(sortie: str) -> tuple[str, bytes]:
    """Extrait le chemin et les octets canoniques produits par la proposition."""
    chemin = ""
    for ligne in sortie.splitlines():
        if ligne.startswith("REVIEW_ARTIFACT_PATH "):
            chemin = ligne.split(" ", 1)[1].strip()
    marqueur = sortie.index("{")
    return chemin, sortie[marqueur:].encode("utf-8")


def test_l_attestation_batch_se_verifie_a_l_usage(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Maillon 7 — le consommateur canonique accepte l'attestation batch.

    C'est la contradiction que l'audit initial avait localisee :
    ``verify_publication_attestation`` exigeait inconditionnellement un
    digest d'attribution unitaire, que le schema INTERDIT au batch. Une
    attestation conforme au schema etait donc inverifiable.
    """
    from ingestor.ingestion_control.publication_attestation import (
        PublicationAttestationInvalidError,
        verify_publication_attestation,
    )

    prepare = _preparer_attestation(control_pg, tmp_path)
    github, jeton = prepare["github"], prepare["jeton"]
    banc: ContexteDuBanc = prepare["contexte"]

    with local_github_server(github) as github_url:
        env = {
            "NEXUS_GITHUB_API_BASE": github_url,
            "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
        }
        anciens = {cle: os.environ.get(cle) for cle in env}
        os.environ.update(env)
        try:
            with psycopg.connect(app_dsn(control_pg)) as conn:
                verifiees = []
                for entree in prepare["artefacts"]:
                    verifiee = verify_publication_attestation(
                        conn,
                        resource_id=entree["resource_id"],
                        current_content_sha256=entree["content_sha256"],
                        current_profile_fingerprint=banc.digests["artifacts_release_sha256"],
                        current_manifest_digest=banc.digests["release_manifest_sha256"],
                    )
                    verifiees.append(verifiee)
                conn.rollback()
            assert len(verifiees) == 4
            assert {v.protocol_version for v in verifiees} == {
                "LOT42-RELEASE-BATCH-V1"
            }
            # Le digest d'attribution UNITAIRE reste absent, et son absence
            # est dite — jamais confondue avec « non verifie ».
            assert {v.attributed_facts_digest for v in verifiees} == {""}
            assert len({v.attestation_digest for v in verifiees}) == 1

            # CONTRE-EPREUVE : une ressource hors du perimetre approuve.
            with psycopg.connect(app_dsn(control_pg)) as conn:
                etrangere = uuid.uuid4()
                with pytest.raises(PublicationAttestationInvalidError):
                    verify_publication_attestation(
                        conn, resource_id=etrangere,
                        current_content_sha256="0" * 64,
                        current_profile_fingerprint=banc.digests["artifacts_release_sha256"],
                        current_manifest_digest=banc.digests["release_manifest_sha256"],
                    )
                conn.rollback()

            # CONTRE-EPREUVE : un contenu observe different de l'atteste.
            with psycopg.connect(app_dsn(control_pg)) as conn:
                with pytest.raises(PublicationAttestationInvalidError):
                    verify_publication_attestation(
                        conn,
                        resource_id=prepare["artefacts"][0]["resource_id"],
                        current_content_sha256="0" * 64,
                        current_profile_fingerprint=banc.digests["artifacts_release_sha256"],
                        current_manifest_digest=banc.digests["release_manifest_sha256"],
                    )
                conn.rollback()
        finally:
            for cle, valeur in anciens.items():
                if valeur is None:
                    os.environ.pop(cle, None)
                else:
                    os.environ[cle] = valeur


def _environnement_d_autorite(
    control_pg: dict[str, str], *, github_url: str, jeton: Path
) -> dict[str, str]:
    """Les DSN d'autorite et d'attestation, et la forge locale du banc.

    Chaque outil recoit le role prevu pour lui : l'autorite enregistre les
    autorisations, l'attestor projette et atteste. Aucun des deux n'est le
    superutilisateur.
    """
    from _pg_authority import authority_dsn

    return {
        "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg),
        "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
        "NEXUS_GITHUB_API_BASE": github_url,
        "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
    }


def _arguments_de_proposition(contexte: ContexteDuBanc) -> list[str]:
    """La proposition de revue batch, adressee aux autorites du banc."""
    return [
        "propose-release-batch-review",
        "--release-id", contexte.release_id,
        "--release-dir", str(contexte.racine),
        "--release-manifest-sha256", contexte.digests["release_manifest_sha256"],
        "--transfer-manifest-path", str(contexte.manifeste_de_transfert),
        "--transfer-manifest-sha256",
        contexte.digests["artifact_transfer_manifest_sha256"],
        "--rights-registry-path", str(contexte.registre_de_droits),
        "--review-id", REVUE_DE_TEST,
        "--evaluator", "acceptance-bench",
    ]


def _arguments_d_enregistrement(
    contexte: ContexteDuBanc, *, chemin: str, head: str
) -> list[str]:
    """L'enregistrement apres approbation, au head exact de la revue."""
    return [
        "record-release-batch-attestation",
        "--release-id", contexte.release_id,
        "--review-id", REVUE_DE_TEST,
        "--repository", REPOSITORY,
        "--pull-request", "7001",
        "--expected-head", head,
        "--review-artifact-path", chemin,
    ]


def _preparer_attestation(
    control_pg: dict[str, str], tmp_path: Path
) -> dict[str, object]:
    """Amene le banc jusqu'a des attestations batch enregistrees."""
    contexte = _contexte_du_banc(tmp_path)
    github = LocalGitHub()
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    head = hashlib.sha1(b"acceptance-batch-head").hexdigest()
    github.add_approved_pr(
        number=7001, head_sha=head, base_sha="9" * 40, review_id=7011
    )
    with local_github_server(github) as github_url:
        env = _environnement_d_autorite(control_pg, github_url=github_url, jeton=jeton)
        artefacts = _semer_etat_historique(
            control_pg, contexte=contexte, github=github, env=env
        )
        propose = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_proposition(contexte),
            env,
        )
        assert propose.returncode == 0, propose.stderr
        chemin, octets = _artefact_propose(propose.stdout)
        github.put_blob(path=chemin, ref=head, content=octets)
        enregistre = _run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_d_enregistrement(contexte, chemin=chemin, head=head),
            env,
        )
        assert enregistre.returncode == 0, enregistre.stderr
    return {
        "github": github, "jeton": jeton, "head": head,
        "contexte": contexte, "artefacts": artefacts,
    }


def test_un_job_batch_sans_artefact_nomme_est_refuse(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Contre-epreuve A/B — aucune substitution vers « le plus recent ».

    Une SECONDE version d'artefact existe pour la ressource. Le traitement
    doit utiliser celle que le job nomme, ou refuser ; jamais retenir la
    plus recente parce qu'elle arrive en tete d'une requete ordonnee.
    """
    from ingestor.ingestion_control.provisioning import (
        SEALED_RELEASE_PIPELINE,
        find_authorised_artifact,
        find_latest_artifact,
        persist_sealed_release_artifact,
    )

    contexte = _preparer_attestation(control_pg, tmp_path)
    premier = contexte["artefacts"][0]
    resource_id = premier["resource_id"]
    autorise = premier["artifact_id"]

    # B : des octets DIFFERENTS, donc un SHA different — sinon la contrainte
    # (resource_id, sha256) empecherait la seconde ligne d'exister, et le
    # test porterait sur deux versions dont une seule est reelle.
    octets_b = b"%PDF-1.7\n% version B, non couverte par la revue\n"
    sha_b = hashlib.sha256(octets_b).hexdigest()
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        run_id = conn.execute(
            "SELECT run_id FROM ingestion_control.resources WHERE resource_id = %s",
            (resource_id,),
        ).fetchone()[0]
        payload = dict(conn.execute(
            "SELECT payload FROM ingestion_control.artifacts "
            " WHERE artifact_id = %s", (autorise,)
        ).fetchone()[0])
        payload["content_sha256"] = sha_b
        plus_recent = persist_sealed_release_artifact(
            conn, resource_id=resource_id, run_id=run_id,
            sha256=sha_b, size_bytes=len(octets_b),
            mime_declared="application/pdf", mime_detected="application/pdf",
            provenance_url=payload["provenance_artifact_url"], payload=payload,
        )
        # Une date de collecte explicitement POSTERIEURE : « plus recent »
        # doit etre un fait, pas une supposition sur l'ordre d'insertion.
        conn.execute(
            "UPDATE ingestion_control.artifacts "
            "   SET collected_at = now() + interval '1 hour' "
            " WHERE artifact_id = %s", (plus_recent,)
        )
        conn.commit()
    assert plus_recent != autorise

    # Les DEUX lignes existent reellement pour cette ressource.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        presentes = conn.execute(
            "SELECT artifact_id FROM ingestion_control.artifacts "
            " WHERE resource_id = %s ORDER BY collected_at", (resource_id,)
        ).fetchall()
        conn.rollback()
    assert {ligne[0] for ligne in presentes} == {autorise, plus_recent}, presentes

    with psycopg.connect(app_dsn(control_pg)) as conn:
        # « le plus recent » rend bien B — et B n'est PAS ce que la revue a
        # couvert. C'est exactement le piege que la selection par identite
        # ferme.
        dernier = find_latest_artifact(
            conn, resource_id=resource_id, sealed_catalog=_CatalogueMuet()
        )
        assert dernier is not None
        assert dernier.artifact_id == plus_recent, (
            "la version la plus recente doit bien etre B"
        )

        # La selection par IDENTITE rend A, celui que la revue a couvert —
        # de maniere DETERMINISTE, quelle que soit l'autre version.
        choisi = find_authorised_artifact(
            conn, resource_id=resource_id, artifact_id=autorise,
            sealed_catalog=_CatalogueMuet(),
        )
        assert choisi.artifact_id == autorise

        # Un identifiant d'une AUTRE ressource est un refus.
        from ingestor.ingestion_control.provisioning import SealedReleaseRowError

        autre = contexte["artefacts"][2]["resource_id"]
        with pytest.raises(SealedReleaseRowError, match="does not belong"):
            find_authorised_artifact(
                conn, resource_id=autre, artifact_id=autorise,
                sealed_catalog=_CatalogueMuet(),
            )
        conn.rollback()

    # Et le discriminateur durable exige bien l'identite pour ce pipeline.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        kind = conn.execute(
            "SELECT pipeline_kind FROM ingestion_control.resources "
            " WHERE resource_id = %s", (resource_id,)
        ).fetchone()
        conn.rollback()
    assert kind == (SEALED_RELEASE_PIPELINE,)


class _CatalogueMuet:
    """Catalogue minimal du banc : il ne decide rien, il rend ce qu'on lui a
    donne. Les refus testes ici portent sur la SELECTION, pas sur lui."""

    def entry(self, *, content_sha256: str) -> dict[str, object]:
        return {"content_sha256": content_sha256, "page_count": 3,
                "title": None, "source_url": None}

    def resolve_rights(self, *, content_sha256: str) -> tuple[str, str, str]:
        return ("officiel_public", "acceptance_approval", "a" * 64)

    def media_type(self, *, content_sha256: str) -> str:
        return "application/pdf"


def test_les_jobs_batch_nomment_leur_artefact(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    """Maillon 8 — les jobs sont crees depuis les attestations ENREGISTREES.

    Chaque job batch nomme l'artefact qu'il publie. Le producteur derive
    cette identite des attestations reellement ecrites, jamais d'un choix
    libre.
    """
    from ingestor.ingestion_control.jobs import create_job

    contexte = _preparer_attestation(control_pg, tmp_path)

    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        attestations = conn.execute(
            "SELECT a.resource_id, a.artifact_id, a.attestation_id, r.run_id,"
            "       r.state_version"
            "  FROM ingestion_control.publication_attestations a"
            "  JOIN ingestion_control.resources r USING (resource_id)"
            " WHERE a.protocol_version = 'LOT42-RELEASE-BATCH-V1'"
            "   AND a.release_id = %s AND a.invalidated_at IS NULL"
            " ORDER BY a.resource_id", (contexte["contexte"].release_id,)
        ).fetchall()
        assert len(attestations) == 4, attestations
        jobs = []
        for resource_id, artifact_id, attestation_id, run_id, version in attestations:
            jobs.append(create_job(
                conn, run_id=run_id, resource_id=resource_id,
                job_type="publication_resume",
                payload={
                    "resource_id": str(resource_id),
                    "run_id": str(run_id),
                    "expected_state_version": version,
                    "publication_attestation_id": str(attestation_id),
                    # L'identite EXACTE : le batch l'exige, et le
                    # discriminateur durable fait appliquer cette exigence.
                    "artifact_id": str(artifact_id),
                },
            ))
        conn.commit()
    assert len(jobs) == 4

    # Lecture INDEPENDANTE : chaque job nomme bien son artefact.
    with psycopg.connect(app_dsn(control_pg)) as conn:
        nommes = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE payload ? 'artifact_id')"
            "  FROM ingestion_control.jobs"
            " WHERE job_id = ANY(%s) AND status = 'queued'", (jobs,)
        ).fetchone()
        conn.rollback()
    assert nommes == (4, 4), nommes

    # Ces jobs ont prouve ce qu'ils devaient prouver — que le PRODUCTEUR
    # nomme l'artefact. Les laisser en file ferait reclamer a un worker
    # d'un autre test des jobs d'une AUTRE release : il les refuserait, a
    # raison, et le refus masquerait ce que ce module veut montrer. La file
    # du banc est partagee ; elle est donc rendue propre ici.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        conn.execute(
            "DELETE FROM ingestion_control.jobs WHERE job_id = ANY(%s)", (jobs,)
        )
        conn.commit()


def _jobs_depuis_les_attestations(
    control_pg: dict[str, str], contexte: ContexteDuBanc
) -> list[uuid.UUID]:
    """Les jobs batch, derives des attestations REELLEMENT ecrites.

    L'identite de l'artefact n'est pas choisie : elle est relue sur
    l'attestation qui le couvre.
    """
    from ingestor.ingestion_control.jobs import create_job

    jobs: list[uuid.UUID] = []
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        attestations = conn.execute(
            "SELECT a.resource_id, a.artifact_id, a.attestation_id, r.run_id,"
            "       r.state_version"
            "  FROM ingestion_control.publication_attestations a"
            "  JOIN ingestion_control.resources r USING (resource_id)"
            " WHERE a.protocol_version = 'LOT42-RELEASE-BATCH-V1'"
            "   AND a.release_id = %s AND a.invalidated_at IS NULL"
            " ORDER BY a.resource_id",
            (contexte.release_id,),
        ).fetchall()
        assert len(attestations) == 4, attestations
        for resource_id, artifact_id, attestation_id, run_id, version in attestations:
            jobs.append(create_job(
                conn, run_id=run_id, resource_id=resource_id,
                job_type="publication_resume",
                payload={
                    "resource_id": str(resource_id),
                    "run_id": str(run_id),
                    "expected_state_version": version,
                    "publication_attestation_id": str(attestation_id),
                    "artifact_id": str(artifact_id),
                },
            ))
        conn.commit()
    return jobs


def _environnement_de_worker(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    *,
    contexte: ContexteDuBanc,
    github_url: str,
    jeton: Path,
    tmp_path: Path,
) -> dict[str, str]:
    """L'environnement REEL de Worker B : readiness signee, DSN separes."""
    from _pg_authority import authority_dsn

    return {
        **environnement_de_readiness(
            tmp_path, corpus_manifest_sha256=contexte.digests["corpus_manifest_sha256"]
        ),
        "NEXUS_GITHUB_API_BASE": github_url,
        "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
        # Les ROLES OPERATIONNELS : le superutilisateur ne sert qu'a preparer
        # et a relire la base jetable, jamais a demontrer un privilege.
        "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg),
        "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
        "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg),
        "PG_RAG_DSN": product_pg["publisher_dsn"],
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": "",
    }


def _arguments_de_worker_b(contexte: ContexteDuBanc, *, iterations: int) -> list[str]:
    """Les arguments du VRAI CLI de Worker B, autorites comprises."""
    return [
        "--profiles-dir", str(PROFILS_DIR),
        "--artifact-store-dir", str(contexte.magasin),
        "--owner", "banc-worker-b",
        "--expected-role", "ingestion_control_app",
        "--embedding-artifact-root", str(contexte.modele_e5),
        "--embedding-inventory-sha256", contexte.e5_inventaire_sha256,
        "--max-iterations", str(iterations),
        *contexte.arguments_d_autorites(),
    ]


def _lancer_worker_b(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    *,
    banc: ContexteDuBanc,
    github: LocalGitHub,
    jeton: Path,
    tmp_path: Path,
    iterations: int = 4,
    autorites: ContexteDuBanc | None = None,
) -> subprocess.CompletedProcess[str]:
    """Lance le VRAI CLI de Worker B, forge locale ouverte.

    ``autorites`` permet de le lancer avec le jeu d'autorites d'une AUTRE
    release que celle dont les jobs sont en file — c'est ce que la
    contre-epreuve de mauvaise release exige.
    """
    with local_github_server(github) as github_url:
        return _run(
            "ingestor.ingestion_worker.multilevel_publication_resume_cli",
            _arguments_de_worker_b(autorites or banc, iterations=iterations),
            _environnement_de_worker(
                control_pg, product_pg, contexte=banc,
                github_url=github_url, jeton=jeton, tmp_path=tmp_path,
            ),
            timeout=2400,
        )


def _publier_le_banc(
    control_pg: dict[str, str], product_pg: dict[str, str], tmp_path: Path
) -> tuple[dict[str, object], ContexteDuBanc, list[uuid.UUID], subprocess.CompletedProcess[str]]:
    """Le parcours complet jusqu'a la publication produit, une seule fois."""
    prepare = _preparer_attestation(control_pg, tmp_path)
    banc: ContexteDuBanc = prepare["contexte"]
    jobs = _jobs_depuis_les_attestations(control_pg, banc)
    worker = _lancer_worker_b(
        control_pg, product_pg, banc=banc,
        github=prepare["github"], jeton=prepare["jeton"], tmp_path=tmp_path,
    )
    return prepare, banc, jobs, worker


def _compter_dans_le_produit(
    product_pg: dict[str, str], contenus: list[str]
) -> tuple[int, int, int]:
    """Artefacts, placements et chunks publies pour ces contenus."""
    with psycopg.connect(product_pg["admin_dsn"]) as conn:
        comptes = conn.execute(
            "SELECT (SELECT count(*) FROM public.rag_artifacts"
            "          WHERE artifact_id = ANY(%s)),"
            "       (SELECT count(*) FROM public.rag_artifact_placements"
            "          WHERE artifact_id = ANY(%s)),"
            "       (SELECT count(*) FROM public.rag_chunks"
            "          WHERE artifact_id = ANY(%s))",
            (contenus, contenus, contenus),
        ).fetchone()
        conn.rollback()
    assert comptes is not None
    return comptes


def test_le_parcours_batch_atteint_l_index_produit(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
) -> None:
    """Maillon final — la publication dans l'index produit, puis le retrieval.

    Le CLI de Worker B est lance REELLEMENT : il charge ses autorites,
    construit ses dependances, lit les octets scelles, embarque et publie.
    Aucun lecteur, verificateur ou publisher n'est remplace par un resultat
    prepare, et un code de sortie nul ne suffit pas : ce qui suit est relu
    independamment, dans les deux bases.
    """
    prepare, banc, jobs, worker = _publier_le_banc(control_pg, product_pg, tmp_path)
    assert len(jobs) == 4
    assert worker.returncode == 0, worker.stderr
    assert worker.stdout.count("status=succeeded") == 4, (
        worker.stdout + "\n" + worker.stderr
    )
    # La sortie du worker est la trace de ce qui s'est reellement passe :
    # elle est conservee telle quelle, visible avec `pytest -s`.
    print(worker.stdout)

    # ── Lecture INDEPENDANTE du plan de controle ──────────────────────────
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        etats = conn.execute(
            "SELECT count(*) FROM ingestion_control.resources r"
            "  JOIN ingestion_control.publication_attestations a USING (resource_id)"
            " WHERE a.release_id = %s AND r.resource_state = 'RETRIEVAL_ELIGIBLE'",
            (banc.release_id,),
        ).fetchone()
        traites = conn.execute(
            "SELECT count(*) FROM ingestion_control.jobs"
            " WHERE job_id = ANY(%s) AND status = 'succeeded'", (jobs,)
        ).fetchone()
        conn.rollback()
    assert etats == (4,), etats
    assert traites == (4,), traites

    # ── Lecture INDEPENDANTE de la base PRODUIT ───────────────────────────
    contenus = sorted(contenu.content_sha256 for contenu in banc.contenus)
    with psycopg.connect(product_pg["admin_dsn"]) as conn:
        artefacts = conn.execute(
            "SELECT artifact_id, rights, type_doc, official, source_kind, source_uri"
            "  FROM public.rag_artifacts WHERE artifact_id = ANY(%s)"
            " ORDER BY artifact_id", (contenus,)
        ).fetchall()
        placements = conn.execute(
            "SELECT collection, artifact_id, placement_status, currentness,"
            "       review_status, source_path, source_uri"
            "  FROM public.rag_artifact_placements WHERE artifact_id = ANY(%s)"
            " ORDER BY collection, artifact_id", (contenus,)
        ).fetchall()
        chunks = conn.execute(
            "SELECT count(*), count(DISTINCT artifact_id),"
            "       count(*) FILTER (WHERE vector IS NULL"
            "                          OR vector_dims(vector) <> 1024"
            "                          OR model <> %s OR btrim(text) = '')"
            "  FROM public.rag_chunks WHERE artifact_id = ANY(%s)",
            ("intfloat/multilingual-e5-large", contenus),
        ).fetchone()
        conn.rollback()

    # L'artefact EXACT, ses droits, son type documentaire et sa provenance.
    assert [ligne[0] for ligne in artefacts] == contenus, artefacts
    assert {ligne[1] for ligne in artefacts} == {"officiel_public"}, artefacts
    assert {ligne[2] for ligne in artefacts} == {banc.type_doc}, artefacts
    assert {ligne[3] for ligne in artefacts} == {True}, artefacts
    assert {ligne[4] for ligne in artefacts} == {"sealed_release"}, artefacts
    urls = {contenu.url_telechargement for contenu in banc.contenus}
    assert {ligne[5] for ligne in artefacts} == urls, artefacts

    # QUATRE placements : deux contenus, chacun dans DEUX collections.
    assert len(placements) == 4, placements
    assert {ligne[0] for ligne in placements} == set(banc.collections), placements
    assert {(ligne[2], ligne[3], ligne[4]) for ligne in placements} == {
        ("active", "current", "reviewed")
    }, placements
    chemins = {contenu.chemin_physique for contenu in banc.contenus}
    assert {ligne[5] for ligne in placements} == chemins, placements

    # Les chunks : embarques par le VRAI modele, en dimension canonique.
    assert chunks[0] > 0, chunks
    assert chunks[1] == len(contenus), chunks
    assert chunks[2] == 0, chunks

    # ── Le contenu est effectivement RECUPERE par le retrieval ────────────
    trouves = _recuperer_par_le_retrieval(product_pg, banc)
    assert trouves, "aucun chunk publie n'a ete retrouve par le chemin de retrieval"
    # L'identite rendue est celle d'un artefact du banc, et le TEXTE rendu
    # est celui qui a ete reellement extrait des octets publies.
    assert {candidat.artifact_id for candidat in trouves} <= set(contenus), trouves
    assert any("algorithmique" in candidat.text for candidat in trouves), trouves
    # L'ATTRIBUTION documentaire est conservee jusqu'au resultat expose :
    # ce que le retrieval rend porte les faits que l'attestation a scelles,
    # pas une valeur recomposee a l'affichage.
    assert {candidat.type_doc for candidat in trouves} == {banc.type_doc}, trouves
    assert {candidat.rights for candidat in trouves} == {"officiel_public"}, trouves
    assert {candidat.source_label for candidat in trouves} == {
        "eduscol.education.gouv.fr"
    }, trouves
    assert {candidat.source_uri for candidat in trouves} <= urls, trouves
    assert {candidat.placement_source_path for candidat in trouves} <= chemins, trouves


def _recuperer_par_le_retrieval(
    product_pg: dict[str, str], contexte: ContexteDuBanc
) -> list[Any]:
    """Interroge la base produit par le CHEMIN DE RETRIEVAL reel.

    Identite interne signee, scope serveur derive du catalogue gouverne,
    puis le store pgvector : ce sont les predicats d'acces reels — autorite
    de placement, droits, lisibilite — qui decident, pas une requete ecrite
    pour ce test.
    """
    import base64
    import hmac
    import time

    from _banc_multiniveaux import CONFIG_COLLECTIONS

    from ingestor.collection_config import load_collection_config
    from ingestor.identity_v2 import (
        load_identity_verifier_config,
        verify_identity_token,
    )
    from ingestor.retrieval_pg_v2 import PgCandidateStore
    from ingestor.retrieval_scope_v2 import build_server_retrieval_scope

    collection = "rag_nexus_nsi_terminale_specialite"
    secret = "banc-multiniveaux-internal-secret-32-bytes"
    variables = {
        "NEXUS_INTERNAL_TOKEN_SECRET": secret,
        "NEXUS_INTERNAL_TOKEN_ISSUER": "banc-cockpit",
        "NEXUS_INTERNAL_TOKEN_AUDIENCE": "banc-engine",
        "NEXUS_SSO_ISSUER": "banc-sso",
        "NEXUS_SSO_AUDIENCE": "banc-cockpit-audience",
    }
    anciens = {cle: os.environ.get(cle) for cle in variables}
    os.environ.update(variables)
    try:
        config = load_identity_verifier_config()
        artefact = config.artifact
        maintenant = int(time.time())
        identite = {
            "aud": variables["NEXUS_SSO_AUDIENCE"],
            "exp": maintenant + 600,
            "iss": variables["NEXUS_SSO_ISSUER"],
            "jti": "banc-multiniveaux-jti",
            "tenant": "libre_terminale",
            "niveau": "terminale",
            "role": "admin",
            "school_year": "2026-2027",
            "sub": "psn_bancmultiniveaux0001",
            "pedagogical_profile": {
                "voie": "generale",
                "matieres": ["nsi"],
                "statut_enseignement": "specialite",
                "candidat": "libre",
                "audience": "libre",
            },
        }
        charge = {
            "protocol_version": "1",
            "iss": variables["NEXUS_INTERNAL_TOKEN_ISSUER"],
            "aud": variables["NEXUS_INTERNAL_TOKEN_AUDIENCE"],
            "sub": identite["sub"],
            "jti": identite["jti"],
            "iat": maintenant,
            "exp": maintenant + 300,
            "identity": identite,
            "scope_id": artefact.scope_id,
            "scope_digest": artefact.sha256_digest(),
            "allowed_collections": [
                sujet.collection for sujet in artefact.subjects
            ],
        }

        def _b64(valeur: bytes) -> str:
            return base64.urlsafe_b64encode(valeur).rstrip(b"=").decode("ascii")

        entete = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        corps = _b64(json.dumps(charge).encode())
        signature = hmac.new(
            secret.encode(), f"{entete}.{corps}".encode("ascii"), hashlib.sha256
        ).digest()
        jeton = f"{entete}.{corps}.{_b64(signature)}"

        verifiee = verify_identity_token(jeton, config=config)
        scope = build_server_retrieval_scope(
            verifiee,
            collection=collection,
            collection_config=load_collection_config(CONFIG_COLLECTIONS),
        )
        store = PgCandidateStore(
            lambda: psycopg.connect(product_pg["retrieval_dsn"]), scope
        )
        candidats = store.lexical(
            raw_query="programme officiel NSI algorithmique",
            collection=collection,
            limit=10,
        )
        return list(candidats)
    finally:
        for cle, valeur in anciens.items():
            if valeur is None:
                os.environ.pop(cle, None)
            else:
                os.environ[cle] = valeur


def test_une_reprise_apres_ecriture_produit_ne_duplique_rien(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
) -> None:
    """Interruption APRES l'ecriture produit, AVANT l'acquittement du job.

    C'est le cas qui distingue une reprise correcte d'une republication :
    la base produit porte deja tout, la ressource est deja
    ``RETRIEVAL_ELIGIBLE``, et le job — toujours en file, car son bail est
    tombe — doit etre repris SANS rien dupliquer ni rien reecrire.

    Le job rejoue est le MEME : c'est ce que fait un bail expire apres un
    arret brutal. Un job neuf n'aurait pas les evenements de promotion qui
    le nomment, et serait refuse — a raison.
    """
    prepare, banc, jobs, worker = _publier_le_banc(control_pg, product_pg, tmp_path)
    assert worker.stdout.count("status=succeeded") == 4, worker.stdout + worker.stderr
    contenus = sorted(contenu.content_sha256 for contenu in banc.contenus)
    avant = _compter_dans_le_produit(product_pg, contenus)
    assert avant[0] == 2 and avant[1] == 4 and avant[2] > 0, avant

    # L'interruption : le worker s'arrete entre l'ecriture produit et
    # l'acquittement. Le bail tombe, le job redevient reclamable.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        remis = conn.execute(
            "UPDATE ingestion_control.jobs"
            "   SET status = 'queued', lease_token = NULL,"
            "       lease_expires_at = NULL, claimed_by = NULL"
            " WHERE job_id = ANY(%s) RETURNING job_id", (jobs,)
        ).fetchall()
        conn.commit()
    assert len(remis) == 4, remis

    repris = _lancer_worker_b(
        control_pg, product_pg, banc=banc,
        github=prepare["github"], jeton=prepare["jeton"], tmp_path=tmp_path,
    )
    assert repris.returncode == 0, repris.stderr
    assert repris.stdout.count("status=succeeded") == 4, (
        repris.stdout + "\n" + repris.stderr
    )

    # RIEN n'a ete duplique : ni artefact, ni placement, ni chunk.
    apres = _compter_dans_le_produit(product_pg, contenus)
    assert apres == avant, (avant, apres)

    # Et les jobs sont acquittes, une seule fois chacun.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        etats = conn.execute(
            "SELECT status, count(*) FROM ingestion_control.jobs"
            " WHERE job_id = ANY(%s) GROUP BY status", (jobs,)
        ).fetchall()
        conn.rollback()
    assert etats == [("succeeded", 4)], etats


def test_un_worker_porteur_d_une_autre_release_ne_publie_rien(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
) -> None:
    """Mauvaise release : aucune publication, et le refus est nomme.

    Les jobs sont ceux d'une release reellement attestee. Le worker, lui,
    porte le jeu d'autorites d'une AUTRE release — coherent avec lui-meme,
    mais etranger a ces contenus. Publier « parce que tout le reste va
    bien » serait exactement la faute que la liaison de release ferme.
    """
    prepare = _preparer_attestation(control_pg, tmp_path)
    banc: ContexteDuBanc = prepare["contexte"]
    jobs = _jobs_depuis_les_attestations(control_pg, banc)
    assert len(jobs) == 4

    # Une SECONDE release de banc, coherente et complete, mais qui ne
    # contient pas les contenus de la premiere.
    etrangere = _contexte_du_banc(tmp_path / "autre")
    assert etrangere.release_id != banc.release_id
    contenus = sorted(contenu.content_sha256 for contenu in banc.contenus)
    assert not set(contenus) & {
        contenu.content_sha256 for contenu in etrangere.contenus
    }

    worker = _lancer_worker_b(
        control_pg, product_pg, banc=banc, autorites=etrangere,
        github=prepare["github"], jeton=prepare["jeton"], tmp_path=tmp_path,
    )
    assert worker.returncode == 0, worker.stderr
    assert "status=succeeded" not in worker.stdout, worker.stdout
    assert "is not part of the sealed release" in worker.stderr, worker.stderr

    # Rien n'a ete ecrit dans le produit, et aucune ressource n'a bouge.
    assert _compter_dans_le_produit(product_pg, contenus) == (0, 0, 0)
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        etats = conn.execute(
            "SELECT DISTINCT r.resource_state"
            "  FROM ingestion_control.resources r"
            "  JOIN ingestion_control.publication_attestations a USING (resource_id)"
            " WHERE a.release_id = %s", (banc.release_id,)
        ).fetchall()
        conn.rollback()
    assert etats == [("NEEDS_REVIEW",)], etats

    # La file est rendue propre : ces jobs ont prouve leur refus.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        conn.execute(
            "DELETE FROM ingestion_control.jobs WHERE job_id = ANY(%s)", (jobs,)
        )
        conn.commit()
