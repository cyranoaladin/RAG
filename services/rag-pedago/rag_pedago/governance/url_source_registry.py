"""Registre des URL sources — la comptabilité des provenances web du corpus.

**Le problème que ce registre existe pour supprimer.** Le corpus scellé
sait d'où viennent ses octets *approximativement* : le catalogue de
moisson conserve, pour chaque document, l'URL de la **page qui le
référence** — sa provenance de navigation. Il ne conserve pas l'URL du
**document lui-même**. Or c'est la seconde, et elle seule, qui permet de
rejouer un téléchargement et de comparer l'empreinte servie aujourd'hui à
l'empreinte scellée. Sans elle, « le corpus est-il encore à jour ? » n'est
pas une question à laquelle on peut répondre : c'est une question qu'on ne
peut même pas poser.

**Ce que le registre garantit.** Une URL découverte quelque part dans les
autorités de gouvernance ne peut pas s'évaporer. Elle finit dans
exactement l'un de trois états *nommés* :

``RESOLUE``
    une URL de document direct est connue ; le registre porte la sonde
    réseau qui l'a rejouée et l'empreinte servie ;
``IRRECUPERABLE``
    l'URL directe est objectivement hors d'atteinte, et l'entrée porte la
    **raison** codée et la **preuve** ;
``EN_ATTENTE``
    non résolue mais résoluble, avec le motif nommé de ce qui manque.

Tout ce qui n'entre dans aucun de ces trois états est compté
``URL_UNACCOUNTED`` et fait échouer la vérification. C'est le seul compteur
dont la valeur admissible est fixée d'avance : zéro. Un registre qui laisse
une URL sans état nommé ne décrit pas un corpus incomplet, il décrit un
corpus dont on ignore ce qu'on ignore.

**Pourquoi « irrécupérable » exige une preuve.** Sans cette contrainte,
``IRRECUPERABLE`` deviendrait la poubelle où l'on range ce qu'on n'a pas
cherché, et ``URL_UNACCOUNTED = 0`` serait obtenu par déplacement plutôt
que par travail. La garde refuse donc toute entrée irrécupérable dont la
raison ou la preuve manque : le coût de classer une URL irrécupérable doit
rester supérieur au coût de la résoudre.

**Pourquoi un 200 muet est refusé.** Une entrée de document direct qui a
répondu 200 mais ne porte pas l'empreinte de ce qui a été servi ne peut pas
être comptée « fraîcheur vérifiée » : elle prouve seulement qu'une URL
répond. Confondre « l'URL existe » et « le contenu n'a pas dérivé » est
précisément l'erreur qui laisserait un corpus périmé se déclarer courant.
La garde refuse donc le 200 sans empreinte servie, et le refuse aussi sans
empreinte scellée à laquelle la comparer.

**Aucun contournement.** Les sondes réseau consignées ici ont été prises
avec un agent identifié et le délai déclaré par ``robots.txt`` du
fournisseur. Un 403 sur une page de navigation est enregistré comme un
403 : c'est un fait sur la protection du fournisseur, pas un obstacle à
franchir. La réparation d'une provenance manquante passe par la remoisson
avec l'outil sanctionné, jamais par la dissimulation du robot.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

REGISTRY_KIND = "URL_SOURCE_REGISTRY_V1"

#: Une entrée irrécupérable doit citer l'une de ces raisons *nommées* — jamais
#: une chaîne arbitraire. Une raison inconnue serait invérifiable, donc
#: équivalente à l'absence de raison que la garde existe pour refuser.
RAISON_IRRECUPERABILITE_NAVIGATION_PROTEGEE = "NAVIGATION_PROTEGEE_403"
RAISON_IRRECUPERABILITE_RELATION_ABSENTE = (
    "RELATION_NAVIGATION_VERS_DOCUMENT_ABSENTE_DES_AUTORITES"
)
RAISONS_IRRECUPERABILITE_CONNUES = frozenset(
    {
        RAISON_IRRECUPERABILITE_NAVIGATION_PROTEGEE,
        RAISON_IRRECUPERABILITE_RELATION_ABSENTE,
    }
)

#: Une preuve d'irrécupérabilité en-deçà de cette longueur ne peut pas citer
#: à la fois un fait mesuré et la politique du fournisseur consultée : elle
#: est une étiquette, pas une preuve.
PREUVE_IRRECUPERABILITE_LONGUEUR_MINIMALE = 40

#: Statut HTTP qu'un code de raison exige de sa propre sonde. Un code qui
#: NOMME un statut et une sonde qui en a relevé un autre se contredisent :
#: l'un des deux est faux, et l'entrée ne prouve plus rien.
STATUT_EXIGE_PAR_RAISON: dict[str, int] = {
    RAISON_IRRECUPERABILITE_NAVIGATION_PROTEGEE: 403,
}

#: Statuts qui disent « pas maintenant », jamais « plus jamais ». Le
#: constructeur les oriente déjà vers EN_ATTENTE ; la garde refuse qu'un
#: registre écrit à la main les range en irrécupérable.
STATUTS_TRANSITOIRES = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Nombre d'autorités dont ce registre est censé dériver : le catalogue de
#: moisson et l'évidence de fraîcheur, chacune scellée par sa propre empreinte.
NOMBRE_AUTORITES_ATTENDU = 2


class RegistreUrlSourceError(RuntimeError):
    """Le registre ne prouve pas ce qu'il affirme — refus explicite."""


