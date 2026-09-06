"""Disposition de fraîcheur, un objet gouverné à la fois.

`URL_UNACCOUNTED=0` dit que chaque URL a un état. Ce n'est pas la même
question que « chaque ARTEFACT scellé a-t-il une disposition ? ». Un artefact
peut être couvert par une URL comptée et rester, lui, sans réponse : c'est
exactement le silence que ce module refuse.

Quatre dispositions, et rien d'autre :

``VERIFIED_CURRENT``
    Une URL de document direct a été rejouée et l'empreinte servie est
    **identique** à l'empreinte scellée. « L'URL répond » ne suffit pas : sans
    empreinte servie, il n'y a pas de vérification, seulement un ping.

``UNRECOVERABLE_WITH_EVIDENCE``
    Aucune URL directe n'existe plus, et la provenance de navigation est
    irrécupérable — avec sa raison codée **et** sa preuve. La preuve est
    exigée pour que cette case ne devienne pas l'endroit où l'on range ce
    qu'on n'a pas cherché.

``NON_URL_STATIC_SOURCE``
    L'objet ne vient d'aucune URL : sa provenance est un dépôt statique
    gouverné. Il n'a pas de fraîcheur réseau à vérifier ; le dire est une
    réponse, pas une échappatoire.

``INTERACTIVE_RESOURCE_VERIFIED``
    Ressource interactive dont l'identité n'est pas un fichier téléchargeable.

Ce qui n'entre dans aucune est compté ``CURRENTNESS_UNACCOUNTED`` et fait
**refuser** le registre. C'est le seul compteur dont la valeur admissible est
fixée d'avance.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

LEDGER_KIND = "CURRENTNESS_DISPOSITION_V1"

#: Un appui « irrécupérable » doit citer un condensé vérifiable de la preuve
#: qui l'a produit, pas seulement les raisons codées : sans lui, la preuve
#: existe dans le registre d'URL mais disparaît du jugement qui s'en sert.
_PREUVE_DIGEST_RE = re.compile(r"preuve=[0-9a-f]{64}$")


class DispositionError(RuntimeError):
    """Une disposition manque, ou n'est pas soutenue par ce qu'elle prétend."""


class Disposition(StrEnum):
    VERIFIED_CURRENT = "VERIFIED_CURRENT"
    UNRECOVERABLE_WITH_EVIDENCE = "UNRECOVERABLE_WITH_EVIDENCE"
    NON_URL_STATIC_SOURCE = "NON_URL_STATIC_SOURCE"
    INTERACTIVE_RESOURCE_VERIFIED = "INTERACTIVE_RESOURCE_VERIFIED"


@dataclass(frozen=True)
class DispositionArtefact:
    """La disposition d'UN artefact scellé, et ce qui la soutient."""

    content_sha256: str
    disposition: Disposition
    #: Les URL du registre qui portent la provenance de cet artefact.
    urls: tuple[str, ...]
    #: Ce qui soutient la disposition : empreinte servie, raison + preuve
    #: d'irrécupérabilité, ou nature de la source.
    appui: str


