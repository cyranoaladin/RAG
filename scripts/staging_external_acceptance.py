#!/usr/bin/env python3
"""Recette d'un agent EXTÉRIEUR contre un staging déjà déployé.

Ce que ce banc mesure, et rien d'autre : depuis un client hors du réseau et
hors du conteneur du service, muni des seuls credentials qu'on lui a remis,
peut-il obtenir des réponses **citées** sur des questions réelles ?

Il ne construit ni requête ni transport à lui : il réutilise
``scripts/rag_query_external.py``, le client externe livré. Redéfinir ici la
forme du contrat ou les en-têtes ferait deux vérités, et la recette finirait
par valider son propre simulacre plutôt que le service.

**Aucune donnée n'est écrite, aucune base n'est touchée.** Le banc lit.

**Une portée par exécution.** Le jeton d'identité (`RAG_IDENTITY_TOKEN`) est
émis pour UNE portée : prétendre en couvrir trois d'un seul appel serait une
fiction. La recette complète se fait donc en autant d'exécutions que de
portées, chacune avec son identité — c'est exactement ce qu'un agent extérieur
vit.

Usage :

    RAG_API_URL=https://rag-staging.exemple \\
    RAG_BFF_SERVICE_TOKEN=… RAG_API_KEY=… RAG_IDENTITY_TOKEN=… \\
    python scripts/staging_external_acceptance.py --scope prod_nsi_terminale_specialite_v1

Sortie : un bloc de mesures, jamais un secret.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from rag_query_external import (  # noqa: E402
    HTTP_TIMEOUT_SECONDS,
    ExternalClientConfig,
    RagQueryExternalClientError,
    available_scopes,
    build_request,
    load_external_client_config,
    post_search,
)

sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / "contracts" / "src"))

from nexus_contracts import (  # noqa: E402
    RetrievalResponse,
    RetrievalScopeArtifactV2,
    load_retrieval_scope_artifact,
)

#: Une vraie question par collection servable. Ce ne sont pas des sondes
#: techniques : chacune est une question qu'un élève pose, dans sa matière et
#: à son niveau. Une collection absente de cette table n'a pas de question, et
#: la recette le dit au lieu d'en inventer une générique — une question
#: générique reviendrait à mesurer que le service répond, pas qu'il enseigne.
QUESTIONS_BY_COLLECTION: dict[str, str] = {
    "rag_nexus_nsi_terminale_specialite": (
        "Comment le programme de terminale aborde-t-il les bases de données et SQL ?"
    ),
    "rag_nexus_nsi_premiere_specialite": (
        "Quelles notions de programmation et d'algorithmique sont étudiées en première ?"
    ),
    "rag_nexus_maths_terminale_gen_specialite": (
        "Comment le programme de terminale traite-t-il probabilités et statistiques ?"
    ),
    "rag_nexus_maths_premiere_gen_specialite": (
        "Quelle place occupent les probabilités conditionnelles en première ?"
    ),
    "rag_nexus_maths_seconde_tc": (
        "Comment le programme aborde-t-il les vecteurs et la géométrie repérée en seconde ?"
    ),
    "rag_nexus_francais_premiere_tc": (
        "Comment l'étude de la langue est-elle conduite en classe de première ?"
    ),
    "rag_nexus_francais_seconde_tc": (
        "Quel est le programme de français en classe de seconde générale et technologique ?"
    ),
    "rag_nexus_pc_terminale_specialite": (
        "Quel est le programme de spécialité physique-chimie en terminale générale ?"
    ),
    "rag_nexus_svt_terminale_specialite": (
        "Quels thèmes le programme de spécialité SVT couvre-t-il en terminale ?"
    ),
    "rag_nexus_ses_terminale_specialite": (
        "Quels chapitres de sciences économiques et sociales sont au programme de terminale ?"
    ),
    "rag_nexus_hlp_premiere_specialite": (
        "Quels objets d'étude le programme d'humanités, littérature et philosophie "
        "fixe-t-il en première ?"
    ),
    "rag_nexus_philo_terminale_tc": (
        "Quelles notions le programme de philosophie de terminale met-il au programme ?"
    ),
    "rag_nexus_dgemc_terminale_option": (
        "Que prévoit le programme de droit et grands enjeux du monde contemporain ?"
    ),
}


@dataclass(frozen=True)
class AcceptanceCase:
    """Une question réelle, la portée qui l'autorise, et sa collection."""

    scope_id: str
    collection: str
    query: str


def build_case(scope_id: str) -> AcceptanceCase:
    """Construire le cas d'une portée, ou dire pourquoi il n'y en a pas."""
    artifact = load_retrieval_scope_artifact(scope_id)
    if not isinstance(artifact, RetrievalScopeArtifactV2):
        raise AcceptanceError(f"{scope_id} n'est pas un scope V2")
    collection = str(artifact.evidence_subject.collection)
    query = QUESTIONS_BY_COLLECTION.get(collection)
    if query is None:
        raise AcceptanceError(
            f"aucune question pédagogique déclarée pour {collection} — "
            "en inventer une générique mesurerait que le service répond, "
            "pas qu'il enseigne"
        )
    return AcceptanceCase(scope_id=scope_id, collection=collection, query=query)