class RoleSource(StrEnum):
    """Ce qu'une URL *est*, pas ce à quoi elle sert.

    La distinction porte tout le registre : ``DOCUMENT_DIRECT`` désigne
    des octets rejouables et comparables à un scellé ; les trois autres
    rôles désignent des points d'entrée qui ne rendent jamais l'octet
    scellé, et pour lesquels « vérifier la fraîcheur » n'a pas de sens.
    """

    DOCUMENT_DIRECT = "DOCUMENT_DIRECT"
    NAVIGATION_PROVENANCE = "NAVIGATION_PROVENANCE"
    INTERACTIVE_RESOURCE = "INTERACTIVE_RESOURCE"
    CATALOGUE = "CATALOGUE"


class Resolution(StrEnum):
    """État nommé d'une URL vis-à-vis de la résolution vers le document.

    ``NON_CLASSEE`` n'est pas un état de repli : c'est le marqueur de
    l'absence de classement, seul cas compté ``URL_UNACCOUNTED``. Il
    existe pour que l'oubli soit visible plutôt que silencieux.
    """

    RESOLUE = "RESOLUE"
    IRRECUPERABLE = "IRRECUPERABLE"
    EN_ATTENTE = "EN_ATTENTE"
    NON_CLASSEE = "NON_CLASSEE"


@dataclass(frozen=True)
class EntreeUrl:
    """Une URL distincte et tout ce qui est prouvé à son sujet.

    Les noms des champs de provenance suivent le contrat demandé
    (``source_role``, ``navigation_url``, ``direct_url``, …) ; ils sont
    aussi les clés JSON du registre versionné.
    """

    url: str
    source_role: RoleSource
    resolution: Resolution
    navigation_url: str | None = None
    direct_url: str | None = None
    resolved_url: str | None = None
    status: int | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    retrieved_at: str | None = None
    content_sha256: str | None = None
    artifact_id: str | None = None
    #: Empreinte scellée dans le corpus, à laquelle ``content_sha256``
    #: (l'empreinte servie aujourd'hui) est comparée.
    empreinte_scellee: str | None = None
    #: Artefacts du périmètre gouverné dont cette URL porte la provenance.
    artefacts_perimetre: tuple[str, ...] = ()
    raison_irrecuperabilite: str | None = None
    preuve_irrecuperabilite: str | None = None
    motif_attente: str | None = None
    erreur_reseau: str | None = None

    @property
    def fraicheur_verifiable(self) -> bool:
        """Vrai si la comparaison servi/scellé a un sens pour cette entrée."""
        return (
            self.source_role is RoleSource.DOCUMENT_DIRECT
            and self.status == 200
            and self.content_sha256 is not None
            and self.empreinte_scellee is not None
        )


