#!/usr/bin/env python3
"""Exporte l'entrée de revue CANONIQUE d'un run de traitement (§ 7).

Pourquoi cette étape existe. Le préparateur de paquets extrayait le PDF
lui-même : il re-décidait donc du sens d'une page, et pouvait présenter au
reviewer un texte que ni le scanner PII ni le découpage n'avaient jamais vu.
C'est exactement ce qui a permis à l'extraction partielle V1 de passer.

La règle est désormais :

    SORTIE CANONIQUE DU TRAITEMENT V2  →  entrée de revue

Le texte de revue n'est pas produit ici : il est **retrouvé**. Cet exporteur
rejoue l'extraction gouvernée, puis confronte CHAQUE empreinte de page et
l'empreinte du document à ce que la base du run porte réellement. Toute
divergence est un refus, jamais un avertissement — un texte de revue qui n'est
pas celui qui a été scanné ne prouve rien de ce sur quoi on statuera.

La matière brute (le texte canonique) sort HORS du dépôt, en 0600. Le dépôt ne
reçoit que des empreintes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

SCHEMA = "NEXUS-CANONICAL-REVIEW-INPUT-V1"


class CanonicalReviewInputError(RuntimeError):
    """L'entrée de revue ne peut pas être prouvée identique au run."""


def _sha(payload: bytes | str) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonique(document: object) -> bytes:
    """Sérialisation déterministe : un ordre dépendant de l'exécution ne se
    rehache pas deux fois pareil, et son empreinte ne prouverait rien."""
    return json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _ecrire_prive(chemin: Path, octets: bytes) -> str:
    """Écrit de la matière brute : jamais lisible par un autre compte."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "wb") as sortie:
        sortie.write(octets)
    os.chmod(chemin, 0o600)
    return _sha(octets)


def charger_provenance_de_page(connection: object) -> dict[str, dict[int, dict[str, object]]]:
    """Ce que le run a ÉCRIT, page par page — l'autorité de comparaison."""
    lignes = connection.execute(  # type: ignore[attr-defined]
        "SELECT artifact_id, page_number, extraction_path, native_text_sha256,"
        " page_policy_verdict, canonical_page_text_sha256,"
        " ocr_runtime_identity_sha256"
        " FROM drive_staging.page_provenances"
    ).fetchall()
    par_document: dict[str, dict[int, dict[str, object]]] = {}
    for aid, numero, voie, natif, verdict, canon, ocr in lignes:
        par_document.setdefault(aid, {})[numero] = {
            "page_number": numero,
            "extraction_path": voie,
            "native_text_sha256": natif,
            "page_policy_verdict": verdict,
            "canonical_page_text_sha256": canon,
            "ocr_runtime_identity_sha256": ocr,
        }
    return par_document


