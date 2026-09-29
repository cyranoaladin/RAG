#!/usr/bin/env python3
"""Exercer le retrieval servi de V4 sur le staging, sous les scopes émis (lot DB).

Lecture seule, rôle ``rag_reader`` (``PG_RAG_DSN``), dans l'image ingestor
épinglée. Pour chaque collection que nomme l'autorité de nommage V4 :

* un jeton ``teacher`` est signé, en mémoire, par un secret éphémère de la
  sonde, sous le scope émis ; le scope serveur en est dérivé par le code servi ;
* son programme et sa visibilité sont confrontés au registre de programme de
  la release et à la visibilité servie (``internal``) ;
* chaque chunk atteignable par le scope est interrogé par son vecteur
  (périmètre entier, jamais un échantillon) et une requête lexicale est posée ;
* aucun candidat ne sort des placements autorisés du scope ; un refus dense n'est
  admis que constaté à sa source comme ``dense ann tie overflow`` ;
* le rôle ``student`` est refusé.

Méthode identique à ``test_4`` du banc réel V4 (lot CZ). Sortie : un rapport
JSON ; code 1 au premier manquement.

    python staging_retrieval_probe.py --repository-root /repo --output /run/probe.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

SUCCESSEURS_V4 = "packages/contracts/authorities/production-profile-scope-successors-v4.yml"
SUCCESSEURS_HGGSP = "packages/contracts/authorities/production-profile-scope-successors-hggsp-v5.yml"
RELEASE_V4 = "production-profile-gate-2026-2027-v4"
RELEASE_HGGSP = "production-profile-gate-2026-2027-v5-hggsp"
HGGSP_COLLECTIONS = frozenset({
    "rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite",
})
V4_HGGSP_SCOPES = {
    "rag_nexus_hggsp_premiere_specialite": "prod_hggsp_premiere_specialite_v2",
    "rag_nexus_hggsp_terminale_specialite": "prod_hggsp_terminale_specialite_v2",
}
SUCCESSOR_HGGSP_SCOPES = {
    "rag_nexus_hggsp_premiere_specialite": "prod_hggsp_premiere_specialite_v3",
    "rag_nexus_hggsp_terminale_specialite": "prod_hggsp_terminale_specialite_v3",
}
REGISTRY_BASE = "services/rag-pedago/data/releases/prerentree_2026_2027"
REGISTRE_PROGRAMME_V4 = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/"
    "release-024f8625ebfeb7ce/profile_gate/programme_registry.json"
)
REGISTRE_PROGRAMME_HGGSP = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_hggsp_v5/"
    "release-b34b11e678bf9559/profile_gate/programme_registry.json"
)
CONFIG_COLLECTIONS = "services/rag-engine/configs/rag_collections.yml"
VISIBILITE_SERVIE = "internal"
REFUS_EGALITE = "dense ann tie overflow"


class SondeEchec(RuntimeError):
    """Un manquement du retrieval servi."""


def _modules() -> dict[str, Any]:
    """Le code servi : paquet ``ingestor`` (dépôt) ou modules à plat (image)."""
    try:
        from ingestor import identity_v2, retrieval_hybrid_v2, retrieval_pg_v2, retrieval_scope_v2
        from ingestor.collection_config import load_collection_config
    except ImportError:  # image ingestor : modules à la racine de /app
        import identity_v2  # type: ignore[no-redef]
        import retrieval_hybrid_v2  # type: ignore[no-redef]
        import retrieval_pg_v2  # type: ignore[no-redef]
        import retrieval_scope_v2  # type: ignore[no-redef]
        from collection_config import load_collection_config  # type: ignore[no-redef]
    return {
        "identity": identity_v2,
        "hybrid": retrieval_hybrid_v2,
        "pg": retrieval_pg_v2,
        "scope": retrieval_scope_v2,
        "load_collection_config": load_collection_config,
    }


def scopes_emis(racine: Path) -> dict[str, str]:
    autorite = yaml.safe_load((racine / SUCCESSEURS_V4).read_text(encoding="utf-8"))
    if autorite.get("release_id") != RELEASE_V4:
        raise SondeEchec(f"autorité de nommage : release {autorite.get('release_id')!r}")
    return {b["collection"]: b["scope_id"] for b in autorite["bindings"]}


def programmes(racine: Path) -> dict[str, str]:
    registre = json.loads((racine / REGISTRE_PROGRAMME_V4).read_text(encoding="utf-8"))
    return {t["collection"]: t["programme_version"] for t in registre["taxonomies"]}


def mixed_authorities(
    racine: Path, registry_path: Path, registry_sha256: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Résout chaque collection depuis son propriétaire dans le registre v2."""
    if hashlib.sha256(registry_path.read_bytes()).hexdigest() != registry_sha256:
        raise SondeEchec("registre mixte : SHA-256 divergent")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    releases = registry.get("releases")
    if registry.get("registry_version") != "2" or not isinstance(releases, list) or len(releases) != 2:
        raise SondeEchec("registre mixte : version ou releases inattendues")
    by_id = {item.get("release_id"): item for item in releases}
    if set(by_id) != {RELEASE_V4, RELEASE_HGGSP}:
        raise SondeEchec("registre mixte : propriétaires inattendus")
    v4_collections = set(by_id[RELEASE_V4].get("collections", []))
    successor_collections = set(by_id[RELEASE_HGGSP].get("collections", []))
    if successor_collections != HGGSP_COLLECTIONS or len(v4_collections) != 9 or v4_collections & successor_collections:
        raise SondeEchec("registre mixte : collections hors du périmètre 9+2")
    for entry in releases:
        manifest = racine / REGISTRY_BASE / entry["manifest_path"]
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != entry["expected_manifest_sha256"]:
            raise SondeEchec("registre mixte : manifeste propriétaire divergent")
    v4_scopes = scopes_emis(racine)
    if len(v4_scopes) != 11 or any(v4_scopes.get(name) != scope for name, scope in V4_HGGSP_SCOPES.items()):
        raise SondeEchec("registre mixte : les scopes HGGSP V4 ne sont pas préservés")
    successor = yaml.safe_load((racine / SUCCESSEURS_HGGSP).read_text(encoding="utf-8"))
    if (successor.get("release_id") != RELEASE_HGGSP
            or successor.get("release_manifest_sha256") != by_id[RELEASE_HGGSP]["expected_manifest_sha256"]
            or successor.get("mixed_registry_sha256") != registry_sha256):
        raise SondeEchec("registre mixte : autorité de scope successeur divergente")
    hggsp_scopes = {item["collection"]: item["scope_id"] for item in successor["bindings"]}
    if set(hggsp_scopes) != HGGSP_COLLECTIONS or set(v4_scopes) & v4_collections != v4_collections:
        raise SondeEchec("registre mixte : collections de scopes divergentes")
    if set(hggsp_scopes.values()) & set(V4_HGGSP_SCOPES.values()):
        raise SondeEchec("registre mixte : scope HGGSP V4 réutilisé")
    if hggsp_scopes != SUCCESSOR_HGGSP_SCOPES:
        raise SondeEchec("registre mixte : scopes HGGSP successeurs inattendus")
    v4_programmes = programmes(racine)
    hggsp_registry = json.loads((racine / REGISTRE_PROGRAMME_HGGSP).read_text(encoding="utf-8"))
    hggsp_programmes = {item["collection"]: item["programme_version"] for item in hggsp_registry["taxonomies"]}
    if set(hggsp_programmes) != HGGSP_COLLECTIONS or not v4_collections <= set(v4_programmes):
        raise SondeEchec("registre mixte : programmes divergents")
    scopes = {name: v4_scopes[name] for name in sorted(v4_collections)}
    scopes.update(hggsp_scopes)
    programme_versions = {name: v4_programmes[name] for name in v4_collections}
    programme_versions.update(hggsp_programmes)
    owners = {name: RELEASE_V4 for name in v4_collections}
    owners.update({name: RELEASE_HGGSP for name in HGGSP_COLLECTIONS})
    return scopes, programme_versions, owners


