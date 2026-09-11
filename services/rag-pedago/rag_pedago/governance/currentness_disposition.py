"""Applique la politique d'actualité, et rien d'autre qu'elle.

Cette logique vivait dans une épreuve, avec ce commentaire : « elle vit ici,
pas dans le plan de contrôle, parce que la politique n'est pas adoptée. La
coder dans le producteur reviendrait à l'appliquer. » C'est exact — et c'est
précisément ce que ce module fait, maintenant que la politique est adoptée.

Ce qu'il produit : **une disposition d'actualité**. Une seule dimension.

Ce qu'il ne produit jamais :

- un verdict de servabilité. Composer les autorités appartient au gate de
  servabilité, pas à la politique. Une politique d'actualité qui refuserait un
  document pour une raison de PII n'aurait pas renforcé la PII : elle aurait
  créé un second endroit où la PII se décide, et deux endroits qui décident
  finissent par décider différemment ;
- `VERIFIED_CURRENT` sans identité d'octets. Autoriser à servir n'est pas
  prouver l'actualité, et confondre les deux ferait passer un instantané pour
  une vérification ;
- la résurrection d'une archive. Ne pas pouvoir vérifier une URL n'annule pas
  une déclaration positive d'archivage : l'absence de preuve réseau n'est pas
  une preuve d'obsolescence, et elle n'est pas davantage une preuve d'actualité.

Le module refuse de s'appliquer tant que la politique ne se déclare pas
appliquée. Un module qui appliquerait une proposition la rendrait effective
sans l'ADR qui l'adopte.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

#: Les quatre dispositions d'actualité. Aucune autre n'est admise.
VERIFIED_CURRENT = "VERIFIED_CURRENT"
OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE = "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"
NOT_CURRENT_DECLARED_BY_SOURCE = "NOT_CURRENT_DECLARED_BY_SOURCE"
UNKNOWN = "UNKNOWN"

DISPOSITIONS = frozenset(
    {
        VERIFIED_CURRENT,
        OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE,
        NOT_CURRENT_DECLARED_BY_SOURCE,
        UNKNOWN,
    }
)

#: Statut de source qui déclare positivement l'archivage. Le repli ne le
#: renverse jamais.
STATUT_ARCHIVE = "ARCHIVE"

#: Conditions que la politique sait évaluer elle-même. Toute autre condition
#: dans sa règle de repli appartiendrait à une autre autorité.
CONDITIONS_CONNUES = frozenset(
    {
        "OFFICIAL_INSTITUTIONAL_PROVENANCE",
        "CONTENT_SHA_PROVENANCE_MATCH",
        "SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE",
        "NO_KNOWN_SUPERSEDING_CONFLICT",
    }
)

CHEMIN_POLITIQUE = (
    Path(__file__).resolve().parents[2]
    / "configs/proposals/nexus_rag_currentness_policy_v1.yml"
)


class PolitiqueNonAppliquee(RuntimeError):
    """La politique n'est pas adoptée : rien ne peut s'en réclamer."""


class PolitiqueInvalide(RuntimeError):
    """La politique dit quelque chose qu'elle n'a pas le droit de dire."""


def charger_politique(chemin: Path | None = None) -> Mapping[str, Any]:
    """Charge la politique et REFUSE si elle ne s'applique pas.

    Le refus est la valeur par défaut. Une politique absente, illisible, ou qui
    se déclare proposition, ne peut pas produire de disposition : sans cela, un
    fichier effacé rendrait tout le monde « actuel » en silence.
    """
    chemin = chemin or CHEMIN_POLITIQUE
    if not chemin.is_file():
        raise PolitiqueNonAppliquee(f"politique d'actualité absente : {chemin}")
    document = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise PolitiqueNonAppliquee(f"politique d'actualité illisible : {chemin}")
    if document.get("applied") is not True:
        raise PolitiqueNonAppliquee(
            "la politique d'actualité n'est pas appliquée "
            f"(applied={document.get('applied')!r}) : aucune disposition ne peut "
            "s'en réclamer"
        )
    _verifier_perimetre(document)
    return document


def _verifier_perimetre(politique: Mapping[str, Any]) -> None:
    """Refuse une politique qui s'arrogerait une décision étrangère."""
    repli = politique.get("fallback_rule") or {}
    exigees = list(repli.get("conditions_all_required") or [])
    if not exigees:
        raise PolitiqueInvalide("la règle de repli n'exige aucune condition")
    etrangeres = sorted(set(exigees) - CONDITIONS_CONNUES)
    if etrangeres:
        raise PolitiqueInvalide(
            "la règle de repli exige des conditions que la politique d'actualité "
            f"ne sait pas évaluer : {etrangeres}. Elles appartiennent à d'autres "
            "autorités et doivent leur être rendues."
        )
    if repli.get("disposition") == VERIFIED_CURRENT:
        raise PolitiqueInvalide(
            "le repli ne peut pas produire VERIFIED_CURRENT : autoriser à servir "
            "n'est pas prouver l'actualité"
        )


def disposition_actualite(
    cas: Mapping[str, Any], politique: Mapping[str, Any]
) -> str:
    """Rend la SEULE sortie de la politique : une disposition d'actualité.

    L'ordre des règles porte le sens :

    1. une archive déclarée par la source le reste, quoi qu'en dise le réseau ;
    2. une identité d'octets prouve l'actualité — c'est la seule chose qui la
       prouve ;
    3. à défaut, le repli, si toutes ses conditions d'actualité tiennent ;
    4. sinon, l'inconnu — jamais l'obsolescence, qui serait une affirmation.
    """
    if cas.get("source_status") == STATUT_ARCHIVE:
        return NOT_CURRENT_DECLARED_BY_SOURCE
    if cas.get("content_identity_match") is True:
        return VERIFIED_CURRENT

    repli = politique["fallback_rule"]
    satisfaites = {
        "OFFICIAL_INSTITUTIONAL_PROVENANCE": cas.get("official_provenance") is True,
        "CONTENT_SHA_PROVENANCE_MATCH": cas.get("sha_provenance_match") is True,
        "SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE": cas.get("source_status") != STATUT_ARCHIVE,
        "NO_KNOWN_SUPERSEDING_CONFLICT": not cas.get("superseding_conflict", False),
    }
    exigees = repli["conditions_all_required"]
    if all(satisfaites[nom] for nom in exigees):
        return repli["disposition"]
    return UNKNOWN