@dataclass(frozen=True)
class AutoriteSource:
    """Autorité consultée pour découvrir des URL, identifiée par son empreinte."""

    nom: str
    emplacement: str
    sha256: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class RegistreUrlSource:
    registry_kind: str
    perimetre: str
    autorites: list[AutoriteSource]
    entrees: list[EntreeUrl] = field(default_factory=list)


def compter(registre: RegistreUrlSource) -> dict[str, int]:
    """Recalcule les compteurs depuis les entrées — jamais depuis le texte publié.

    ``URL_UNRECOVERABLE`` est un sous-ensemble de ``URL_DIRECT_UNRESOLVED``
    et non une catégorie parallèle : une URL irrécupérable *est* une URL
    non résolue, dont on a en plus démontré qu'elle le restera.
    """
    entrees = registre.entrees
    resolues = [e for e in entrees if e.direct_url is not None]
    non_resolues = [e for e in entrees if e.direct_url is None]
    comptees = [e for e in entrees if _est_comptee(e)]
    directs = [e for e in entrees if e.source_role is RoleSource.DOCUMENT_DIRECT]
    verifiables = [e for e in directs if e.fraicheur_verifiable]
    return {
        "URL_DISCOVERED": len(entrees),
        "URL_DIRECT_RESOLVED": len(resolues),
        "URL_DIRECT_UNRESOLVED": len(non_resolues),
        "URL_UNRECOVERABLE": sum(
            1 for e in entrees if e.resolution is Resolution.IRRECUPERABLE
        ),
        "URL_FETCHED": sum(1 for e in entrees if e.status == 200),
        # Une URL jamais sondée n'est pas « en erreur » : c'est un trou dans
        # la mesure. Les confondre laissait un registre non sondé se
        # présenter comme intégralement sondé et en échec.
        "URL_ERRORS": sum(1 for e in entrees if _sonde_en_echec(e)),
        "URL_UNPROBED": sum(1 for e in entrees if _jamais_sondee(e)),
        "URL_UNACCOUNTED": len(entrees) - len(comptees),
        "CURRENTNESS_VERIFIED": sum(
            1 for e in verifiables if e.content_sha256 == e.empreinte_scellee
        ),
        "CURRENTNESS_DRIFTED": sum(
            1 for e in verifiables if e.content_sha256 != e.empreinte_scellee
        ),
    }


def _jamais_sondee(entree: EntreeUrl) -> bool:
    return entree.status is None and not entree.erreur_reseau


def _sonde_en_echec(entree: EntreeUrl) -> bool:
    if _jamais_sondee(entree):
        return False
    return entree.status != 200 or bool(entree.erreur_reseau)


def _empreinte_sha256_valide(valeur: str | None) -> bool:
    return (
        isinstance(valeur, str)
        and len(valeur) == 64
        and all(caractere in "0123456789abcdef" for caractere in valeur)
    )


def _est_comptee(entree: EntreeUrl) -> bool:
    """Une URL n'est comptée que si son sort porte un nom **et** sa justification."""
    if entree.resolution is Resolution.RESOLUE:
        return entree.direct_url is not None
    if entree.resolution is Resolution.IRRECUPERABLE:
        return bool(entree.raison_irrecuperabilite and entree.preuve_irrecuperabilite)
    if entree.resolution is Resolution.EN_ATTENTE:
        return bool(entree.motif_attente)
    return False