def identite_verifiee(modules: Mapping[str, Any], scope_id: str, *, role: str, secret: str) -> Any:
    """Jeton interne signé pour le scope émis ; l'identité découle du scope."""
    environ = {
        "NEXUS_INTERNAL_TOKEN_SECRET": secret,
        "NEXUS_INTERNAL_TOKEN_ISSUER": "sonde-staging",
        "NEXUS_INTERNAL_TOKEN_AUDIENCE": "sonde-engine",
        "NEXUS_SSO_ISSUER": "sonde-sso",
        "NEXUS_SSO_AUDIENCE": "sonde-cockpit",
    }
    identity = modules["identity"]
    config = identity.load_identity_verifier_config(environ)
    artefact = config.artifacts[scope_id]
    cible, sujet = artefact.target_identity, artefact.evidence_subject
    maintenant = int(time.time())
    personne = {
        "aud": environ["NEXUS_SSO_AUDIENCE"], "exp": maintenant + 600,
        "iss": environ["NEXUS_SSO_ISSUER"], "jti": f"sonde-{scope_id}-{role}",
        "tenant": cible.tenant, "niveau": cible.niveau.value, "role": role,
        "school_year": sujet.school_year, "sub": "psn_sondestaging00001",
        "pedagogical_profile": {
            "voie": cible.voie.value, "matieres": [cible.matiere],
            "statut_enseignement": cible.statut_enseignement.value,
            "candidat": cible.candidates[0].value, "audience": cible.audience,
        },
    }
    charge = {
        "protocol_version": "1", "iss": environ["NEXUS_INTERNAL_TOKEN_ISSUER"],
        "aud": environ["NEXUS_INTERNAL_TOKEN_AUDIENCE"], "sub": personne["sub"],
        "jti": personne["jti"], "iat": maintenant, "exp": maintenant + 300,
        "identity": personne, "scope_id": scope_id,
        "scope_digest": artefact.sha256_digest(), "allowed_collections": [sujet.collection],
    }

    def _b64(valeur: bytes) -> str:
        return base64.urlsafe_b64encode(valeur).rstrip(b"=").decode("ascii")

    entete = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    corps = _b64(json.dumps(charge).encode())
    signature = hmac.new(secret.encode(), f"{entete}.{corps}".encode("ascii"), hashlib.sha256).digest()
    return identity.verify_identity_token(f"{entete}.{corps}.{_b64(signature)}", config=config)


