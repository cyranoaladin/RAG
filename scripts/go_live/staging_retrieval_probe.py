#!/usr/bin/env python3
"""Exercer le retrieval servi de V4 sur le staging, sous les scopes émis (lot DB).

Lecture seule, rôle ``rag_reader`` (``PG_RAG_DSN``), dans l'image ingestor
épinglée. Pour chaque collection que nomme l'autorité de nommage V4 :

* un jeton ``teacher`` est signé, en mémoire, par un secret éphémère de la
  sonde, sous le scope émis ; le scope serveur en est dérivé par le code servi ;
* son programme et sa visibilité sont confrontés au registre de programme de
  la release et à la visibilité servie (``internal``) ;
* chaque chunk publié est interrogé par son vecteur (périmètre entier, jamais
  un échantillon) et une requête lexicale est posée ;
* aucun candidat ne sort du jeu publié de la collection ; un refus dense n'est
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
RELEASE_V4 = "production-profile-gate-2026-2027-v4"
REGISTRE_PROGRAMME_V4 = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/"
    "release-024f8625ebfeb7ce/profile_gate/programme_registry.json"
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


def sonder(
    racine: Path,
    *,
    connexion: Callable[[], Any],
    modules: Mapping[str, Any] | None = None,
    collections: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Le rapport de sonde ; lève ``SondeEchec`` au premier manquement.

    ``collections`` restreint la sonde (banc) ; par défaut, toutes celles que
    nomme l'autorité de nommage V4 (staging)."""
    modules = modules or _modules()
    configuration = modules["load_collection_config"](racine / CONFIG_COLLECTIONS)
    emis, officiels = scopes_emis(racine), programmes(racine)
    if set(emis) != set(officiels):
        raise SondeEchec("collections : autorité de nommage ≠ registre de programme")
    retenues = sorted(emis) if collections is None else sorted(collections)
    if not set(retenues) <= set(emis):
        raise SondeEchec(f"collections hors de l'autorité de nommage : {sorted(set(retenues) - set(emis))}")
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
    rapport: dict[str, Any] = {"release_id": RELEASE_V4, "collections": {}}
    try:
        for collection in retenues:
            scope = modules["scope"].build_server_retrieval_scope(
                identite_verifiee(modules, emis[collection], role="teacher", secret=secret),
                collection=collection, collection_config=configuration,
            )
            if (scope.programme_version, scope.visibilities) != (officiels[collection], (VISIBILITE_SERVIE,)):
                raise SondeEchec(f"{collection} : scope {scope.programme_version} {scope.visibilities}")
            with connexion() as conn:
                lignes = conn.execute(
                    "SELECT chunk_id, vector::text, text FROM public.rag_chunks"
                    " WHERE collection = %s ORDER BY chunk_id",
                    (collection,),
                ).fetchall()
                conn.rollback()
            if not lignes:
                raise SondeEchec(f"{collection} : aucun chunk publié lisible par rag_reader")
            chunks = {chunk_id: (vecteur, texte) for chunk_id, vecteur, texte in lignes}
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
                if not candidats or any(c.chunk_id not in chunks for c in candidats):
                    raise SondeEchec(f"{collection} {chunk_id[:12]} : candidat hors du jeu publié")
                identiques = [c for c in candidats if c.chunk_id == chunk_id or c.vector == tuple(valeurs)]
                en_tete += candidats[0] in identiques
                retrouves += bool(identiques)
                manques += not identiques
            mots = next((t for _v, t in chunks.values() if len(t.split()) >= 8), "").split()[:8]
            lexicaux = store.lexical(raw_query=" ".join(mots), collection=collection, limit=10) if mots else []
            if any(c.chunk_id not in chunks for c in lexicaux):
                raise SondeEchec(f"{collection} : candidat lexical hors du jeu publié")
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
    args = parser.parse_args(argv)
    import psycopg

    dsn = os.environ.get("PG_RAG_DSN", "").strip()
    if not dsn:
        print("SONDE_ECHEC: PG_RAG_DSN absent", file=sys.stderr)
        return 1
    try:
        rapport = sonder(
            args.repository_root, connexion=lambda: psycopg.connect(dsn),
            collections=args.collection or None,
        )
    except SondeEchec as exc:
        print(f"SONDE_ECHEC: {exc}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SONDE_RETRIEVAL_V4", json.dumps(rapport["totaux"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
