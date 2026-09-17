#!/usr/bin/env python3
"""Le périmètre servable COURANT, dérivé de la matrice — et de nulle part ailleurs.

Une preuve de couverture n'a de sens que rapportée à l'ensemble qu'elle couvre.
Tant que cet ensemble était recopié en littéral dans les vérificateurs, une
preuve établie sur l'ancien périmètre restait « vraie » après que la matrice
eut changé : le compteur coïncidait avec lui-même, pas avec le présent.

Ce module est la seule dérivation du SERVABLE_CANDIDATE_SET. Les vérificateurs
de recherche (écart, C4) et de stockage (C6) le lisent tous ici, à l'exécution.
Aucun cardinal n'y figure : ni l'ancien, ni le nouveau.

Ne pas confondre avec l'ensemble PROMU d'une release : ce sont deux autorités
distinctes, et aucune ne se déduit du cardinal de l'autre.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"

#: Le seul verdict qui autorise l'indexation. Tout autre verdict est un refus.
VERDICT_CANDIDAT = "CANDIDATE_NO_BLOCKING_DIMENSION"

NOM_PERIMETRE = "SERVABLE_CANDIDATE_SET"

#: Liste POSITIVE des statuts PII qui valent « clair ». Tout statut absent d'ici
#: — REJECTED, PII_UNDECIDED, ou un statut futur que ce code ne connaît pas —
#: est un refus. `!= PII_UNDECIDED` échouerait ouvert sur l'inconnu.
STATUTS_PII_CLAIRS = frozenset({"PII_CLEARED", "PII_CLEARED_OR_NOT_SCANNED"})

CLASSE_PREUVE_PERIMEE = "STALE_PROOF_AFTER_SERVABILITY_SCOPE_CHANGE"
PRIORITE_PREUVE_PERIMEE = "P0_GO_LIVE_GATE_INTEGRITY"


class MatriceInexploitable(RuntimeError):
    """La matrice est absente, vide ou ne porte aucune ligne."""


def empreinte_ensemble(identifiants) -> str:
    """Empreinte stable d'un ensemble d'identifiants.

    Triée, une ligne par identifiant, saut de ligne final. C'est la même
    dérivation que `content_set_digest` du vérificateur CAS : un test les
    confronte, pour qu'un même ensemble n'ait jamais deux empreintes.
    """
    corps = "".join(f"{i}\n" for i in sorted(set(identifiants)))
    return hashlib.sha256(corps.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PerimetreServable:
    contenus: frozenset[str]
    refuses: frozenset[str]
    matrix_sha256: str
    #: Candidats dont le statut PII n'est pas dans la liste positive. Vide par
    #: construction si la matrice est saine ; le vérifier coûte une ligne.
    pii_non_clairs: frozenset[str] = frozenset()

    @property
    def count(self) -> int:
        return len(self.contenus)

    @property
    def digest(self) -> str:
        return empreinte_ensemble(self.contenus)

    def en_dict(self) -> dict:
        return {
            "name": NOM_PERIMETRE,
            "count": self.count,
            "content_set_sha256": self.digest,
            "matrix_sha256": self.matrix_sha256,
            "authority_source": MATRICE,
        }


def perimetre_courant(racine: Path) -> PerimetreServable:
    chemin = racine / MATRICE
    if not chemin.is_file():
        raise MatriceInexploitable(f"matrice absente : {chemin}")
    octets = chemin.read_bytes()
    lignes = json.loads(octets.decode("utf-8")).get("rows") or []
    if not lignes:
        raise MatriceInexploitable(f"matrice sans ligne : {chemin}")
    candidats = frozenset(
        ligne["content_sha256"] for ligne in lignes if ligne["verdict"] == VERDICT_CANDIDAT
    )
    refuses = frozenset(
        ligne["content_sha256"] for ligne in lignes if ligne["verdict"] != VERDICT_CANDIDAT
    )
    return PerimetreServable(
        pii_non_clairs=frozenset(
            ligne["content_sha256"]
            for ligne in lignes
            if ligne["verdict"] == VERDICT_CANDIDAT
            and ligne.get("pii") not in STATUTS_PII_CLAIRS
        ),
        contenus=candidats,
        refuses=refuses,
        # Empreinte des OCTETS du fichier : le champ MATRIX_SHA256 interne est
        # une déclaration, et une déclaration ne lie pas une preuve à un état.
        matrix_sha256=hashlib.sha256(octets).hexdigest(),
    )
