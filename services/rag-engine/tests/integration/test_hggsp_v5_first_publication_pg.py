"""Décision B HGGSP — première publication V5 sur un produit sans HGGSP.

État initial reproduit (PostgreSQL jetables, schéma de contrôle 020 et
schéma produit réels) :

* contrôle : 74 ressources, artefacts, attestations actives et jobs V4 HGGSP,
  jobs **en file, jamais exécutés** ;
* produit : les 405 placements V4 NON-HGGSP déjà servis, **zéro** placement
  HGGSP (dernier relevé opérateur, historique : ``PLACEMENTS=9 263 405``,
  ``CHUNKS=5678``, ``HGGSP=0``).

Chaîne V5, par les vrais CLI et rôles : adoption V2, liaison des autorités,
proposition de revue batch, approbation sur la forge du banc,
``record-release-batch-attestation``, mise en file par l'outil de staging.

Worker B, deux fois :

1. le **vrai CLI en sous-processus**, tel que le staging le lancera : il
   refuse de démarrer (défaut 1 ci-dessous), sans rien écrire ;
2. le **même ``main()``, en processus**, sous les deux seules corrections
   minimales proposées (``_correctif_de_demarrage_propose``), appliquées par
   le banc et JAMAIS livrées par ce lot : claim release-bound, vérifications
   live, promotion, publisher gouverné et E5 restent ceux du dépôt. Puis un
   rejeu.

Défauts constatés (reproduits sans Docker dans
``tests/test_hggsp_v5_runtime_blockers.py``) :

* défaut 1 — ``from_authorities`` exige une taxonomie scellée pour chacun
  des 11 profils du registre ; le registre de programmes de V5 n'en porte
  que 2 ;
* défaut 2 — une ressource successeur V2 naît à ``state_version=0`` ;
  ``_require_payload`` prend ce 0 pour une absence.

Ce qui est simulé, et seulement cela :

* la forge GitHub (``LocalGitHub``) et les autorisations r4 V5 de banc ;
* les lignes V4 initiales du contrôle (``_seed_v4(served=False)``) ;
* l'état produit V4 non-HGGSP : identités scellées réelles (artefacts,
  placements, chunks), mais texte et vecteurs de chunks **synthétiques** —
  ils ne servent qu'à mesurer leur conservation ;
* la readiness de staging, signée par une clé de banc ;
* le manifeste de transfert, dérivé de celui de V2 et restreint aux 52
  objets du catalogue V5.

Rien du résultat V5 n'est inséré par le banc : les lignes produit HGGSP sont
écrites par le publisher seul. Les embeddings V5 sont calculés par le modèle
E5 réel désigné par ``RAG_EMBEDDING_MODEL_CACHE_DIR`` (vérifié par son
inventaire) ; les PDF sont relus depuis ``NEXUS_REAL_RELEASE_ARTIFACT_MIRRORS``
et rehachés. Opt-in : ``NEXUS_HGGSP_V5_PRODUCT_BENCH=1``.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

if os.environ.get("NEXUS_HGGSP_V5_PRODUCT_BENCH") != "1":
    pytest.skip("banc produit HGGSP V5 non demandé (NEXUS_HGGSP_V5_PRODUCT_BENCH=1)",
                allow_module_level=True)

from _banc_releases_reelles import (  # noqa: E402
    MODELE_E5_ENV,
    PROFILE_MANIFEST_V4,
    PROFILES_V4,
    REPOSITORY_ROOT,
    V4_DIR,
    V4_ID,
    acces_github,
    arguments_d_enregistrement,
    arguments_de_proposition,
    arguments_worker_b,
    artefact_propose,
    enregistrer,
    erreurs_d_iteration,
    lancer_worker_b,
    magasin_reel,
    readiness,
    refus_au_demarrage,
    run,
    sha,
    transfert_nomme,
)
from _local_github import VALID_TOKEN, LocalGitHub, local_github_server  # noqa: E402
from _pg_authority import (  # noqa: E402
    adopter_dsn,
    app_dsn,
    attestor_dsn,
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    start_rag_product_postgres,
    superuser_dsn,
)
from test_hggsp_successor_attestation_coexistence_pg import (  # noqa: E402
    CLI,
    COLLECTIONS,
    V5_DIR,
    V5_ID,
    _facts,
    _r4_documents,
    _seed_v4,
    _snapshot_v4_attestations_and_jobs,
    _snapshot_v4_control,
)

pytestmark = [pytest.mark.integration, requires_docker]

MANIFESTE = "production-profile-gate.release.json"
ENQUEUE = "scripts.go_live.staging_v4_enqueue_publication"
SUBJECTS_MAPPING_V5 = "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml"


# ── autorités scellées : cibles recalculées, jamais recopiées ────────────────


def _sealed(release_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(catalogue d'artefacts par SHA, placements) d'une release scellée."""
    manifest = json.loads((release_dir / MANIFESTE).read_bytes())
    catalog = {
        entry["content_sha256"]: entry
        for entry in json.loads((release_dir / "artifacts.release.json").read_bytes())["artifacts"]
    }
    placements = [
        placement
        for subject in manifest["subjects"]
        for placement in json.loads((release_dir / subject["path"]).read_bytes())["placements"]
    ]
    return catalog, placements


