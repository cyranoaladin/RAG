#!/usr/bin/env python3
"""Vérifie une réacquisition non-PDF contre le manifeste qui l'a demandée.

Récupérer n'est pas vérifier. Un fichier rendu par le canal Drive peut être le
bon fichier, un autre fichier de même taille, ou une page d'erreur enregistrée
sous le bon nom. Seule l'empreinte tranche — et elle est CONFRONTÉE à celle que
la disposition avait relevée sur les octets, jamais recalculée puis acceptée
comme sa propre référence.

Les 37 `.ggb` sont des archives. Ce script ne les ouvre pas : l'identité de
source est celle du FICHIER PHYSIQUE. Toute extraction destinée à devenir
recherchable est une étape ultérieure, qui passe le gate PII et ses protections
d'archive — pas une commodité de vérification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

KIND = "NEXUS-NON-PDF-REACQUISITION-VERIFICATION-V1"


def _sha(chemin: Path) -> str:
    empreinte = hashlib.sha256()
    with chemin.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1 << 20), b""):
            empreinte.update(bloc)
    return empreinte.hexdigest()


def verifier(demandes: list[dict[str, object]], racine: Path) -> dict[str, object]:
    """Confronte chaque fichier reçu à la taille ET à l'empreinte attendues.

    Les deux, pas l'une : des octets qui hachent juste et une taille déclarée
    fausse disent que le manifeste ment sur autre chose que le contenu, et les
    confondre priverait l'exploitant de l'information qui dit QUOI réparer.
    """
    resultats: list[dict[str, object]] = []
    comptes = {
        "NON_PDF_REACQUIRED": 0,
        "NON_PDF_SIZE_MATCH": 0,
        "NON_PDF_SHA_MATCH": 0,
        "NON_PDF_SIZE_MISMATCH": 0,
        "NON_PDF_SHA_MISMATCH": 0,
        "NON_PDF_MISSING": 0,
        "NON_PDF_ERRORS": 0,
    }
    for demande in demandes:
        attendue = str(demande["expected_content_sha256"])
        taille_attendue = int(demande["expected_size"])
        # Le fichier est nommé par son empreinte ATTENDUE : c'est une adresse,
        # pas une preuve. Elle est confrontée juste après.
        candidats = [racine / attendue, *sorted(racine.glob(f"{attendue}.*"))]
        recu = next((c for c in candidats if c.is_file()), None)
        ligne: dict[str, object] = {
            "drive_file_id": demande["drive_file_id"],
            "expected_content_sha256": attendue,
            "expected_size": taille_attendue,
            "classification": demande.get("classification"),
        }
        if recu is None:
            ligne["status"] = "MISSING"
            comptes["NON_PDF_MISSING"] += 1
            resultats.append(ligne)
            continue
        try:
            taille = recu.stat().st_size
            obtenue = _sha(recu)
        except OSError as exc:
            ligne["status"] = "ERROR"
            ligne["detail"] = type(exc).__name__
            comptes["NON_PDF_ERRORS"] += 1
            resultats.append(ligne)
            continue
        comptes["NON_PDF_REACQUIRED"] += 1
        ligne["observed_size"] = taille
        ligne["observed_content_sha256"] = obtenue
        taille_ok = taille == taille_attendue
        sha_ok = obtenue == attendue
        comptes["NON_PDF_SIZE_MATCH" if taille_ok else "NON_PDF_SIZE_MISMATCH"] += 1
        comptes["NON_PDF_SHA_MATCH" if sha_ok else "NON_PDF_SHA_MISMATCH"] += 1
        ligne["status"] = "VERIFIED" if (taille_ok and sha_ok) else "MISMATCH"
        resultats.append(ligne)

    total = len(demandes)
    rendu: dict[str, object] = {"kind": KIND, "NON_PDF_EXPECTED": total, **comptes}
    rendu["NON_PDF_UNACCOUNTED"] = total - (
        comptes["NON_PDF_REACQUIRED"]
        + comptes["NON_PDF_MISSING"]
        + comptes["NON_PDF_ERRORS"]
    )
    rendu["ACCEPTANCE_MET"] = (
        comptes["NON_PDF_REACQUIRED"] == total
        and comptes["NON_PDF_SIZE_MISMATCH"] == 0
        and comptes["NON_PDF_SHA_MISMATCH"] == 0
        and comptes["NON_PDF_ERRORS"] == 0
        and rendu["NON_PDF_UNACCOUNTED"] == 0
    )
    rendu["results"] = sorted(resultats, key=lambda e: str(e["expected_content_sha256"]))
    return rendu


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--received-root",
        required=True,
        type=Path,
        help="répertoire où le canal Drive a déposé les fichiers, nommés par "
        "leur content_sha256 attendu",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    manifeste = json.loads(args.manifest.read_text(encoding="utf-8"))
    rendu = verifier(manifeste["requests"], args.received_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(rendu, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for cle in (
        "NON_PDF_EXPECTED", "NON_PDF_REACQUIRED", "NON_PDF_SIZE_MATCH",
        "NON_PDF_SHA_MATCH", "NON_PDF_SIZE_MISMATCH", "NON_PDF_SHA_MISMATCH",
        "NON_PDF_MISSING", "NON_PDF_ERRORS", "NON_PDF_UNACCOUNTED",
        "ACCEPTANCE_MET",
    ):
        print(f"{cle}={rendu[cle]}")
    return 0 if rendu["ACCEPTANCE_MET"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
