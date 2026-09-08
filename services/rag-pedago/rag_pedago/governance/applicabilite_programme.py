"""Applicabilité d'un programme à un scope, et NIVEAU DE PREUVE de ce fait.

``NEXUS-PROGRAM-APPLICABILITY-EVIDENCE-V1``.

Deux choses que ce module refuse de confondre.

1. **La vérification officielle** — le canal commanditaire a lu le texte
   officiel et rapporte ce qu'il dit. C'est un fait vérifié.
2. **La reproductibilité locale du fetch** — cette session peut-elle
   re-télécharger les octets officiels et les rehacher ? C'est une propriété du
   RÉSEAU, pas du fait.

Les fondre dans un seul drapeau ferait rétrograder un fait vérifié au motif
qu'un serveur rend 403 à un agent non navigateur, ou — pire dans l'autre sens —
ferait passer pour vérifié tout ce qui a pu être téléchargé. Les deux
propriétés sont donc portées séparément, et
``local_official_evidence_reproducible`` n'entre dans aucune décision de
statut.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

CONTRACT_ID = "NEXUS-PROGRAM-APPLICABILITY-EVIDENCE-V1"

#: Enum FERMÉE des niveaux de preuve d'une applicabilité.
DECLARE = "DECLARED_BY_COMMANDITAIRE"
VERIFIE_OFFICIEL = "VERIFIED_OFFICIAL_BY_COMMANDITAIRE"
EN_ATTENTE = "PENDING_AUTHORITY_LOOKUP"
STATUTS_PREUVE = (DECLARE, VERIFIE_OFFICIEL, EN_ATTENTE)

#: Seul ce niveau autorise un verdict d'INCOMPATIBILITÉ. Un fait déclaré peut
#: nourrir une hypothèse ; il ne peut pas condamner un artefact.
STATUTS_OPPOSABLES = (VERIFIE_OFFICIEL,)

#: Les champs sans lesquels « vérifié » ne veut rien dire. Un statut vérifié
#: qui ne nomme ni le texte, ni son NOR, ni sa date d'entrée en vigueur, ni la
#: date de vérification, ni le reçu, est une affirmation sans prise.
CHAMPS_REQUIS_POUR_VERIFIE = (
    "official_reference", "nor", "effective_from",
    "official_source_identifier", "verified_at", "evidence_receipt_sha256",
)


@dataclass(frozen=True)
class ApplicabiliteProgramme:
    """Un programme applicable à un scope précis, avec son niveau de preuve."""

    scope_id: str
    niveau: str
    matiere: str
    modality: str | None
    school_year: str
    official_reference: str | None
    nor: str | None
    official_reference_kind: str | None
    effective_from: str | None
    official_source_identifier: str | None
    verified_at: str | None
    evidence_receipt_sha256: str | None
    evidence_status: str
    #: Propriété du RÉSEAU, jamais du fait. Ne participe à aucune décision.
    local_official_evidence_reproducible: bool = False
    official_snapshot_sha256: str | None = None
    supersedes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.evidence_status not in STATUTS_PREUVE:
            raise ValueError(f"statut de preuve hors enum fermée : {self.evidence_status}")
        if self.evidence_status == VERIFIE_OFFICIEL:
            manquants = [c for c in CHAMPS_REQUIS_POUR_VERIFIE if not getattr(self, c)]
            if manquants:
                raise ValueError(
                    f"{self.scope_id} : « vérifié » sans {', '.join(manquants)}")
        if self.official_snapshot_sha256 and not self.local_official_evidence_reproducible:
            raise ValueError(
                f"{self.scope_id} : une empreinte d'instantané officiel sans "
                "reproductibilité locale déclarée serait une preuve sans provenance")

    @property
    def opposable(self) -> bool:
        """Ce fait peut-il fonder une INCOMPATIBILITÉ ?

        Ne consulte jamais ``local_official_evidence_reproducible`` : un fait
        vérifié le reste quand le réseau refuse, et un fetch réussi ne vérifie
        rien à lui seul."""
        return self.evidence_status in STATUTS_OPPOSABLES


def receipt_sha256(*champs: str) -> str:
    """Le reçu d'une vérification : l'empreinte de ce qui a été rapporté.

    Le reçu scelle le CONTENU du rapport, pas son transport. Deux
    vérifications qui rapportent la même chose ont le même reçu, et une
    vérification dont un champ change en a un autre — c'est ce qui rend un
    changement silencieux impossible."""
    graine = "\n".join((CONTRACT_ID, *champs)) + "\n"
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()


# --- LCA : trois familles de scopes, jamais une seule ------------------------
#
# Le défaut que cette séparation empêche : « matiere=lca » traité comme un
# scope. L'enseignement de complément du cycle 4, l'option de lycée et la
# spécialité LLCA relèvent de textes DIFFÉRENTS, et l'option de lycée relève
# elle-même de deux textes selon le niveau. Les confondre attribuerait à un
# document de collège un programme de terminale.

LCA_CYCLE4_COMPLEMENT = "LCA_CYCLE4_COMPLEMENT"
LCA_GT_OPTION_SECONDE = "LCA_GT_OPTION_SECONDE"
LCA_GT_OPTION_PREMIERE = "LCA_GT_OPTION_PREMIERE"
LCA_GT_OPTION_TERMINALE = "LCA_GT_OPTION_TERMINALE"
LLCA_SPECIALITE_PREMIERE = "LLCA_SPECIALITE_PREMIERE"
LLCA_SPECIALITE_TERMINALE = "LLCA_SPECIALITE_TERMINALE"
SCOPES_LCA = (
    LCA_CYCLE4_COMPLEMENT,
    LCA_GT_OPTION_SECONDE, LCA_GT_OPTION_PREMIERE, LCA_GT_OPTION_TERMINALE,
    LLCA_SPECIALITE_PREMIERE, LLCA_SPECIALITE_TERMINALE,
)

#: Disposition d'un artefact dont les métadonnées ne suffisent pas à choisir.
LCA_MODALITE_INCONNUE = "LCA_SCOPE_MODALITY_UNKNOWN"

_LCA_PAR_CLE: dict[tuple[str, str], str] = {
    ("cycle_4", "ENSEIGNEMENT_COMPLEMENT_LCA"): LCA_CYCLE4_COMPLEMENT,
    ("cinquieme", "ENSEIGNEMENT_COMPLEMENT_LCA"): LCA_CYCLE4_COMPLEMENT,
    ("quatrieme", "ENSEIGNEMENT_COMPLEMENT_LCA"): LCA_CYCLE4_COMPLEMENT,
    ("troisieme", "ENSEIGNEMENT_COMPLEMENT_LCA"): LCA_CYCLE4_COMPLEMENT,
    ("seconde", "LCA_OPTION"): LCA_GT_OPTION_SECONDE,
    ("premiere", "LCA_OPTION"): LCA_GT_OPTION_PREMIERE,
    ("terminale", "LCA_OPTION"): LCA_GT_OPTION_TERMINALE,
    ("premiere", "LLCA_SPECIALITE"): LLCA_SPECIALITE_PREMIERE,
    ("terminale", "LLCA_SPECIALITE"): LLCA_SPECIALITE_TERMINALE,
}


def resoudre_scope_lca(niveau: str | None, modality: str | None) -> str:
    """Le scope LCA exact, ou ``LCA_SCOPE_MODALITY_UNKNOWN``.

    Une nouvelle autorité permet de résoudre des scopes précis ; elle ne
    transforme pas des métadonnées pauvres en preuve. Un artefact qui porte
    seulement ``matiere=lca`` reste sans scope — et sans programme."""
    if not niveau or not modality:
        return LCA_MODALITE_INCONNUE
    return _LCA_PAR_CLE.get((niveau, modality), LCA_MODALITE_INCONNUE)


def autorite_applicable(
    scope_id: str, applicabilites: Sequence[ApplicabiliteProgramme],
) -> ApplicabiliteProgramme | None:
    correspondances = [a for a in applicabilites if a.scope_id == scope_id]
    if len(correspondances) == 1:
        return correspondances[0]
    return None


__all__ = [
    "CHAMPS_REQUIS_POUR_VERIFIE", "CONTRACT_ID", "DECLARE", "EN_ATTENTE",
    "LCA_CYCLE4_COMPLEMENT", "LCA_GT_OPTION_PREMIERE", "LCA_GT_OPTION_SECONDE",
    "LCA_GT_OPTION_TERMINALE", "LCA_MODALITE_INCONNUE",
    "LLCA_SPECIALITE_PREMIERE", "LLCA_SPECIALITE_TERMINALE",
    "SCOPES_LCA", "STATUTS_OPPOSABLES", "STATUTS_PREUVE", "VERIFIE_OFFICIEL",
    "ApplicabiliteProgramme", "autorite_applicable", "receipt_sha256",
    "resoudre_scope_lca",
]