def _cardinalities(catalog: dict[str, Any], placements: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    contents = {p["artifact_id"] for p in placements}
    chunks = {c["chunk_id"] for sha in contents for c in catalog[sha]["chunks"]}
    return len({p["collection"] for p in placements}), len(contents), len(placements), len(chunks)


V4_CATALOG, V4_PLACEMENTS = _sealed(V4_DIR)
V5_CATALOG, V5_PLACEMENTS = _sealed(V5_DIR)
V4_NON_HGGSP = [p for p in V4_PLACEMENTS if p["collection"] not in COLLECTIONS]


def test_les_cibles_se_recalculent_depuis_les_autorites_scellees() -> None:
    v4_hggsp = [p for p in V4_PLACEMENTS if p["collection"] in COLLECTIONS]
    assert _cardinalities(V4_CATALOG, V4_NON_HGGSP) == (9, 263, 405, 5678)
    assert _cardinalities(V5_CATALOG, V5_PLACEMENTS) == (2, 52, 74, 2590)
    assert _cardinalities(V4_CATALOG, [*V4_NON_HGGSP, *V5_PLACEMENTS]) == (11, 315, 479, 8268)
    # Aucun contenu ni chunk commun : HGGSP V5 ne peut heurter aucune ligne
    # produit V4 non-HGGSP par son artefact ou ses chunks.
    assert not {p["artifact_id"] for p in V4_NON_HGGSP} & {p["artifact_id"] for p in V5_PLACEMENTS}
    # Même placement canonique V4/V5 : l'unique différence est l'autorité.
    assert sorted(v4_hggsp, key=lambda p: p["placement_id"]) == sorted(
        V5_PLACEMENTS, key=lambda p: p["placement_id"])


# ── état produit initial ─────────────────────────────────────────────────────


def _vecteur_synthetique(graine: str) -> str:
    octets = hashlib.sha256(graine.encode()).digest()
    return "[" + ",".join(str(((octets[i % 32] + i) % 251) / 125.0 - 1.0 + 1e-3)
                          for i in range(1024)) + "]"


def _seed_product(product: dict[str, str], placements: list[dict[str, Any]], *,
                  authorization_ids: dict[str, str], attestations: dict[str, uuid.UUID],
                  marque: str) -> None:
    """Représente des lignes produit DÉJÀ publiées : identités scellées V4,
    faits d'artefact que le publisher écrit pour une release scellée
    (``officiel_public``, officiel, ``sealed_release``, ``type_doc`` du
    catalogue), autorité nommée, texte et vecteurs synthétiques ``marque``."""
    from ingestor.ingestion_profiles.registry import load_profile_registry

    audiences = {p.scope.collection: sorted(str(a) for a in p.scope.audience)
                 for p in load_profile_registry(PROFILES_V4).values()}
    par_contenu: dict[str, list[dict[str, Any]]] = {}
    for placement in sorted(placements, key=lambda p: p["placement_id"]):
        par_contenu.setdefault(placement["artifact_id"], []).append(placement)
    with psycopg.connect(product["admin_dsn"]) as conn:
        for contenu, lignes in sorted(par_contenu.items()):
            entree = V4_CATALOG[contenu]
            conn.execute(
                "INSERT INTO public.rag_artifacts (artifact_id, content_sha256, source_label,"
                " source_uri, rights, official, source_kind, type_doc, ingestion_artifact_id)"
                " VALUES (%s, %s, %s, %s, 'officiel_public', true, 'sealed_release', %s, %s)",
                (contenu, contenu, marque, entree["source_url"], entree["type_doc"], uuid.uuid4()),
            )
            for p in lignes:
                conn.execute(
                    "INSERT INTO public.rag_artifact_placements (placement_id, artifact_id,"
                    " collection, tenant, niveau, voie, audience, matiere, statut_enseignement,"
                    " candidat, visibility, school_year, programme_version, currentness,"
                    " placement_status, review_status, source_scope, source_placement_id,"
                    " source_path, source_uri, authorization_id, publication_attestation_id)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " 'active', 'reviewed', %s, %s, %s, %s, %s, %s)",
                    (p["placement_id"], contenu, p["collection"], p["tenant"], p["niveau"],
                     p["voie"], audiences[p["collection"]], p["matiere"],
                     p["statut_enseignement"], p["candidat"], p["visibility"],
                     p["school_year"], p["programme_version"], p["currentness"],
                     p["source_scope"], p["source_placement_id"], entree["source_path"],
                     entree["source_url"], authorization_ids[p["collection"]],
                     attestations[p["placement_id"]]),
                )
            p = lignes[0]
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO public.rag_chunks (chunk_id, doc_id, chunk_sha256, vector,"
                    " collection, niveau, voie, audience, matiere, statut_enseignement,"
                    " source_label, source_uri, rights, type_doc, official, text, chunk_index,"
                    " page_start, page_end, review_status, model, source_kind, tenant,"
                    " candidat, visibility, school_year, programme_version, artifact_id)"
                    " VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " 'officiel_public', %s, true, %s, %s, %s, %s, 'reviewed', %s, 'sealed_release',"
                    " %s, %s, %s, %s, %s, %s)",
                    [(c["chunk_id"], contenu, c["chunk_sha256"], _vecteur_synthetique(c["chunk_id"]),
                      p["collection"], p["niveau"], p["voie"], audiences[p["collection"]],
                      p["matiere"], p["statut_enseignement"], marque, entree["source_url"],
                      entree["type_doc"], f"[{marque}] {c['chunk_id']}", c["chunk_index"],
                      c["page_start"], c["page_end"], marque, p["tenant"], p["candidat"],
                      p["visibility"], p["school_year"], p["programme_version"], contenu)
                     for c in entree["chunks"]],
                )