class AcceptanceError(RuntimeError):
    """La recette ne peut pas conclure — jamais un « PASS » par défaut."""


def get_json(config: ExternalClientConfig, route: str) -> object:
    """Lire une route GET gouvernée avec les TROIS credentials du contrat.

    Aucun repli : le service exige les trois, et un banc qui n'en enverrait
    que deux mesurerait un 401 au lieu de la route.
    """
    request = urllib.request.Request(
        f"{config.api_url}{route}",
        headers={
            "Authorization": f"Bearer {config.bff_token}",
            "X-Nexus-Identity": config.identity_token,
            "X-RAG-API-Key": config.api_key,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise AcceptanceError(f"{route} HTTP {response.status}")
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise AcceptanceError(f"{route} HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise AcceptanceError(f"{route} injoignable") from None
    except ValueError:
        raise AcceptanceError(f"{route} n'a pas rendu du JSON") from None


def check_health(config: ExternalClientConfig) -> None:
    """`/health` EST la sonde de disponibilité de ce service.

    Il n'y a pas de `/ready` distinct, et il n'en faut pas : `/health` valide
    déjà les autorités de runtime, les artefacts de modèle, la réconciliation
    de base et la dimension d'embedding, et rend 503 sinon. C'est la sonde que
    le healthcheck du Compose interroge.
    """
    request = urllib.request.Request(f"{config.api_url}/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise AcceptanceError(f"/health HTTP {response.status}")
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise AcceptanceError(f"/health HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise AcceptanceError("/health injoignable") from None
    if payload.get("status") != "healthy":
        raise AcceptanceError(f"/health rend {payload.get('status')!r}")


def check_taxonomy(config: ExternalClientConfig, *, expected: str | None = None) -> int:
    """La taxonomie doit être typée ET non vide.

    Une taxonomie vide en 200 est indistinguable d'un compte légitimement
    vide : un agent extérieur qui la reçoit croit que rien ne lui est
    servable. Le banc refuse ce silence.
    """
    payload = get_json(config, "/taxonomy/v2")
    if not isinstance(payload, dict):
        raise AcceptanceError("/taxonomy/v2 n'a pas rendu un objet")
    if payload.get("version") != 2:
        raise AcceptanceError("/taxonomy/v2 n'annonce pas sa version")
    collections = payload.get("collections")
    if not isinstance(collections, list) or not collections:
        raise AcceptanceError("/taxonomy/v2 n'annonce aucune collection servable")
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions.get("matiere"):
        raise AcceptanceError("/taxonomy/v2 n'annonce aucune dimension")
    if expected is not None:
        annoncees = {
            item.get("collection")
            for item in collections
            if isinstance(item, dict)
        }
        if expected not in annoncees:
            raise AcceptanceError(
                f"/taxonomy/v2 n'annonce pas {expected} — interroger une "
                "collection que le service ne déclare pas servable mesurerait "
                "autre chose que ce qu'il promet"
            )
    return len(collections)


def check_search(
    config: ExternalClientConfig, case: AcceptanceCase
) -> tuple[int, int]:
    """Une question réelle, servie et **citée**. Rend (résultats, citations)."""
    artifact = load_retrieval_scope_artifact(case.scope_id)
    if not isinstance(artifact, RetrievalScopeArtifactV2):
        raise AcceptanceError(f"{case.scope_id} n'est pas un scope V2")
    try:
        response: RetrievalResponse = post_search(
            build_request(case.query, artifact), config=config
        )
    except RagQueryExternalClientError as exc:
        raise AcceptanceError(f"{case.scope_id} : {exc}") from None

    if not response.results:
        raise AcceptanceError(f"{case.scope_id} : aucun résultat servi")

    expected_collection = str(artifact.evidence_subject.collection)
    citations = 0
    for result in response.results:
        collection = result.metadata.get("collection")
        if collection != expected_collection:
            raise AcceptanceError(
                f"{case.scope_id} : résultat hors portée ({collection!r})"
            )
        citation = result.citation
        if citation is None:
            raise AcceptanceError(f"{case.scope_id} : un résultat sans citation")
        if not citation.source_uri or citation.page is None:
            raise AcceptanceError(
                f"{case.scope_id} : citation sans source ni page — elle n'étaye rien"
            )
        citations += 1
    return len(response.results), citations


def run(config: ExternalClientConfig, case: AcceptanceCase) -> dict[str, object]:
    check_health(config)
    servable = check_taxonomy(config, expected=case.collection)
    results, citations = check_search(config, case)
    return {
        "scope": case.scope_id,
        "collection": case.collection,
        "servable_collections": servable,
        "results": results,
        "citations": citations,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        required=True,
        choices=available_scopes(),
        help="la portée que le jeton d'identité fourni couvre",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        case = build_case(arguments.scope)
        # Les credentials sont exigés AVANT tout appel réseau : « Unauthorized »
        # côté serveur ne dirait pas lequel manque.
        config = load_external_client_config()
        measures = run(config, case)
    except (AcceptanceError, RagQueryExternalClientError) as exc:
        print("EXTERNAL_AGENT_E2E=FAIL")
        print(f"REASON={exc}")
        return 3

    print("EXTERNAL_AGENT_E2E=PASS")
    for name, value in measures.items():
        print(f"{name.upper()}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
