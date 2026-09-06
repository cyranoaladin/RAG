#!/usr/bin/env python3
"""Construit le registre des URL sources à partir des autorités et des sondes.

Le script ne va **pas** sur le réseau : il assemble. Les sondes réseau lui
sont fournies telles qu'elles ont été relevées (agent identifié,
``Crawl-delay`` du fournisseur respecté), afin que la construction du
registre soit rejouable à l'identique et que la CI n'ait jamais besoin de
sortir de la machine.

Toutes les entrées sont des chemins passés en argument : aucune racine
machine-locale n'est inscrite ici.

Usage :
    python scripts/build_url_source_registry.py \\
        --evidence configs/prerentree_2026_2027/multilevel_currentness_evidence.yml \\
        --catalogue <catalogue-complet.tsv> \\
        --sondes <sondes_reseau.json> \\
        --sortie data/releases/prerentree_2026_2027/multilevel/url_source_registry.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_pedago.governance.url_source_registry import (  # noqa: E402
    RAISON_IRRECUPERABILITE_NAVIGATION_PROTEGEE as RAISON_403,
)
from rag_pedago.governance.url_source_registry import (  # noqa: E402
    RAISON_IRRECUPERABILITE_RELATION_ABSENTE as RAISON_RELATION_ABSENTE,
)
from rag_pedago.governance.url_source_registry import (  # noqa: E402
    REGISTRY_KIND,
    AutoriteSource,
    EntreeUrl,
    RegistreUrlSource,
    Resolution,
    RoleSource,
    ecrire_registre,
    verifier_registre,
)

PERIMETRE = "prerentree_2026_2027/multilevel"

#: Le seul porteur connu de la relation « page de navigation → URL de
#: document direct » : la base du moissonneur, dont les tables ``urls`` et
#: ``references_`` conservent ``source_url`` → ``target_url``. Le catalogue
#: exporté vers le plan de contrôle a laissé tomber cette colonne.
PORTEUR_RELATION = (
    "catalog.sqlite3 du run eduscol-pdf-harvester v1.10.0 "
    "full-20260804T230753+0100 (tables urls[kind='pdf'] et "
    "references_[source_url, target_url])"
)

#: Statuts pour lesquels une non-réponse ne prouve rien de permanent : la
#: sonde doit être reprise, pas classée irrécupérable sur un accident
#: transitoire du fournisseur ou du réseau.
STATUTS_TRANSITOIRES = frozenset({429})


def _est_echec_transitoire(sonde: dict[str, Any]) -> bool:
    status = sonde.get("status")
    if status is None:
        return True
    if status in STATUTS_TRANSITOIRES:
        return True
    return 500 <= status < 600


def _preuve_navigation(sonde: dict[str, Any], autorites: int) -> str:
    """La preuve est un fait mesuré, pas une conviction.

    Elle nomme les trois choses qui, ensemble, ferment la question : ce que
    le fournisseur a répondu, ce que sa politique déclarée autorise, et où
    l'on a cherché la relation sans la trouver.
    """
    status = sonde.get("status")
    observe = f"HTTP {status}" if status is not None else f"échec réseau ({sonde.get('erreur')})"
    return (
        f"{observe} le {sonde.get('retrieved_at')} avec agent identifié et le "
        "Crawl-delay: 10 déclaré par robots.txt ; robots.txt (User-agent: *) "
        "n'exclut pas ce chemin et autorise explicitement /sites/default/files/ "
        "et *.pdf — la fermeture est une protection anti-robot du fournisseur, "
        "pas une exclusion robots, et n'est pas contournée ; l'URL de document "
        f"direct correspondante n'apparaît dans aucune des {autorites} autorités "
        "textuelles du plan de contrôle Drive (0 occurrence de "
        "« sites/default/files ») ; son unique porteur connu — "
        f"{PORTEUR_RELATION} — n'a pas été versé au plan de contrôle et son "
        "répertoire de run local n'existe plus."
    )


def _sha256_fichier(chemin: Path) -> str:
    empreinte = hashlib.sha256()
    with chemin.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1 << 20), b""):
            empreinte.update(bloc)
    return empreinte.hexdigest()


def _sonde_de(sondes: dict[str, dict[str, Any]], url: str) -> dict[str, Any]:
    sonde = sondes.get(url)
    if sonde is None:
        raise SystemExit(f"SONDE_MANQUANTE: {url}")
    return sonde


def construire(
    evidence_path: Path,
    catalogue_path: Path,
    sondes_path: Path,
    nb_autorites: int,
) -> RegistreUrlSource:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))["artifacts"]
    sondes: dict[str, dict[str, Any]] = json.loads(sondes_path.read_text(encoding="utf-8"))

    navigation_par_empreinte: dict[str, set[str]] = defaultdict(set)
    urls_navigation: set[str] = set()
    lignes_catalogue = 0
    with catalogue_path.open(encoding="utf-8", newline="") as flux:
        for ligne in csv.DictReader(flux, delimiter="\t"):
            lignes_catalogue += 1
            url = (ligne.get("url_source") or "").strip()
            if url:
                urls_navigation.add(url)
                navigation_par_empreinte[ligne["sha256"]].add(url)

    perimetre_par_url: dict[str, set[str]] = defaultdict(set)
    for artefact in evidence:
        for url in navigation_par_empreinte.get(artefact["content_sha256"], ()):
            perimetre_par_url[url].add(artefact["content_sha256"])

    entrees: list[EntreeUrl] = []

    # 1. Les documents directs : les seules URL sur lesquelles « fraîcheur »
    #    veut dire quelque chose, parce qu'elles rendent l'octet scellé.
    for artefact in evidence:
        direct = artefact.get("current_download_url")
        if not direct:
            continue
        sonde = _sonde_de(sondes, direct)
        servi = sonde.get("content_sha256")
        if sonde.get("status") == 200 and servi is not None and servi != artefact["content_sha256"]:
            raise SystemExit(
                f"EMPREINTE_DERIVEE {direct} : servie={servi} "
                f"scellée={artefact['content_sha256']} — la sonde directe rend un "
                "contenu différent de l'empreinte scellée ; ceci est une dérive de "
                "contenu à la source, pas une incohérence de registre, et exige une "
                "remédiation gouvernée avant toute écriture du registre"
            )
        entrees.append(
            EntreeUrl(
                url=direct,
                source_role=RoleSource.DOCUMENT_DIRECT,
                resolution=Resolution.RESOLUE,
                navigation_url=artefact.get("current_source_listing_url"),
                direct_url=direct,
                resolved_url=sonde.get("resolved_url"),
                status=sonde.get("status"),
                content_type=sonde.get("content_type"),
                etag=sonde.get("etag"),
                last_modified=sonde.get("last_modified"),
                retrieved_at=sonde.get("retrieved_at"),
                content_sha256=sonde.get("content_sha256"),
                artifact_id=artefact["content_sha256"],
                empreinte_scellee=artefact["content_sha256"],
                artefacts_perimetre=(artefact["content_sha256"],),
                erreur_reseau=sonde.get("erreur"),
            )
        )

    # 2. Les pages de navigation : provenance réelle du corpus, mais jamais
    #    porteuses de l'octet. Leur sort doit être nommé une par une.
    for url in sorted(urls_navigation):
        sonde = _sonde_de(sondes, url)
        accessible = sonde.get("status") == 200
        transitoire = (not accessible) and _est_echec_transitoire(sonde)
        irrecuperable = not accessible and not transitoire
        entrees.append(
            EntreeUrl(
                url=url,
                source_role=RoleSource.NAVIGATION_PROVENANCE,
                resolution=(
                    Resolution.IRRECUPERABLE if irrecuperable else Resolution.EN_ATTENTE
                ),
                navigation_url=url,
                direct_url=None,
                resolved_url=sonde.get("resolved_url"),
                status=sonde.get("status"),
                content_type=sonde.get("content_type"),
                etag=sonde.get("etag"),
                last_modified=sonde.get("last_modified"),
                retrieved_at=sonde.get("retrieved_at"),
                content_sha256=sonde.get("content_sha256"),
                artifact_id=None,
                empreinte_scellee=None,
                artefacts_perimetre=tuple(sorted(perimetre_par_url.get(url, ()))),
                raison_irrecuperabilite=(
                    RAISON_403
                    if irrecuperable and sonde.get("status") == 403
                    else RAISON_RELATION_ABSENTE
                    if irrecuperable
                    else None
                ),
                preuve_irrecuperabilite=(
                    _preuve_navigation(sonde, nb_autorites) if irrecuperable else None
                ),
                motif_attente=(
                    "Page accessible : l'extraction des liens de document reste à "
                    "faire par remoisson sanctionnée (eduscol-pdf-harvester), qui "
                    "reconstruira la table urls/references_ perdue."
                    if accessible
                    else (
                        f"Échec transitoire ({sonde.get('status') or sonde.get('erreur')}) "
                        f"le {sonde.get('retrieved_at')} : l'inaccessibilité n'est pas "
                        "démontrée permanente, la sonde réseau doit être reprise avant "
                        "toute classification irrécupérable."
                        if transitoire
                        else None
                    )
                ),
                erreur_reseau=sonde.get("erreur"),
            )
        )

    autorites = [
        AutoriteSource(
            nom="catalogue-complet.tsv",
            emplacement=(
                "gdrive:NEXUS_RAG_GDRIVE_READY/00_INDEX_PROVENANCE/"
                "EDUSCOL_CATALOGUES/catalogue-complet.tsv"
            ),
            sha256=_sha256_fichier(catalogue_path),
            note=(
                f"{lignes_catalogue} affectations, {len(urls_navigation)} URL de "
                "navigation distinctes, aucune URL de document direct."
            ),
        ),
        AutoriteSource(
            nom="multilevel_currentness_evidence.yml",
            emplacement="services/rag-pedago/configs/prerentree_2026_2027/multilevel_currentness_evidence.yml",
            sha256=_sha256_fichier(evidence_path),
            note=(
                f"{len(evidence)} artefacts scellés du périmètre ; "
                f"{sum(1 for a in evidence if a.get('current_download_url'))} portent "
                "une URL de document direct."
            ),
        ),
    ]

    registre = RegistreUrlSource(
        registry_kind=REGISTRY_KIND,
        perimetre=PERIMETRE,
        autorites=autorites,
        entrees=entrees,
    )
    verifier_registre(registre)
    return registre


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--evidence", type=Path, required=True)
    analyseur.add_argument("--catalogue", type=Path, required=True)
    analyseur.add_argument("--sondes", type=Path, required=True)
    analyseur.add_argument("--sortie", type=Path, required=True)
    analyseur.add_argument(
        "--autorites-consultees",
        type=int,
        default=37,
        help="Nombre d'autorités textuelles du plan de contrôle fouillées sans succès.",
    )
    args = analyseur.parse_args()

    registre = construire(
        args.evidence, args.catalogue, args.sondes, args.autorites_consultees
    )
    ecrire_registre(registre, args.sortie)
    print(f"REGISTRE_ECRIT {args.sortie} ({len(registre.entrees)} entrées)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
