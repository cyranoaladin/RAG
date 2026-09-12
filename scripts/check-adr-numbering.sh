#!/usr/bin/env bash
# check-adr-numbering.sh — L'espace des numéros d'ADR est un registre, pas une convention.
#
# Motif : un numéro d'ADR a été réservé par deux artefacts en prose — une phrase de rapport
# et un champ JSON — sans qu'aucun fichier ne porte ce nom. Un `git log --all` ne pouvait
# pas le voir, et un ADR sans rapport a été écrit sous ce numéro. Une réservation doit être
# une chose que l'outil connaît, pas une chose qu'il faut avoir lue.
#
# Ce fichier est balayé comme les autres : un garde-fou qui s'exempte lui-même de son propre
# contrôle est précisément le défaut qu'il cherche. D'où l'absence de tout numéro littéral
# dans ces commentaires — il vaudrait réservation.
#
# Règles :
# 1. Deux fichiers ne peuvent pas porter le même numéro.        → ÉCHEC
# 2. Un numéro référencé dans le dépôt sans fichier doit être
#    déclaré dans docs/adr/RESERVATIONS.md.                     → ÉCHEC sinon
# 3. Un numéro à la fois réservé ET porté par un fichier doit
#    être retiré du registre : une réservation honorée n'est
#    plus une réservation.                                      → ÉCHEC sinon
#
# Les fixtures de test (scripts/tests/) sont exclues du balayage des références :
# elles emploient délibérément des numéros fictifs.
#
# Override pour les tests :
#   ADR_DIR             — répertoire des ADR
#   ADR_RESERVATIONS    — fichier de registre des réservations
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ADR_DIR="${ADR_DIR:-docs/adr}"
ADR_RESERVATIONS="${ADR_RESERVATIONS:-$ADR_DIR/RESERVATIONS.md}"
PATTERN='ADR-[0-9]{4}'

if [ ! -d "$ADR_DIR" ]; then
    echo "ERROR: $ADR_DIR not found"; exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- Numéros portés par un fichier ---
git ls-files "$ADR_DIR" \
    | grep -E "/${PATTERN}" \
    | grep -oE "$PATTERN" \
    | sort > "$TMP/files_all"
sort -u "$TMP/files_all" > "$TMP/files"

# --- Numéros référencés n'importe où dans le dépôt (prose comprise) ---
# Exclus : les fixtures de test, et le registre lui-même (il ne se justifie pas lui-même).
git ls-files -z \
    | grep -zv '^scripts/tests/' \
    | grep -zv "^${ADR_RESERVATIONS}\$" \
    | xargs -0 grep -ohE "$PATTERN" 2>/dev/null \
    | sort -u > "$TMP/refs"

# --- Numéros déclarés comme réservés ---
# Seul l'intérieur des marqueurs est lu, et seul le PREMIER champ de chaque ligne :
# la prose du registre (numéros cités en exemple ou en provenance) ne réserve rien.
if [ -f "$ADR_RESERVATIONS" ]; then
    sed -n '/adr-registry:begin/,/adr-registry:end/p' "$ADR_RESERVATIONS" \
        | awk '{print $1}' \
        | grep -xE "$PATTERN" \
        | sort -u > "$TMP/reserved"
else
    : > "$TMP/reserved"
fi

echo "ADR numbering: $(wc -l < "$TMP/files" | tr -d ' ') fichier(s), \
$(wc -l < "$TMP/refs" | tr -d ' ') numéro(s) référencé(s), \
$(wc -l < "$TMP/reserved" | tr -d ' ') réservation(s) déclarée(s)."

ERRORS=0

# --- Règle 1 : pas deux fichiers pour un même numéro ---
DUPES=$(uniq -d "$TMP/files_all")
if [ -n "$DUPES" ]; then
    echo "FAIL: un même numéro d'ADR est porté par plusieurs fichiers :"
    for n in $DUPES; do
        echo "    $n :"
        git ls-files "$ADR_DIR" | grep -F "$n" | sed 's/^/      /'
    done
    ERRORS=$((ERRORS + 1))
fi

# --- Règle 2 : référencé sans fichier ⇒ doit être déclaré réservé ---
UNDECLARED=$(comm -23 <(comm -23 "$TMP/refs" "$TMP/files") "$TMP/reserved")
if [ -n "$UNDECLARED" ]; then
    echo "FAIL: numéro(s) référencé(s) sans fichier et non déclaré(s) dans $ADR_RESERVATIONS :"
    for n in $UNDECLARED; do
        echo "    $n — référencé par :"
        git ls-files -z | grep -zv '^scripts/tests/' \
            | xargs -0 grep -lF "$n" 2>/dev/null | head -5 | sed 's/^/      /'
    done
    echo "  → écrire le fichier docs/adr/<numéro>-*.md, ou déclarer la réservation."
    ERRORS=$((ERRORS + 1))
fi

# --- Règle 3 : une réservation honorée doit être retirée du registre ---
STALE=$(comm -12 "$TMP/reserved" "$TMP/files")
if [ -n "$STALE" ]; then
    echo "FAIL: réservation(s) obsolète(s) — le fichier existe, retirer l'entrée de $ADR_RESERVATIONS :"
    echo "$STALE" | sed 's/^/    /'
    ERRORS=$((ERRORS + 1))
fi

if [ "$ERRORS" -gt 0 ]; then
    echo "BLOCKED: $ERRORS violation(s) de numérotation d'ADR."
    exit 1
fi

echo "OK: espace des numéros d'ADR cohérent (aucun doublon, aucune réservation muette)."