def _r4_v4() -> dict[str, str]:
    sys.path.insert(0, str(REPOSITORY_ROOT / "scripts/go_live"))
    import build_lot41a_r4_authorizations as generateur  # noqa: PLC0415

    return {doc["scope"]["collection"]: cle for cle, doc in generateur.construire(REPOSITORY_ROOT).items()}


def _produit(product: dict[str, str], *, hggsp: bool) -> dict[str, Any]:
    """Cardinalités et empreinte de TOUTES les colonnes, côté HGGSP ou non."""
    filtre = "(collection = ANY(%(c)s)) = %(h)s"
    contenus = f"SELECT artifact_id FROM public.rag_artifact_placements WHERE {filtre}"
    with psycopg.connect(product["admin_dsn"]) as conn:
        placements = conn.execute(
            f"SELECT count(DISTINCT collection), count(DISTINCT artifact_id), count(*),"
            f" md5(coalesce(string_agg(row_to_json(p)::text, '|' ORDER BY placement_id), ''))"
            f"  FROM public.rag_artifact_placements p WHERE {filtre}",
            {"c": list(COLLECTIONS), "h": hggsp},
        ).fetchone()
        artefacts = conn.execute(
            f"SELECT count(*), md5(coalesce(string_agg(row_to_json(a)::text, '|'"
            f" ORDER BY artifact_id), '')) FROM public.rag_artifacts a"
            f" WHERE artifact_id IN ({contenus})",
            {"c": list(COLLECTIONS), "h": hggsp},
        ).fetchone()
        chunks = conn.execute(
            f"SELECT count(DISTINCT chunk_id), md5(coalesce(string_agg(row_to_json(c)::text, '|'"
            f" ORDER BY chunk_id), '')) FROM public.rag_chunks c"
            f" WHERE artifact_id IN ({contenus})",
            {"c": list(COLLECTIONS), "h": hggsp},
        ).fetchone()
        conn.rollback()
    assert placements and artefacts and chunks
    return {
        "cardinalites": (placements[0], placements[1], placements[2], chunks[0]),
        "empreintes": (placements[3], artefacts[1], chunks[1]),
        "artefacts": artefacts[0],
    }