def exporter(
    *,
    connection: object,
    corpus_root: Path,
    chemins_par_contenu: dict[str, str],
    contenus: list[str],
    sortie: Path,
    identite_du_run: dict[str, object],
    ocr_runtime: object,
) -> dict[str, object]:
    """Rend le manifeste de l'export et écrit la matière hors dépôt."""
    from rag_pedago.governance.drive_extraction import extraire_document

    textes_base = dict(
        connection.execute(  # type: ignore[attr-defined]
            "SELECT artifact_id, canonical_text_sha256 FROM drive_staging.artifacts"
        ).fetchall()
    )
    provenance_base = charger_provenance_de_page(connection)

    sortie.mkdir(parents=True, exist_ok=True)
    os.chmod(sortie, 0o700)

    entrees: list[dict[str, object]] = []
    for contenu in sorted(set(contenus)):
        chemin = chemins_par_contenu.get(contenu)
        if chemin is None:
            raise CanonicalReviewInputError(
                f"{contenu[:16]}… : aucun chemin de corpus — un contenu qu'on ne "
                "sait pas localiser ne peut pas être exporté"
            )
        octets = (corpus_root / chemin).read_bytes()
        if _sha(octets) != contenu:
            raise CanonicalReviewInputError(
                f"{contenu[:16]}… : les octets du corpus hachent ailleurs — le "
                "chemin est un localisateur, l'empreinte est l'autorité"
            )

        resultat = extraire_document(octets, ocr_runtime=ocr_runtime)

        # --- l'identité avec le run, page par page ---------------------
        attendue = provenance_base.get(contenu)
        if attendue is None:
            raise CanonicalReviewInputError(
                f"{contenu[:16]}… : le run ne porte aucune provenance de page"
            )
        if len(attendue) != len(resultat.pages):
            raise CanonicalReviewInputError(
                f"{contenu[:16]}… : le run porte {len(attendue)} page(s), le "
                f"rejeu en rend {len(resultat.pages)}"
            )
        for trace in resultat.provenance:
            reference = attendue.get(trace.number)
            if reference is None:
                raise CanonicalReviewInputError(
                    f"{contenu[:16]}… page {trace.number} : absente du run"
                )
            rejoue = {
                "page_number": trace.number,
                "extraction_path": trace.extraction_path,
                "native_text_sha256": trace.native_text_sha256,
                "page_policy_verdict": trace.page_policy_verdict,
                "canonical_page_text_sha256": trace.canonical_page_text_sha256,
                "ocr_runtime_identity_sha256": trace.ocr_runtime_identity_sha256,
            }
            if rejoue != reference:
                raise CanonicalReviewInputError(
                    f"{contenu[:16]}… page {trace.number} : la provenance rejouée "
                    "diverge de celle du run — le texte présenté au reviewer ne "
                    "serait pas celui qui a été scanné"
                )

        empreinte_texte = _sha(resultat.canonical_text)
        if textes_base.get(contenu) != empreinte_texte:
            raise CanonicalReviewInputError(
                f"{contenu[:16]}… : le texte canonique rejoué hache vers "
                f"{empreinte_texte[:16]}… là où le run porte "
                f"{str(textes_base.get(contenu))[:16]}…"
            )

        # --- la matière, hors dépôt ------------------------------------
        dossier = sortie / contenu
        fichiers: dict[str, str] = {}
        for page in resultat.pages:
            nom = f"pages/page-{page.number:04d}.txt"
            fichiers[nom] = _ecrire_prive(dossier / nom, page.text.encode("utf-8"))
        # Le texte entier, tel qu'il a été soumis au scanner : le reviewer et
        # le vérificateur doivent pouvoir le rehacher sans le reconstituer.
        fichiers["canonical_text.txt"] = _ecrire_prive(
            dossier / "canonical_text.txt", resultat.canonical_text.encode("utf-8")
        )

        provenance = [
            attendue[numero] for numero in sorted(attendue)
        ]
        empreinte_provenance = _sha(_canonique(provenance))
        document = {
            "schema": SCHEMA,
            "content_sha256": contenu,
            "source_pdf_sha256": contenu,
            "drive_file_id": chemins_par_contenu.get(f"{contenu}:drive_file_id", ""),
            "canonical_text_sha256": empreinte_texte,
            "page_count": len(resultat.pages),
            "page_provenance_digest": empreinte_provenance,
            "page_provenance": provenance,
            "extraction_policy_id": resultat.policy_id,
            "extraction_identity_sha256": resultat.identity_sha256(),
            "files": dict(sorted(fichiers.items())),
        }
        _ecrire_prive(dossier / "document.json", _canonique(document))
        entrees.append(
            {
                "content_sha256": contenu,
                "canonical_text_sha256": empreinte_texte,
                "page_provenance_digest": empreinte_provenance,
                "page_count": len(resultat.pages),
                "ocr_pages": sorted(
                    t.number
                    for t in resultat.provenance
                    if t.extraction_path == "OCR_FALLBACK"
                ),
            }
        )

    manifeste = {
        "schema": SCHEMA,
        **identite_du_run,
        "content_count": len(entrees),
        "content_set_sha256": _sha(
            "\n".join(sorted(e["content_sha256"] for e in entrees)) + "\n"  # type: ignore[misc]
        ),
        "entries": sorted(entrees, key=lambda e: str(e["content_sha256"])),
    }
    _ecrire_prive(sortie / "manifest.json", _canonique(manifeste))
    return manifeste


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="base du run V2 (lecture seule)")
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--run-report", required=True, type=Path)
    parser.add_argument("--run-identity", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)

    import psycopg
    from nexus_pdf_ocr import require_runtime

    identite = json.loads(args.run_identity.read_text(encoding="utf-8"))
    # Le runtime OCR est EXIGÉ identique à celui du run : un autre moteur
    # rendrait un autre texte sur les pages océrisées, et l'export échouerait
    # plus loin sur une divergence dont l'origine serait perdue.
    runtime = require_runtime(str(identite["OCR_RUNTIME_IDENTITY"]))

    rapport = json.loads(args.run_report.read_text(encoding="utf-8"))
    detectes = [e["artifact_id"] for e in rapport["pii_detectes"]]

    chemins: dict[str, str] = {}
    for ligne in args.inventory.read_text(encoding="utf-8").splitlines():
        if not ligne.strip():
            continue
        objet = json.loads(ligne)
        if objet.get("mime_type") != "application/pdf" or not objet.get("servable"):
            continue
        chemin = objet["relative_path"]
        empreinte = _sha((args.corpus_root / chemin).read_bytes())
        chemins.setdefault(empreinte, chemin)
        chemins.setdefault(f"{empreinte}:drive_file_id", objet.get("drive_file_id", ""))

    with psycopg.connect(args.dsn) as connection:
        manifeste = exporter(
            connection=connection,
            corpus_root=args.corpus_root,
            chemins_par_contenu=chemins,
            contenus=detectes,
            sortie=args.output_root,
            identite_du_run=identite,
            ocr_runtime=runtime,
        )
    print(f"CANONICAL_REVIEW_INPUT_SCHEMA={manifeste['schema']}")
    print(f"CANONICAL_REVIEW_INPUT_CONTENTS={manifeste['content_count']}")
    print(f"CANONICAL_REVIEW_INPUT_CONTENT_SET_SHA256={manifeste['content_set_sha256']}")
    print(f"CANONICAL_REVIEW_INPUT_MANIFEST_SHA256={_sha(_canonique(manifeste))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
