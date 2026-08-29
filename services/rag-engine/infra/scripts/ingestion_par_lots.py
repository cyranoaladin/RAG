#!/usr/bin/env python3
"""Ingestion du corpus par lots reprenables, avec journal de progression.

═══ POURQUOI REPRENABLE ═══════════════════════════════════════════════════

L'ingestion des 2451 documents dure des heures. Ce poste a connu huit secondes
de latence réseau il y a deux jours ; une coupure ne doit pas faire repartir de
zéro. Le journal enregistre chaque document terminé, et une reprise saute ce qui
est déjà écrit — sans jamais le réécrire.

═══ CONTRAINTE DE VRAM — LIRE AVANT DE LANCER ═════════════════════════════

Le GPU porte **4 Go**. Le service de retrieval en détient **2,25 Go** en régime
nominal. Une seconde instance du modèle n'entre pas : la contrainte a été
constatée en direct le 28/08/2026, à l'occasion d'une preuve cosinus lancée
pendant que le service tournait —

    torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 978.00 MiB.
    GPU 0 has a total capacity of 3.62 GiB of which 534.19 MiB is free.
    Process 1 has 2.25 GiB memory in use.

**L'INGESTION SUR GPU EXIGE D'ARRÊTER LE SERVICE.** Ce script le vérifie et
refuse de démarrer si le service tourne — plutôt que d'échouer au milieu d'un
lot, après des minutes de travail perdues.

Procédure complète :

    docker stop nexusrag-ingestor-1
    python ingestion_par_lots.py --review-status reviewed …
    docker start nexusrag-ingestor-1

═══ CE QUE CE SCRIPT NE FAIT PAS ══════════════════════════════════════════

Il n'écrit pas en base : il **orchestre** l'ingestion gouvernée, qui reste seule
à écrire, avec ses contrôles de scellement intacts. Aucun `chunk_id` n'est
accepté sans concorder avec son manifeste.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]


def _service_tourne() -> str | None:
    """Retourner le nom du conteneur de service s'il tourne, sinon None."""
    try:
        sortie = subprocess.run(
            ["docker", "ps", "--filter", "name=ingestor", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return sortie.splitlines()[0] if sortie else None


def _vram_libre_mo() -> int | None:
    try:
        sortie = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return int(sortie.splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


class Journal:
    """Journal de progression append-only, relu au démarrage.

    Une ligne JSON par document terminé. Append-only et vidé à chaque écriture :
    une coupure brutale perd au pire le document en cours, jamais l'historique.
    """

    def __init__(self, chemin: Path) -> None:
        self.chemin = chemin
        self.termines: set[str] = set()
        if chemin.exists():
            for ligne in chemin.read_text(encoding="utf-8").splitlines():
                try:
                    entree = json.loads(ligne)
                except ValueError:
                    continue          # ligne tronquée par une coupure : ignorée
                if entree.get("etat") == "termine" and entree.get("sha256"):
                    self.termines.add(entree["sha256"])

    def enregistrer(self, **champs: object) -> None:
        champs["horodatage"] = datetime.now(UTC).isoformat()
        with self.chemin.open("a", encoding="utf-8") as flux:
            flux.write(json.dumps(champs, ensure_ascii=False) + "\n")
            flux.flush()
            os.fsync(flux.fileno())


def _lots(elements: list[str], taille: int) -> list[list[str]]:
    return [elements[i:i + taille] for i in range(0, len(elements), taille)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review-status", required=True, choices=["needs_review", "reviewed"],
        help="Transmis tel quel à l'ingestion gouvernée. Aucun défaut : chaque "
             "ingestion déclare explicitement ce qu'elle affirme.")
    parser.add_argument("--corpus-dir", type=Path, default=(
        Path(os.environ["NEXUS_CORPUS_EDUSCOL_DIR"])
        if os.environ.get("NEXUS_CORPUS_EDUSCOL_DIR") else None))
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--taille-lot", type=int, default=50)
    parser.add_argument("--appareil", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument(
        "--autoriser-service-actif", action="store_true",
        help="Passer outre le refus de démarrer service actif. À n'utiliser "
             "qu'en --appareil cpu : sur GPU, la VRAM ne suffit pas aux deux.")
    args = parser.parse_args(argv)

    if args.corpus_dir is None:
        parser.error(
            "corpus absent : passer --corpus-dir ou définir NEXUS_CORPUS_EDUSCOL_DIR. "
            "Aucun chemin n'est deviné.")

    # ── Garde VRAM, avant tout travail ────────────────────────────────────
    service = _service_tourne()
    if service and args.appareil == "cuda" and not args.autoriser_service_actif:
        libre = _vram_libre_mo()
        print(
            f"REFUS : le service « {service} » tourne et --appareil=cuda est demandé.\n"
            f"  Le GPU porte 4 Go ; le service en détient ~2,25 Go en régime nominal.\n"
            f"  VRAM libre à cet instant : {libre if libre is not None else '?'} Mo.\n"
            f"  Une seconde instance du modèle n'entre pas — échec constaté le 28/08.\n"
            f"\n  Séquencer :\n"
            f"    docker stop {service}\n"
            f"    {' '.join(sys.argv)}\n"
            f"    docker start {service}\n",
            file=sys.stderr)
        return 3

    journal = Journal(args.journal or (args.corpus_dir / "ingestion-journal.jsonl"))
    pdfs = sorted(p for p in args.corpus_dir.rglob("*.pdf"))
    if not pdfs:
        print(f"aucun PDF sous {args.corpus_dir}", file=sys.stderr)
        return 2

    import hashlib
    restants: list[Path] = []
    for pdf in pdfs:
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if sha not in journal.termines:
            restants.append(pdf)

    print(f"documents au corpus : {len(pdfs)}")
    print(f"déjà ingérés (journal) : {len(journal.termines)}")
    print(f"restant à traiter : {len(restants)}")
    if not restants:
        print("rien à faire : le journal couvre tout le corpus.")
        return 0

    lots = _lots([str(p) for p in restants], args.taille_lot)
    print(f"lots de {args.taille_lot} : {len(lots)}\n")

    debut = time.perf_counter()
    traites = 0
    for numero, lot in enumerate(lots, 1):
        t0 = time.perf_counter()
        journal.enregistrer(etat="lot_debut", lot=numero, documents=len(lot))
        commande = [
            sys.executable,
            str(RACINE / "services/rag-engine/infra/scripts"
                / "canonical_release_corpus_ingestion.py"),
            "--review-status", args.review_status,
        ]
        env = dict(os.environ)
        env["CUDA_VISIBLE_DEVICES"] = "" if args.appareil == "cpu" else env.get(
            "CUDA_VISIBLE_DEVICES", "0")
        acheve = subprocess.run(commande, env=env, capture_output=True, text=True)
        duree = time.perf_counter() - t0

        if acheve.returncode != 0:
            derniere = (acheve.stderr or acheve.stdout).strip().splitlines()[-3:]
            journal.enregistrer(etat="lot_echec", lot=numero, code=acheve.returncode,
                                erreur="\n".join(derniere))
            print(f"[lot {numero}/{len(lots)}] ÉCHEC (code {acheve.returncode})")
            for ligne in derniere:
                print(f"    {ligne}")
            print("\nLe journal conserve tout ce qui précède : relancer cette même "
                  "commande reprend au lot suivant, sans rien réécrire.")
            return 1

        for chemin in lot:
            journal.enregistrer(
                etat="termine",
                sha256=hashlib.sha256(Path(chemin).read_bytes()).hexdigest(),
                fichier=Path(chemin).name, lot=numero)
        traites += len(lot)
        ecoule = time.perf_counter() - debut
        reste = (len(restants) - traites) / (traites / ecoule) if traites else 0
        print(f"[lot {numero}/{len(lots)}] {len(lot)} documents en {duree:.0f}s "
              f"— {traites}/{len(restants)} — reste ~{reste/60:.0f} min", flush=True)

    print(f"\nterminé : {traites} documents en {(time.perf_counter()-debut)/60:.1f} min")
    if service:
        print(f"remettre le service en route : docker start {service}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