def _jobs_v4(control: dict[str, str]) -> list[tuple[Any, ...]]:
    with psycopg.connect(superuser_dsn(control)) as conn:
        lignes = conn.execute(
            "SELECT j.status, j.attempt_count, j.claimed_by FROM ingestion_control.jobs j"
            "  JOIN ingestion_control.publication_attestations pa"
            "    ON pa.attestation_id::text = j.payload->>'publication_attestation_id'"
            " WHERE pa.release_id = %s", (V4_ID,),
        ).fetchall()
        conn.rollback()
    return lignes


# ── la chaîne V5 ─────────────────────────────────────────────────────────────


def _chaine_v5_jusqu_a_la_file(control: dict[str, str], tmp: Path, github: LocalGitHub,
                               jeton: Path, *, graine: str) -> dict[str, Any]:
    """Contrôle V4 (décision B) puis toute la chaîne V5 jusqu'aux 74 jobs."""
    transfer_v4 = transfert_nomme(tmp, V4_ID)
    transfer_v5 = transfert_nomme(tmp, V5_ID, release_dir=V5_DIR)
    old_auth, new_auth, docs = _r4_documents()
    with local_github_server(github) as github_url:
        env = {
            "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control),
            "PG_INGESTION_CONTROL_ADOPTER_DSN": adopter_dsn(control),
            "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control),
            **acces_github(github_url, jeton),
        }
        enregistrer(github=github, env=env, documents=docs, numero=8103, graine=graine)
        _seed_v4(control, facts=_facts(V4_DIR, transfer_v4), transfer=transfer_v4,
                 authorization_ids=old_auth, served=False)
        avant = {
            "controle": _snapshot_v4_control(control),
            "attestations_jobs": _snapshot_v4_attestations_and_jobs(control),
        }
        adopte = run(CLI, [
            "adopt-predecessor-release", "--adoption-version", "SEALED-RELEASE-ADOPTION-V2",
            "--release-id", V5_ID, "--release-dir", str(V5_DIR),
            "--release-manifest-sha256", sha(V5_DIR / MANIFESTE),
            "--artifacts-release-sha256", sha(V5_DIR / "artifacts.release.json"),
            "--candidate-inventory-sha256", sha(V5_DIR / "candidate_inventory.json"),
            "--transfer-manifest-path", str(transfer_v5),
            "--transfer-manifest-sha256", sha(transfer_v5),
            "--predecessor-release-id", V4_ID,
            "--predecessor-release-manifest-sha256", sha(V4_DIR / MANIFESTE),
            "--adopted-by", f"{graine}-adopter",
        ], env)
        assert adopte.returncode == 0, adopte.stderr
        assert "created_adoptions=74" in adopte.stdout, adopte.stdout
        lie = run(CLI, [
            "bind-publication-authorities", "--release-id", V5_ID, "--bound-by", graine,
            *[a for c in COLLECTIONS for a in ("--scope-authorization", f"{c}={new_auth[c]}")],
        ], env)
        assert lie.returncode == 0, lie.stderr
        revue = f"{graine}-review"
        propose = run(CLI, arguments_de_proposition(
            release_dir=V5_DIR, release_id=V5_ID, transfert=transfer_v5, revue=revue), env)
        assert propose.returncode == 0, propose.stderr
        chemin, contenu = artefact_propose(propose.stdout)
        tete = hashlib.sha1(f"{graine}-reviewed-head".encode()).hexdigest()
        github.add_approved_pr(number=8105, head_sha=tete, base_sha="9" * 40, review_id=8115)
        github.put_blob(path=chemin, ref=tete, content=contenu)
        enregistre = run(CLI, arguments_d_enregistrement(
            release_id=V5_ID, revue=revue, pull_request=8105, tete=tete, chemin=chemin), env)
        assert enregistre.returncode == 0, enregistre.stderr
    file_args = ["--release-id", V5_ID, "--expected-jobs", "74",
                 *[a for c in COLLECTIONS for a in ("--collection", c)]]
    file_env = {"PG_INGESTION_CONTROL_DSN": app_dsn(control)}
    en_file = run(ENQUEUE, file_args, file_env)
    assert en_file.returncode == 0, en_file.stderr
    assert "crees=74" in en_file.stdout, en_file.stdout
    return {"old_auth": old_auth, "new_auth": new_auth, "transfer_v5": transfer_v5,
            "avant": avant, "file_args": file_args, "file_env": file_env}