# Oracle indépendant du magasin de candidats : la collection de rag_chunks est
# l'ancre physique. Pour un artefact gouverné, seul son placement décide dans
# quels scopes ses chunks sont atteignables. Le cas legacy n'a pas de placement
# et doit donc satisfaire toutes les dimensions physiques du scope.
_JEU_PUBLIE_SQL = """
SELECT chunk_id, vector_text, text, artifact_id, placement_id
FROM (
    SELECT chunk.chunk_id, chunk.vector::text AS vector_text, chunk.text,
           chunk.artifact_id, NULL::text AS placement_id
      FROM public.rag_chunks AS chunk
     WHERE chunk.artifact_id IS NULL
       AND chunk.collection = %(collection)s
       AND chunk.tenant = %(tenant)s
       AND chunk.niveau = %(niveau)s
       AND chunk.voie IS NOT DISTINCT FROM %(voie)s
       AND chunk.matiere = %(matiere)s
       AND chunk.statut_enseignement = %(statut_enseignement)s
       AND chunk.candidat = ANY(%(candidats)s::text[])
       AND chunk.audience && %(audiences)s::text[]
       AND chunk.rights = ANY(%(rights)s::text[])
       AND chunk.visibility = ANY(%(visibilities)s::text[])
       AND chunk.school_year = %(school_year)s
       AND chunk.programme_version = %(programme_version)s
       AND chunk.review_status = 'reviewed'
       AND btrim(chunk.source_label) <> ''
       AND btrim(chunk.source_uri) <> ''
       AND btrim(chunk.rights) <> ''
    UNION ALL
    SELECT chunk.chunk_id, chunk.vector::text AS vector_text, chunk.text,
           chunk.artifact_id, placement.placement_id
      FROM public.rag_chunks AS chunk
      JOIN public.rag_artifacts AS artifact ON artifact.artifact_id = chunk.artifact_id
      JOIN public.rag_artifact_placements AS placement
        ON placement.artifact_id = artifact.artifact_id
     WHERE chunk.artifact_id IS NOT NULL
       AND placement.collection = %(collection)s
       AND placement.tenant = %(tenant)s
       AND placement.niveau = %(niveau)s
       AND placement.voie IS NOT DISTINCT FROM %(voie)s
       AND placement.matiere = %(matiere)s
       AND placement.statut_enseignement = %(statut_enseignement)s
       AND placement.candidat = ANY(%(candidats)s::text[])
       AND placement.audience && %(audiences)s::text[]
       AND placement.visibility = ANY(%(visibilities)s::text[])
       AND placement.school_year = %(school_year)s
       AND placement.programme_version = %(programme_version)s
       AND placement.placement_status = 'active'
       AND placement.currentness IN ('current', 'official_snapshot')
       AND placement.review_status = 'reviewed'
       AND artifact.rights = ANY(%(rights)s::text[])
       AND btrim(artifact.source_label) <> ''
       AND btrim(artifact.source_uri) <> ''
       AND btrim(artifact.rights) <> ''
       AND btrim(placement.source_uri) <> ''
) AS atteignable
ORDER BY chunk_id, placement_id NULLS FIRST
"""


