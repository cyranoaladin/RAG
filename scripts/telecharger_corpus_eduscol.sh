#!/usr/bin/env bash
# Télécharger et vérifier le corpus Éduscol depuis Drive.
#
# Le corpus source fait autorité sur son propre contenu. Ce script ne le
# reconstitue pas : il le copie, puis vérifie CHAQUE fichier contre les
# empreintes que le corpus publie lui-même (00_ADMIN/SHA256SUMS.txt).
#
# Aucun chemin de machine n'est deviné : la destination et le remote se
# configurent, et l'absence de configuration échoue en nommant la raison.
set -uo pipefail

REMOTE="${NEXUS_DRIVE_REMOTE:-gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY}"
DEST="${NEXUS_CORPUS_EDUSCOL_DIR:-}"
if [ -z "$DEST" ]; then
  echo "destination absente : définir NEXUS_CORPUS_EDUSCOL_DIR." >&2
  echo "Deviner un chemin ferait dépendre le corpus d'un poste précis." >&2
  exit 2
fi

mkdir -p "$DEST/01_EDUSCOL_OFFICIEL" "$DEST/00_ADMIN"

echo "== 1/3 empreintes de référence =="
rclone copy "$REMOTE/00_ADMIN/SHA256SUMS.txt" "$DEST/00_ADMIN/" --progress 2>&1 | tail -2
rclone copy "$REMOTE/00_ADMIN/eduscol_affectations.tsv" "$DEST/00_ADMIN/" 2>&1 | tail -1
wc -l < "$DEST/00_ADMIN/SHA256SUMS.txt" | sed 's/^/  lignes d empreintes: /'

echo "== 2/3 téléchargement des 2451 PDF =="
# `--checksum` évite de retélécharger ce qui est déjà correct : le script est
# reprenable, une coupure ne fait pas repartir de zéro.
rclone copy "$REMOTE/01_EDUSCOL_OFFICIEL" "$DEST/01_EDUSCOL_OFFICIEL" \
  --checksum --transfers 6 --checkers 12 \
  --stats 30s --stats-one-line --log-level INFO 2>&1 | tail -20

echo "== 3/3 vérification par empreinte, sur TOUT le périmètre =="
python3 - "$DEST" <<'PY'
import hashlib, sys
from pathlib import Path

racine = Path(sys.argv[1])
sommes = racine / "00_ADMIN" / "SHA256SUMS.txt"
attendu = {}
for ligne in sommes.read_text(encoding="utf-8", errors="replace").splitlines():
    ligne = ligne.strip()
    if not ligne or " " not in ligne:
        continue
    empreinte, chemin = ligne.split(None, 1)
    attendu[chemin.lstrip("*./")] = empreinte.lower()

presents = {}
for p in (racine / "01_EDUSCOL_OFFICIEL").rglob("*"):
    if p.is_file():
        presents[str(p.relative_to(racine))] = p

print(f"  empreintes déclarées : {len(attendu)}")
print(f"  fichiers téléchargés : {len(presents)}")

conformes = divergents = []
conformes, divergents, manquants = [], [], []
for chemin, empreinte in sorted(attendu.items()):
    # Le fichier d'empreintes peut préfixer autrement : on retrouve par suffixe.
    fichier = presents.get(chemin)
    if fichier is None:
        candidats = [p for c, p in presents.items() if c.endswith(Path(chemin).name)]
        fichier = candidats[0] if len(candidats) == 1 else None
    if fichier is None:
        manquants.append(chemin); continue
    reel = hashlib.sha256(fichier.read_bytes()).hexdigest()
    (conformes if reel == empreinte else divergents).append(chemin)

print(f"\n  ── VÉRIFICATION ──")
print(f"  conformes  : {len(conformes)}/{len(attendu)}")
print(f"  divergents : {len(divergents)}")
print(f"  manquants  : {len(manquants)}")
for c in divergents[:10]:
    print(f"    DIVERGENT  {c}")
for c in manquants[:10]:
    print(f"    MANQUANT   {c}")
sys.exit(0 if not divergents and not manquants else 1)
PY