def _arguments_v5(tmp: Path, transfer_v5: Path, *, iterations: int) -> list[str]:
    modele = os.environ.get(MODELE_E5_ENV, "").strip()
    if not modele:
        pytest.fail(f"{MODELE_E5_ENV} is required: Worker B really embeds with E5")
    racine_magasin = tmp / f"magasin-{uuid.uuid4().hex[:8]}"
    racine_magasin.mkdir()
    return [
        *arguments_worker_b(
            release_dir=V5_DIR, profiles_dir=PROFILES_V4,
            profile_manifest=PROFILE_MANIFEST_V4,
            magasin=magasin_reel(racine_magasin, release_dir=V5_DIR),
            transfert=transfer_v5, modele=Path(modele),
            subjects_mapping=SUBJECTS_MAPPING_V5,
        ),
        *[a for c in COLLECTIONS for a in ("--collection", c)],
        "--poll-interval-s", "1", "--max-iterations", str(iterations),
        "--max-idle-polls", "2",
    ]


def _readiness_v5(tmp: Path) -> dict[str, str]:
    return readiness(tmp, release_id=V5_ID, manifest_sha256=sha(V5_DIR / MANIFESTE))


def _vrai_cli_worker_b(control: dict[str, str], product: dict[str, str], tmp: Path,
                       github: LocalGitHub, jeton: Path, transfer_v5: Path) -> Any:
    """Le vrai CLI, en sous-processus, tel que le staging le lancera."""
    return lancer_worker_b(
        control, product, github=github, jeton=jeton, readiness_env=_readiness_v5(tmp),
        arguments=_arguments_v5(tmp, transfer_v5, iterations=1), timeout=1800,
    )


@contextmanager
def _correctif_de_demarrage_propose() -> Iterator[None]:
    """BANC SEULEMENT — les corrections minimales proposées, jamais livrées ici.

    Correction 1 : ``from_authorities`` exige une taxonomie scellée pour CHAQUE profil du
    registre gouverné (11), alors que le registre de programmes de V5 n'en
    scelle que 2 : le vrai CLI refuse de démarrer. La correction proposée
    borne ce contrôle aux collections que la release porte. Le banc l'applique
    en présentant au résolveur les seuls profils de la release — le manifeste
    de profils a déjà été vérifié sur le registre COMPLET par
    ``load_multilevel_runtime_authorities`` avant cet appel. Rien d'autre
    n'est modifié : claim, vérifications live, publisher, E5.
    """
    from ingestor.multilevel_verified_placement import (
        MultilevelVerifiedPedagogicalPlacementResolver as Resolver,
    )

    original = Resolver.from_authorities

    def borne(*, profiles: Any, profile_manifest: Any, release_eligibility: Any,
              **autres: Any) -> Any:
        release = {item.collection for item in release_eligibility.placements}
        gardes = {cle: profil for cle, profil in profiles.items() if cle[0] in release}
        return original(
            profiles=gardes,
            profile_manifest=replace(profile_manifest, declared_count=len(gardes)),
            release_eligibility=release_eligibility, **autres,
        )

    from ingestor.ingestion_worker import publication_resume

    def payload_complet(payload: dict[str, Any]) -> dict[str, Any]:
        # Correction 2 : une ressource successeur V2 naît à ``state_version``
        # 0 (défaut du schéma, ``CHECK >= 0``) ; ``not payload.get(...)``
        # prenait ce 0 pour une absence. Seuls None et "" sont absents.
        manquants = [champ for champ in publication_resume.REQUIRED_PAYLOAD_FIELDS
                     if payload.get(champ) is None or payload.get(champ) == ""]
        if manquants:
            raise publication_resume.PublicationResumeError(
                f"publication_resume payload is missing {manquants}")
        return payload

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Resolver, "from_authorities", staticmethod(borne))
        patch.setattr(publication_resume, "_require_payload", payload_complet)
        yield