def jeu_publie(conn: Any, scope: Any) -> tuple[dict[str, tuple[str, str]], set[tuple[str, str | None, str | None]]]:
    """Chunks à interroger et identités de placement autorisées par le scope."""
    parametres = {
        "collection": scope.collection,
        "tenant": scope.tenant,
        "niveau": scope.niveau,
        "voie": scope.voie,
        "matiere": scope.matiere,
        "statut_enseignement": scope.statut_enseignement,
        "candidats": list(dict.fromkeys((scope.candidat, "both"))),
        "audiences": list(scope.audiences),
        "rights": [droit.value for droit in scope.rights],
        "visibilities": list(scope.visibilities),
        "school_year": scope.school_year,
        "programme_version": scope.programme_version,
    }
    chunks: dict[str, tuple[str, str]] = {}
    autorises: set[tuple[str, str | None, str | None]] = set()
    for chunk_id, vecteur, texte, artifact_id, placement_id in conn.execute(
        _JEU_PUBLIE_SQL, parametres
    ).fetchall():
        if not vecteur or not texte or not texte.strip():
            raise SondeEchec(f"{scope.collection} : chunk publié sans vecteur ou texte ({chunk_id})")
        valeur = (vecteur, texte)
        if chunk_id in chunks and chunks[chunk_id] != valeur:
            raise SondeEchec(f"{scope.collection} : chunk {chunk_id} incohérent entre placements")
        chunks[chunk_id] = valeur
        autorises.add((chunk_id, artifact_id, placement_id))
    return chunks, autorises


def verifier_candidats_publies(
    candidats: Iterable[Any], autorises: set[tuple[str, str | None, str | None]],
    *, collection: str, canal: str,
) -> None:
    """Refuse un candidat dont le chunk OU le placement sort du scope."""
    if any((c.chunk_id, c.artifact_id, c.placement_id) not in autorises for c in candidats):
        raise SondeEchec(f"{collection} : candidat {canal} hors du jeu publié")