def _entrees_par_artefact(
    entrees: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    index: dict[str, list[Mapping[str, Any]]] = {}
    for entree in entrees:
        for sha in entree.get("artefacts_perimetre") or ():
            index.setdefault(str(sha), []).append(entree)
    return index


def _disposition_dun_artefact(
    artefact: Mapping[str, Any], entrees: Sequence[Mapping[str, Any]]
) -> DispositionArtefact:
    sha = str(artefact["content_sha256"])
    urls = tuple(sorted(str(entree["url"]) for entree in entrees))

    # 1. Vérifié : une URL directe a rendu EXACTEMENT l'empreinte scellée.
    #    Les quatre conditions sont nécessaires ensemble : sans elles, un
    #    « RESOLUE » qui ne serait pas un téléchargement direct réussi
    #    pourrait produire VERIFIED_CURRENT sur la seule coïncidence des
    #    empreintes.
    for entree in entrees:
        if (
            entree.get("resolution") == "RESOLUE"
            and entree.get("source_role") == "DOCUMENT_DIRECT"
            and entree.get("status") == 200
            and entree.get("direct_url")
            and entree.get("content_sha256")
            and entree.get("content_sha256") == entree.get("empreinte_scellee") == sha
        ):
            return DispositionArtefact(
                content_sha256=sha,
                disposition=Disposition.VERIFIED_CURRENT,
                urls=urls,
                appui=f"empreinte servie identique à l'empreinte scellée ({sha[:12]}…)",
            )

    # 2. Irrécupérable : toutes les provenances le sont, chacune avec raison
    #    ET preuve. Une seule sans preuve suffit à refuser la disposition.
    irrecuperables = [
        entree for entree in entrees if entree.get("resolution") == "IRRECUPERABLE"
    ]
    if irrecuperables and len(irrecuperables) == len(entrees):
        sans_preuve = [
            str(entree["url"])
            for entree in irrecuperables
            if not entree.get("raison_irrecuperabilite")
            or not entree.get("preuve_irrecuperabilite")
        ]
        if sans_preuve:
            raise DispositionError(
                f"{sha[:12]}… : irrécupérable sans preuve pour "
                f"{', '.join(sans_preuve[:3])}"
            )
        raisons = sorted({str(e["raison_irrecuperabilite"]) for e in irrecuperables})
        preuve_digest = hashlib.sha256(
            "|".join(
                sorted(str(e["preuve_irrecuperabilite"]) for e in irrecuperables)
            ).encode("utf-8")
        ).hexdigest()
        return DispositionArtefact(
            content_sha256=sha,
            disposition=Disposition.UNRECOVERABLE_WITH_EVIDENCE,
            urls=urls,
            appui=(
                f"{len(irrecuperables)} provenance(s) irrécupérable(s) : "
                + ", ".join(raisons)
                + f" ; preuve={preuve_digest}"
            ),
        )

    # 3. Sans URL du tout : source statique gouvernée — mais seulement si
    #    l'autorité de l'artefact le déclare explicitement. L'absence de
    #    provenance URL ne prouve rien par elle-même : elle peut tout aussi
    #    bien signaler une régression de jointure dans le registre d'URL, et
    #    confondre les deux laisserait cette régression passer pour une
    #    disposition mesurée.
    if not entrees:
        marqueur = artefact.get("non_url_static_source")
        if not marqueur:
            raise DispositionError(
                f"{sha[:12]}… : aucune provenance URL et aucune déclaration "
                "explicite de source statique gouvernée "
                "(non_url_static_source) par l'autorité de l'artefact — une "
                "régression du registre d'URL ne peut pas être prise pour "
                "une preuve"
            )
        return DispositionArtefact(
            content_sha256=sha,
            disposition=Disposition.NON_URL_STATIC_SOURCE,
            urls=(),
            appui=f"source statique gouvernée déclarée par l'autorité : {marqueur}",
        )

    # 4. Ni vérifié, ni entièrement irrécupérable, ni sans URL : le cas est
    #    ouvert. On ne le range pas d'office — on le nomme.
    raise DispositionError(
        f"{sha[:12]}… : aucune disposition ne s'applique — "
        + ", ".join(
            f"{entree['url']}={entree.get('resolution')}" for entree in entrees[:3]
        )
    )


def construire_registre(
    *,
    artefacts: Sequence[Mapping[str, Any]],
    entrees_url: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Rendre une disposition par artefact scellé, ou échouer en la nommant."""
    if not artefacts:
        raise DispositionError("aucun artefact scellé : le périmètre serait vide")
    index = _entrees_par_artefact(entrees_url)
    dispositions = [
        _disposition_dun_artefact(artefact, index.get(str(artefact["content_sha256"]), []))
        for artefact in artefacts
    ]
    comptes = {disposition.value: 0 for disposition in Disposition}
    for item in dispositions:
        comptes[item.disposition.value] += 1
    total = len(dispositions)
    accounted = sum(comptes.values())
    return {
        "ledger_kind": LEDGER_KIND,
        "artefacts": total,
        "comptes": comptes,
        "CURRENTNESS_ACCOUNTED": accounted,
        "CURRENTNESS_UNACCOUNTED": total - accounted,
        "dispositions": [
            {
                "content_sha256": item.content_sha256,
                "disposition": item.disposition.value,
                "urls": list(item.urls),
                "appui": item.appui,
            }
            for item in sorted(dispositions, key=lambda item: item.content_sha256)
        ],
    }


def verifier_registre(registre: Mapping[str, Any]) -> dict[str, int]:
    """Refuser un registre qui laisserait un objet gouverné sans disposition."""
    if registre.get("ledger_kind") != LEDGER_KIND:
        raise DispositionError("nature de registre inattendue")
    dispositions = registre.get("dispositions")
    if not isinstance(dispositions, list) or not dispositions:
        raise DispositionError("registre sans disposition")
    connues = {disposition.value for disposition in Disposition}
    comptes = {valeur: 0 for valeur in connues}
    vus: set[str] = set()
    for item in dispositions:
        valeur = item.get("disposition")
        if valeur not in connues:
            raise DispositionError(f"disposition inconnue : {valeur!r}")
        if not item.get("appui"):
            raise DispositionError(
                f"{item.get('content_sha256', '?')[:12]}… : disposition sans appui"
            )
        if valeur == Disposition.UNRECOVERABLE_WITH_EVIDENCE.value and not (
            _PREUVE_DIGEST_RE.search(item["appui"])
        ):
            raise DispositionError(
                f"{item.get('content_sha256', '?')[:12]}… : disposition irrécupérable "
                "sans condensé de preuve vérifiable dans l'appui"
            )
        sha = str(item.get("content_sha256"))
        if sha in vus:
            raise DispositionError(f"{sha[:12]}… : artefact dispositionné deux fois")
        vus.add(sha)
        comptes[valeur] += 1
    if comptes != registre.get("comptes"):
        raise DispositionError("les comptes publiés divergent des dispositions")
    total = int(registre.get("artefacts", 0))
    if total != len(dispositions):
        raise DispositionError("le total publié diverge du nombre de dispositions")
    if int(registre.get("CURRENTNESS_UNACCOUNTED", -1)) != 0:
        raise DispositionError("des objets gouvernés restent sans disposition")
    return comptes


__all__ = [
    "LEDGER_KIND",
    "Disposition",
    "DispositionArtefact",
    "DispositionError",
    "construire_registre",
    "verifier_registre",
]