def verifier_registre(registre: RegistreUrlSource) -> dict[str, int]:
    """Refuse tout registre dont une affirmation n'est pas soutenue.

    Renvoie les compteurs recalculés lorsque tout tient. Les manquements
    sont accumulés puis levés ensemble : un registre à réparer se répare
    d'un seul passage, pas par une succession de premières erreurs.
    """
    manquements: list[str] = []

    if registre.registry_kind != REGISTRY_KIND:
        manquements.append(
            f"REGISTRY_KIND_INATTENDU: {registre.registry_kind!r} au lieu de {REGISTRY_KIND!r}"
        )

    if len(registre.autorites) != NOMBRE_AUTORITES_ATTENDU:
        manquements.append(
            f"AUTORITES_INCOMPLETES: {len(registre.autorites)} autorité(s) au lieu de "
            f"{NOMBRE_AUTORITES_ATTENDU}"
        )
    else:
        for autorite in registre.autorites:
            if not _empreinte_sha256_valide(autorite.sha256):
                manquements.append(
                    f"AUTORITE_NON_SCELLEE: {autorite.nom} ({autorite.sha256!r})"
                )

    vues: set[str] = set()
    for entree in registre.entrees:
        if entree.url in vues:
            manquements.append(f"URL_EN_DOUBLE: {entree.url}")
        vues.add(entree.url)
        manquements.extend(_manquements_entree(entree))

    compteurs = compter(registre)
    if compteurs["URL_UNACCOUNTED"] != 0:
        manquements.append(
            f"URL_UNACCOUNTED: {compteurs['URL_UNACCOUNTED']} URL sans sort nommé"
        )
    partition = (
        compteurs["URL_FETCHED"] + compteurs["URL_ERRORS"] + compteurs["URL_UNPROBED"]
    )
    if partition != compteurs["URL_DISCOVERED"]:
        manquements.append(
            f"PARTITION_SONDES_INCOHERENTE: {partition} != {compteurs['URL_DISCOVERED']}"
        )

    if manquements:
        raise RegistreUrlSourceError("; ".join(manquements))
    return compteurs


def _manquements_entree(entree: EntreeUrl) -> list[str]:
    manquements: list[str] = []
    reference = entree.url

    if entree.resolution is Resolution.RESOLUE and entree.direct_url is None:
        manquements.append(f"RESOLUTION_SANS_URL_DIRECTE: {reference}")
    if entree.resolution is Resolution.IRRECUPERABLE:
        if not entree.raison_irrecuperabilite:
            manquements.append(f"RAISON_IRRECUPERABILITE_ABSENTE: {reference}")
        elif entree.raison_irrecuperabilite not in RAISONS_IRRECUPERABILITE_CONNUES:
            manquements.append(
                f"RAISON_IRRECUPERABILITE_INCONNUE: {reference} "
                f"({entree.raison_irrecuperabilite!r})"
            )
        else:
            exige = STATUT_EXIGE_PAR_RAISON.get(entree.raison_irrecuperabilite)
            if exige is not None and entree.status != exige:
                manquements.append(
                    f"RAISON_INCOHERENTE_AVEC_LA_SONDE: {reference} annonce "
                    f"{entree.raison_irrecuperabilite} mais la sonde a relevé "
                    f"{entree.status!r}"
                )
        # Une URL qui répond 200 n'est pas hors d'atteinte : l'entrée se
        # contredirait elle-même, et sa « preuve » attesterait le contraire
        # de ce qu'elle affirme.
        if entree.status == 200 and not entree.erreur_reseau:
            manquements.append(
                f"IRRECUPERABILITE_CONTREDITE_PAR_LA_SONDE: {reference} répond 200"
            )
        if entree.status in STATUTS_TRANSITOIRES:
            manquements.append(
                f"IRRECUPERABILITE_SUR_ECHEC_TRANSITOIRE: {reference} "
                f"(HTTP {entree.status} — relève de EN_ATTENTE)"
            )
        if not entree.preuve_irrecuperabilite:
            manquements.append(f"PREUVE_IRRECUPERABILITE_ABSENTE: {reference}")
        else:
            preuve = entree.preuve_irrecuperabilite
            if len(preuve) < PREUVE_IRRECUPERABILITE_LONGUEUR_MINIMALE:
                manquements.append(f"PREUVE_IRRECUPERABILITE_NON_STRUCTUREE: {reference}")
            if "robots.txt" not in preuve:
                manquements.append(
                    f"PREUVE_IRRECUPERABILITE_SANS_POLITIQUE_ROBOTS: {reference}"
                )
            if not entree.retrieved_at or entree.retrieved_at not in preuve:
                manquements.append(
                    f"PREUVE_IRRECUPERABILITE_SANS_HORODATAGE_SONDE: {reference}"
                )
    if entree.resolution is Resolution.EN_ATTENTE and not entree.motif_attente:
        manquements.append(f"MOTIF_ATTENTE_ABSENT: {reference}")

    # Une URL jamais sondée n'est ni un succès ni une erreur : elle est un
    # trou dans la mesure, et un trou ne se range pas dans une case.
    if entree.status is None and not entree.erreur_reseau:
        manquements.append(f"SONDE_RESEAU_ABSENTE: {reference}")
    if entree.retrieved_at is None:
        manquements.append(f"HORODATAGE_SONDE_ABSENT: {reference}")

    if entree.source_role is RoleSource.DOCUMENT_DIRECT and entree.status == 200:
        if entree.content_sha256 is None:
            manquements.append(f"EMPREINTE_SERVIE_ABSENTE: {reference}")
        if entree.empreinte_scellee is None:
            manquements.append(f"EMPREINTE_SCELLEE_ABSENTE: {reference}")

    return manquements