def _worker_b_corrige(control: dict[str, str], product: dict[str, str], tmp: Path,
                      github: LocalGitHub, jeton: Path, transfer_v5: Path, *,
                      iterations: int) -> SimpleNamespace:
    """Le ``main()`` du vrai CLI, en processus, sous la seule correction
    proposée ; mêmes arguments, même readiness, mêmes rôles."""
    from ingestor.ingestion_worker import multilevel_publication_resume_cli as cli

    arguments = _arguments_v5(tmp, transfer_v5, iterations=iterations)
    sortie, erreur = io.StringIO(), io.StringIO()
    with local_github_server(github) as github_url, pytest.MonkeyPatch.context() as env, \
            _correctif_de_demarrage_propose():
        for nom, valeur in {
            **_readiness_v5(tmp),
            "PG_INGESTION_CONTROL_DSN": app_dsn(control),
            "PG_RAG_DSN": product["publisher_dsn"],
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CUDA_VISIBLE_DEVICES": "",
            **acces_github(github_url, jeton),
        }.items():
            env.setenv(nom, valeur)
        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = cli.main(arguments)
    return SimpleNamespace(returncode=code, stdout=sortie.getvalue(), stderr=erreur.getvalue())


def _jobs_v5(control: dict[str, str]) -> dict[str, int]:
    with psycopg.connect(superuser_dsn(control)) as conn:
        lignes = conn.execute(
            "SELECT j.status, count(*) FROM ingestion_control.jobs j"
            "  JOIN ingestion_control.publication_attestations pa"
            "    ON pa.attestation_id::text = j.payload->>'publication_attestation_id'"
            " WHERE pa.release_id = %s GROUP BY 1", (V5_ID,),
        ).fetchall()
        conn.rollback()
    return dict(lignes)


