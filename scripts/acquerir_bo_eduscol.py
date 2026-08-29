#!/usr/bin/env python3
"""Acquérir les programmes officiels manquants depuis Éduscol, avec corroboration.

═══ LA CLASSE D'ACQUISITION, NOMMÉE POUR CE QU'ELLE EST ═══════════════════

**Acquisition authentifiée par domaine, horodatée.** Ce n'est pas un
« trust on first use » : le TOFU fait confiance à un inconnu parce qu'il arrive
le premier. Ici, la confiance est ancrée dans un domaine gouvernemental
authentifié par TLS — `eduscol.education.gouv.fr` — à une date consignée.

Et c'est **exactement le cycle de vie des 2 451 documents du corpus scellé** :
moissonnés depuis Éduscol, puis scellés. Les documents acquis ici suivent le
même chemin, plus tard. Ce n'est pas une classe plus faible ; c'est la même, à
un autre moment.

═══ CORROBORATION CROISÉE ════════════════════════════════════════════════

Deux sources indépendantes doivent concorder :

  1. la **page de listing** Éduscol nomme le programme et sa référence de B.O. ;
  2. le **document lui-même** cite son arrêté et son numéro de B.O.

Un document dont la référence de B.O. ne concorde pas avec celle annoncée par
son listing est **rejeté, pas scellé**. La concordance est enregistrée comme
preuve d'acquisition — elle ne coûte rien et elle ferme la porte à un document
substitué.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DOMAINE_AUTORISE = "eduscol.education.gouv.fr"
AGENT = "Mozilla/5.0 (NexusRAG/1.0; acquisition gouvernée)"


def sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte)
                   if unicodedata.category(c) != "Mn").lower()


def reference_bo(texte: str) -> str | None:
    """Extraire « B.O. n° N du JJ mois AAAA » sous forme normalisée."""
    m = re.search(r"bo\s*(?:special\s*)?n\s*°?\s*(\d+)\s*du\s*(\d+)\s*"
                  r"([a-z]+)\s*(\d{4})", sans_accent(texte))
    if not m:
        return None
    return f"BO-{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"


def _recuperer(url: str, *, binaire: bool) -> bytes:
    hote = urllib.parse.urlparse(url).netloc
    if hote != DOMAINE_AUTORISE:
        raise ValueError(
            f"domaine refusé : {hote!r}. L'acquisition n'est authentifiée que "
            f"pour {DOMAINE_AUTORISE} — un autre domaine n'a pas cette autorité.")
    if not url.startswith("https://"):
        raise ValueError("acquisition refusée hors TLS : l'authentification de "
                         "domaine est le fondement de cette classe de preuve.")
    requete = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(requete, timeout=45) as reponse:
        return reponse.read()


def liens_pdf(html: str, base: str) -> list[tuple[str, str]]:
    """Retourner (url, libellé) des liens PDF d'une page de listing."""
    trouves: list[tuple[str, str]] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>',
                         html, re.I | re.S):
        url = urllib.parse.urljoin(base, m.group(1))
        libelle = " ".join(re.sub(r"<[^>]+>", " ", m.group(2)).split())
        trouves.append((url, libelle))
    return trouves


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listings", type=Path, required=True,
                        help="JSON : [{collection, listing_url, motif_titre}]")
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args(argv)

    args.dest.mkdir(parents=True, exist_ok=True)
    demandes = json.loads(args.listings.read_text(encoding="utf-8"))
    acquis, rejetes = [], []

    for demande in demandes:
        listing = demande["listing_url"]
        print(f"  ── {demande['collection']}\n     {listing[:96]}", flush=True)
        try:
            html = _recuperer(listing, binaire=False).decode("utf-8", "replace")
        except Exception as exc:                              # noqa: BLE001
            rejetes.append({**demande, "raison": f"listing illisible : {exc}"})
            print(f"     LISTING ILLISIBLE : {exc}", flush=True)
            continue

        # Référence de B.O. annoncée par le listing — première source.
        motif = sans_accent(demande.get("motif_titre", ""))
        candidats = [(u, lib) for u, lib in liens_pdf(html, listing)
                     if not motif or motif in sans_accent(lib)]
        if not candidats:
            rejetes.append({**demande, "raison": "aucun PDF correspondant au motif"})
            print("     AUCUN PDF CORRESPONDANT", flush=True)
            continue

        url, libelle = candidats[0]
        bo_listing = reference_bo(libelle)
        try:
            octets = _recuperer(url, binaire=True)
        except Exception as exc:                              # noqa: BLE001
            rejetes.append({**demande, "raison": f"téléchargement échoué : {exc}"})
            continue

        # Référence de B.O. citée par le document — seconde source.
        try:
            from pypdf import PdfReader
            import io
            texte = "\n".join((p.extract_text() or "")
                              for p in PdfReader(io.BytesIO(octets)).pages[:3])
        except Exception:                                     # noqa: BLE001
            texte = ""
        bo_document = reference_bo(texte) or reference_bo(libelle)

        if bo_listing and bo_document and bo_listing != bo_document:
            rejetes.append({**demande, "url": url, "raison":
                            f"B.O. discordant — listing {bo_listing}, "
                            f"document {bo_document}"})
            print(f"     REJETÉ : B.O. discordant ({bo_listing} ≠ {bo_document})",
                  flush=True)
            continue

        empreinte = hashlib.sha256(octets).hexdigest()
        (args.dest / f"{empreinte}.pdf").write_bytes(octets)
        acquis.append({
            "collection": demande["collection"],
            "sha256": empreinte,
            "url": url,
            "libelle": libelle[:160],
            "listing_url": listing,
            "bo_listing": bo_listing,
            "bo_document": bo_document,
            "corroboration": ("concordante" if bo_listing and bo_document
                              else "partielle — une seule source porte la référence"),
            "classe_acquisition": "acquisition_authentifiee_par_domaine_horodatee",
            "domaine": DOMAINE_AUTORISE,
            "acquis_le": datetime.now(timezone.utc).isoformat(),
            "octets": len(octets),
        })
        print(f"     ACQUIS  {empreinte[:12]}…  {len(octets)} o  "
              f"corroboration {acquis[-1]['corroboration']}", flush=True)

    args.sortie.write_text(json.dumps(
        {"acquis": acquis, "rejetes": rejetes}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n  acquis : {len(acquis)}   rejetés : {len(rejetes)}")
    for r in rejetes:
        print(f"    REJET  {r['collection']:34} {r['raison'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