# --- sérialisation ----------------------------------------------------


def _entree_depuis_dict(brut: dict[str, Any]) -> EntreeUrl:
    return EntreeUrl(
        url=brut["url"],
        source_role=RoleSource(brut["source_role"]),
        resolution=Resolution(brut["resolution"]),
        navigation_url=brut.get("navigation_url"),
        direct_url=brut.get("direct_url"),
        resolved_url=brut.get("resolved_url"),
        status=brut.get("status"),
        content_type=brut.get("content_type"),
        etag=brut.get("etag"),
        last_modified=brut.get("last_modified"),
        retrieved_at=brut.get("retrieved_at"),
        content_sha256=brut.get("content_sha256"),
        artifact_id=brut.get("artifact_id"),
        empreinte_scellee=brut.get("empreinte_scellee"),
        artefacts_perimetre=tuple(brut.get("artefacts_perimetre", ())),
        raison_irrecuperabilite=brut.get("raison_irrecuperabilite"),
        preuve_irrecuperabilite=brut.get("preuve_irrecuperabilite"),
        motif_attente=brut.get("motif_attente"),
        erreur_reseau=brut.get("erreur_reseau"),
    )


def entree_vers_dict(entree: EntreeUrl) -> dict[str, Any]:
    return {
        "url": entree.url,
        "source_role": entree.source_role.value,
        "resolution": entree.resolution.value,
        "navigation_url": entree.navigation_url,
        "direct_url": entree.direct_url,
        "resolved_url": entree.resolved_url,
        "status": entree.status,
        "content_type": entree.content_type,
        "etag": entree.etag,
        "last_modified": entree.last_modified,
        "retrieved_at": entree.retrieved_at,
        "content_sha256": entree.content_sha256,
        "artifact_id": entree.artifact_id,
        "empreinte_scellee": entree.empreinte_scellee,
        "artefacts_perimetre": list(entree.artefacts_perimetre),
        "raison_irrecuperabilite": entree.raison_irrecuperabilite,
        "preuve_irrecuperabilite": entree.preuve_irrecuperabilite,
        "motif_attente": entree.motif_attente,
        "erreur_reseau": entree.erreur_reseau,
    }


def registre_vers_dict(registre: RegistreUrlSource) -> dict[str, Any]:
    return {
        "registry_kind": registre.registry_kind,
        "perimetre": registre.perimetre,
        "autorites": [
            {
                "nom": a.nom,
                "emplacement": a.emplacement,
                "sha256": a.sha256,
                "note": a.note,
            }
            for a in registre.autorites
        ],
        "compteurs": compter(registre),
        "entrees": [entree_vers_dict(e) for e in registre.entrees],
    }


def charger_registre(chemin: Path) -> RegistreUrlSource:
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    return RegistreUrlSource(
        registry_kind=brut["registry_kind"],
        perimetre=brut["perimetre"],
        autorites=[
            AutoriteSource(
                nom=a["nom"],
                emplacement=a["emplacement"],
                sha256=a.get("sha256"),
                note=a.get("note"),
            )
            for a in brut.get("autorites", [])
        ],
        entrees=[_entree_depuis_dict(e) for e in brut["entrees"]],
    )


def ecrire_registre(registre: RegistreUrlSource, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(registre_vers_dict(registre), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def urls_du_registre(entrees: Iterable[EntreeUrl]) -> set[str]:
    return {e.url for e in entrees}