@pytest.fixture(scope="module")
def scenario_b(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    tmp = tmp_path_factory.mktemp("hggsp-v5-scenario-b")
    jeton = tmp / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    github = LocalGitHub()
    control_gen = start_ingestion_control_postgres("hggsp-v5-scenario-b")
    product_gen = start_rag_product_postgres("hggsp-v5-scenario-b-product")
    control, product = next(control_gen), next(product_gen)
    try:
        _seed_product(product, V4_NON_HGGSP, authorization_ids=_r4_v4(),
                      attestations={p["placement_id"]: uuid.uuid4() for p in V4_NON_HGGSP},
                      marque="fixture-v4-non-hggsp-deja-servi")
        produit_initial = {"non_hggsp": _produit(product, hggsp=False),
                           "hggsp": _produit(product, hggsp=True)}
        chaine = _chaine_v5_jusqu_a_la_file(control, tmp, github, jeton, graine="hggsp-v5-b")
        jobs_v4_avant = _jobs_v4(control)
        vrai_cli = _vrai_cli_worker_b(control, product, tmp, github, jeton, chaine["transfer_v5"])
        produit_apres_vrai_cli = _produit(product, hggsp=True)
        premiere = _worker_b_corrige(control, product, tmp, github, jeton, chaine["transfer_v5"],
                                     iterations=74 + 4)
        jobs_v5 = _jobs_v5(control)
        produit_publie = {"non_hggsp": _produit(product, hggsp=False),
                          "hggsp": _produit(product, hggsp=True)}
        rejeu_file = run(ENQUEUE, chaine["file_args"], chaine["file_env"])
        rejeu = _worker_b_corrige(control, product, tmp, github, jeton, chaine["transfer_v5"],
                                  iterations=4)
        yield {
            "control": control, "product": product, "chaine": chaine,
            "produit_initial": produit_initial, "produit_publie": produit_publie,
            "produit_rejeu": {"non_hggsp": _produit(product, hggsp=False),
                              "hggsp": _produit(product, hggsp=True)},
            "jobs_v4_avant": jobs_v4_avant, "jobs_v4_apres": _jobs_v4(control),
            "vrai_cli": vrai_cli, "produit_apres_vrai_cli": produit_apres_vrai_cli,
            "premiere": premiere, "jobs_v5": jobs_v5, "rejeu_file": rejeu_file, "rejeu": rejeu,
            "jobs_v5_rejeu": _jobs_v5(control),
            "apres": {"controle": _snapshot_v4_control(control),
                      "attestations_jobs": _snapshot_v4_attestations_and_jobs(control)},
        }
    finally:
        for gen in (product_gen, control_gen):
            gen.close()


def test_etat_initial_zero_hggsp_et_v4_non_hggsp_servie(scenario_b: dict[str, Any]) -> None:
    initial = scenario_b["produit_initial"]
    assert initial["hggsp"]["cardinalites"] == (0, 0, 0, 0)
    assert initial["non_hggsp"]["cardinalites"] == (9, 263, 405, 5678)
    # Les 74 jobs V4 HGGSP attendaient, jamais réclamés.
    assert sorted(scenario_b["jobs_v4_avant"]) == [("queued", 0, None)] * 74


def test_le_vrai_cli_refuse_de_demarrer_sans_ecrire(scenario_b: dict[str, Any]) -> None:
    """Le blocage CONSTATÉ du scénario B : démarrage, pas produit."""
    sortie = scenario_b["vrai_cli"]
    if sortie.returncode == 0:
        pytest.fail("le vrai CLI démarre désormais sur V5 : retirer le correctif de banc")
    assert refus_au_demarrage(sortie).endswith(
        "collection 'rag_nexus_dgemc_terminale_option' has no sealed taxonomy")
    assert scenario_b["produit_apres_vrai_cli"]["cardinalites"] == (0, 0, 0, 0)


def test_premiere_publication_v5_reussit_sous_le_correctif_propose(
    scenario_b: dict[str, Any],
) -> None:
    sortie = scenario_b["premiere"]
    assert sortie.returncode == 0, sortie.stderr[-3000:]
    assert "authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION" in sortie.stdout
    assert f"claim_release_id={V5_ID}" in sortie.stdout
    assert erreurs_d_iteration(sortie.stderr) == []
    assert scenario_b["jobs_v5"] == {"succeeded": 74}, sortie.stdout[-3000:]


def test_identites_et_autorites_produit_v5(scenario_b: dict[str, Any]) -> None:
    control, product = scenario_b["control"], scenario_b["product"]
    new_auth, old_auth = scenario_b["chaine"]["new_auth"], scenario_b["chaine"]["old_auth"]
    with psycopg.connect(superuser_dsn(control)) as conn:
        v5 = {str(r[0]): (r[1], r[2]) for r in conn.execute(
            "SELECT pa.attestation_id, pa.resource_id, pa.artifact_id"
            "  FROM ingestion_control.publication_attestations pa"
            "  JOIN ingestion_control.sealed_release_adoptions ad"
            "    ON ad.release_id = pa.release_id AND ad.successor_resource_id = pa.resource_id"
            "   AND ad.successor_artifact_id = pa.artifact_id"
            " WHERE pa.release_id = %s AND pa.invalidated_at IS NULL", (V5_ID,)).fetchall()}
        v4_controle = {r[0] for r in conn.execute(
            "SELECT artifact_id FROM ingestion_control.publication_attestations"
            " WHERE release_id = %s", (V4_ID,)).fetchall()}
        conn.rollback()
    assert len(v5) == 74
    with psycopg.connect(product["admin_dsn"]) as conn:
        placements = conn.execute(
            "SELECT placement_id, artifact_id, collection, authorization_id,"
            "       publication_attestation_id::text, currentness"
            "  FROM public.rag_artifact_placements WHERE collection = ANY(%s)",
            (list(COLLECTIONS),)).fetchall()
        artefacts = conn.execute(
            "SELECT a.artifact_id, a.ingestion_artifact_id FROM public.rag_artifacts a"
            " WHERE a.artifact_id IN (SELECT artifact_id FROM public.rag_artifact_placements"
            "                          WHERE collection = ANY(%s))", (list(COLLECTIONS),)).fetchall()
        chunks = conn.execute(
            "SELECT artifact_id, array_agg(chunk_sha256 ORDER BY chunk_index),"
            "       array_agg(chunk_id ORDER BY chunk_index), array_agg(DISTINCT model)"
            "  FROM public.rag_chunks WHERE artifact_id = ANY(%s) GROUP BY artifact_id",
            (sorted({p["artifact_id"] for p in V5_PLACEMENTS}),)).fetchall()
        conn.rollback()
    scelles = {p["placement_id"]: p for p in V5_PLACEMENTS}
    # Placement canonique : identité produit = identité scellée, jamais l'UUID de contrôle.
    assert {r[0] for r in placements} == set(scelles)
    for placement_id, contenu, collection, autorisation, attestation, actualite in placements:
        assert (contenu, collection, actualite) == (
            scelles[placement_id]["artifact_id"], scelles[placement_id]["collection"],
            scelles[placement_id]["currentness"])
        assert autorisation == new_auth[collection] != old_auth[collection]
        assert attestation in v5
    # Chaque attestation V5 porte exactement un placement produit.
    assert sorted(r[4] for r in placements) == sorted(v5)
    # Identité de contenu (52 SHA) distincte des 74 UUID de contrôle V5 ;
    # le lien d'ingestion nomme un artefact de contrôle V5, jamais V4.
    assert {r[0] for r in artefacts} == {p["artifact_id"] for p in V5_PLACEMENTS}
    successeurs = {artifact for _res, artifact in v5.values()}
    assert all(r[1] in successeurs and r[1] not in v4_controle for r in artefacts)
    assert len(chunks) == 52
    for contenu, shas, ids, modeles in chunks:
        assert shas == [c["chunk_sha256"] for c in V5_CATALOG[contenu]["chunks"]]
        assert ids == [c["chunk_id"] for c in V5_CATALOG[contenu]["chunks"]]
        assert modeles == ["intfloat/multilingual-e5-large"]


def test_cardinalites_apres_publication(scenario_b: dict[str, Any]) -> None:
    publie = scenario_b["produit_publie"]
    assert publie["hggsp"]["cardinalites"] == (2, 52, 74, 2590)
    assert publie["non_hggsp"]["cardinalites"] == (9, 263, 405, 5678)
    union = tuple(a + b for a, b in zip(publie["hggsp"]["cardinalites"],
                                         publie["non_hggsp"]["cardinalites"], strict=True))
    assert union == (11, 315, 479, 8268)


def test_v4_conservee_controle_et_produit(scenario_b: dict[str, Any]) -> None:
    assert scenario_b["apres"] == scenario_b["chaine"]["avant"]
    assert scenario_b["jobs_v4_apres"] == scenario_b["jobs_v4_avant"]
    assert (scenario_b["produit_publie"]["non_hggsp"]
            == scenario_b["produit_initial"]["non_hggsp"])


def test_rejeu_idempotent(scenario_b: dict[str, Any]) -> None:
    file = scenario_b["rejeu_file"]
    assert file.returncode == 0, file.stderr
    assert "crees=0" in file.stdout and "deja_publies=74" in file.stdout, file.stdout
    rejeu = scenario_b["rejeu"]
    assert rejeu.returncode == 0, rejeu.stderr[-3000:]
    assert "MULTILEVEL_PUBLICATION_WORKER_ITERATION " not in rejeu.stdout
    assert scenario_b["jobs_v5_rejeu"] == {"succeeded": 74}
    assert scenario_b["produit_rejeu"] == scenario_b["produit_publie"]


# ── cas 3 : contre-épreuve, hors du scénario B ───────────────────────────────


def test_cas_3_une_ligne_hggsp_v4_preexistante_refuse_le_remplacement(
    tmp_path: Path,
) -> None:
    """Contre-épreuve seulement. Le produit reçoit, en FIXTURE, les 74
    placements HGGSP sous autorité V4 — état que le scénario B n'a pas et que
    Worker B V4 ne peut pas produire (ses mappings ne gouvernent pas HGGSP).
    V5 doit alors refuser de réécrire l'autorité d'une ligne existante."""
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    github = LocalGitHub()
    control_gen = start_ingestion_control_postgres("hggsp-v5-cas-3")
    product_gen = start_rag_product_postgres("hggsp-v5-cas-3-product")
    control, product = next(control_gen), next(product_gen)
    try:
        chaine = _chaine_v5_jusqu_a_la_file(control, tmp_path, github, jeton, graine="hggsp-v5-c3")
        with psycopg.connect(superuser_dsn(control)) as conn:
            v4_attestations = dict(conn.execute(
                "SELECT a.payload->>'placement_id', pa.attestation_id"
                "  FROM ingestion_control.publication_attestations pa"
                "  JOIN ingestion_control.artifacts a USING (artifact_id)"
                " WHERE pa.release_id = %s", (V4_ID,)).fetchall())
            conn.rollback()
        v4_hggsp = [p for p in V4_PLACEMENTS if p["collection"] in COLLECTIONS]
        _seed_product(product, v4_hggsp, authorization_ids=chaine["old_auth"],
                      attestations=v4_attestations, marque="fixture-v4-hggsp-cas-3")
        avant = _produit(product, hggsp=True)
        sortie = _worker_b_corrige(control, product, tmp_path, github, jeton,
                                   chaine["transfer_v5"], iterations=1)
        assert sortie.returncode == 0, sortie.stderr[-3000:]
        erreurs = erreurs_d_iteration(sortie.stderr)
        assert len(erreurs) == 1, (sortie.stdout[-2000:], sortie.stderr[-2000:])
        print("CAS_3_REFUS", erreurs[0])
        assert erreurs[0].endswith("existing placement differs from verified input")
        assert _produit(product, hggsp=True) == avant
    finally:
        for gen in (product_gen, control_gen):
            gen.close()