def sonder(
    racine: Path,
    *,
    connexion: Callable[[], Any],
    modules: Mapping[str, Any] | None = None,
    collections: Iterable[str] | None = None,
    mixed_registry: tuple[Path, str] | None = None,
) -> dict[str, Any]:
    """Le rapport de sonde ; lève ``SondeEchec`` au premier manquement.

    ``collections`` restreint la sonde (banc) ; par défaut, toutes celles que
    nomme l'autorité de nommage V4 (staging)."""
    modules = modules or _modules()
    configuration = modules["load_collection_config"](racine / CONFIG_COLLECTIONS)
    if mixed_registry is None:
        emis, officiels = scopes_emis(racine), programmes(racine)
    else:
        emis, officiels, _owners = mixed_authorities(racine, *mixed_registry)
    if set(emis) != set(officiels):
        raise SondeEchec("collections : autorité de nommage ≠ registre de programme")
    retenues = sorted(emis) if collections is None else sorted(collections)
    if not set(retenues) <= set(emis):
        raise SondeEchec(f"collections hors de l'autorité de nommage : {sorted(set(retenues) - set(emis))}")
    if mixed_registry is not None and (len(retenues) != 11 or set(retenues) != set(emis)):
        raise SondeEchec("sonde mixte : les onze scopes doivent être exercés")
    secret = secrets.token_hex(32)
    erreur_pipeline = modules["hybrid"].RetrievalPipelineError
    erreur_scope = modules["scope"].RetrievalScopeError

    # Le store masque la cause d'un refus dense ; on l'observe à sa source.
    motifs: list[str] = []
    charge_dense = modules["pg"]._dense_payload

    def _charge_observee(ligne: Any) -> Any:
        try:
            return charge_dense(ligne)
        except erreur_pipeline as exc:
            motifs.append(str(exc))
            raise

    modules["pg"]._dense_payload = _charge_observee
    rapport: dict[str, Any] = {"release_id": RELEASE_V4 if mixed_registry is None else "mixed-v4-hggsp", "collections": {}}
    try:
        for collection in retenues:
            scope = modules["scope"].build_server_retrieval_scope(
                identite_verifiee(modules, emis[collection], role="teacher", secret=secret),
                collection=collection, collection_config=configuration,
            )
            if (scope.programme_version, scope.visibilities) != (officiels[collection], (VISIBILITE_SERVIE,)):
                raise SondeEchec(f"{collection} : scope {scope.programme_version} {scope.visibilities}")
            with connexion() as conn:
                chunks, autorises = jeu_publie(conn, scope)
                conn.rollback()
            if not chunks:
                raise SondeEchec(f"{collection} : aucun chunk publié lisible par rag_reader")
            store = modules["pg"].PgCandidateStore(connexion, scope)
            en_tete, retrouves, manques, egalites = 0, 0, 0, 0
            for chunk_id, (vecteur, _texte) in chunks.items():
                valeurs = [float(v) for v in vecteur.strip("[]").split(",")]
                try:
                    candidats = store.dense(query_vector=valeurs, collection=collection, limit=5)
                except erreur_pipeline as exc:
                    if not motifs or motifs[-1] != REFUS_EGALITE:
                        raise SondeEchec(f"{collection} {chunk_id[:12]} : refus dense {motifs[-1:]}") from exc
                    motifs.clear()
                    egalites += 1
                    continue
                if not candidats:
                    raise SondeEchec(f"{collection} {chunk_id[:12]} : candidat hors du jeu publié")
                verifier_candidats_publies(candidats, autorises, collection=collection, canal="dense")
                identiques = [c for c in candidats if c.chunk_id == chunk_id or c.vector == tuple(valeurs)]
                en_tete += candidats[0] in identiques
                retrouves += bool(identiques)
                manques += not identiques
            mots = next((t for _v, t in chunks.values() if len(t.split()) >= 8), "").split()[:8]
            lexicaux = store.lexical(raw_query=" ".join(mots), collection=collection, limit=10) if mots else []
            verifier_candidats_publies(lexicaux, autorises, collection=collection, canal="lexical")
            try:
                modules["scope"].build_server_retrieval_scope(
                    identite_verifiee(modules, emis[collection], role="student", secret=secret),
                    collection=collection, collection_config=configuration,
                )
            except erreur_scope:
                eleve = "refuse"
            else:
                raise SondeEchec(f"{collection} : le rôle student a obtenu un scope internal")
            rapport["collections"][collection] = {
                "scope_id": emis[collection], "programme_version": scope.programme_version,
                "chunks": len(chunks), "rappel_a_1": en_tete, "rappel_a_5": retrouves,
                "manques": manques, "refus_egalite": egalites, "lexicaux": len(lexicaux),
                "student": eleve,
            }
    finally:
        modules["pg"]._dense_payload = charge_dense
    rapport["totaux"] = {
        cle: sum(c[cle] for c in rapport["collections"].values())
        for cle in ("chunks", "rappel_a_1", "rappel_a_5", "manques", "refus_egalite")
    }
    return rapport


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - exécution sur l'hôte
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--collection", action="append", default=[],
        help="lot DI : restreint la sonde à ces collections (répétable) ; absente, toutes",
    )
    parser.add_argument("--mixed-registry", type=Path)
    parser.add_argument("--mixed-registry-sha256")
    args = parser.parse_args(argv)
    import psycopg

    dsn = os.environ.get("PG_RAG_DSN", "").strip()
    if not dsn:
        print("SONDE_ECHEC: PG_RAG_DSN absent", file=sys.stderr)
        return 1
    if bool(args.mixed_registry) != bool(args.mixed_registry_sha256):
        print("SONDE_ECHEC: registre mixte et SHA-256 requis ensemble", file=sys.stderr)
        return 1
    if args.mixed_registry:
        import check_staging_authorization as checker  # noqa: PLC0415

        operation = "successor_independent_verification"
        errors = checker.verifier_operation_hggsp_image(
            args.repository_root, operation, checker.OPERATIONS_HGGSP[operation]["cible"]
        )
        if errors:
            print("SONDE_ECHEC: autorisation HGGSP non consommable : " + "; ".join(errors), file=sys.stderr)
            return 1
    try:
        rapport = sonder(
            args.repository_root, connexion=lambda: psycopg.connect(dsn),
            collections=args.collection or None,
            mixed_registry=(args.mixed_registry, args.mixed_registry_sha256) if args.mixed_registry else None,
        )
    except SondeEchec as exc:
        print(f"SONDE_ECHEC: {exc}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SONDE_RETRIEVAL_MIXTE" if args.mixed_registry else "SONDE_RETRIEVAL_V4", json.dumps(rapport["totaux"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
