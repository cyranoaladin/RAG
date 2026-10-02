#!/usr/bin/env bash
# Retire (sans jamais supprimer) les marqueurs de la preuve runtime supersédée.
#
# Usage : retire_runtime_markers.sh <STATE_DIR> <HORODATAGE>
#
# Les marqueurs de `successor_readiness_install` et de `successor_preflight` attestent d'un
# runtime (images, readiness) qu'un amendement a supersédé : ils sont RENOMMÉS
# `<op>.done.superseded-<horodatage>` et gardés comme preuve, ce qui oblige l'orchestrateur à
# rejouer ces deux étapes. Les marqueurs des faits persistants (migration 020, r4) et de toute
# autre étape ne sont jamais touchés.
#
# Refus (code 3) : un des deux marqueurs absent (rien à superséder, ou état déjà partiel),
# une cible de renommage déjà présente, un répertoire invalide. Aucun renommage partiel :
# tout est vérifié avant le premier.
set -euo pipefail

etat="${1:?répertoire de STATE_DIR attendu}"
stamp="${2:?horodatage attendu}"
OPERATIONS=(successor_readiness_install successor_preflight)

refus() { echo "SUPERSESSION_REFUSEE : $1" >&2; exit 3; }
[ -d "$etat" ] || refus "répertoire d'état introuvable"
[[ "$stamp" =~ ^[0-9A-Za-z._-]+$ ]] || refus "horodatage invalide"

for op in "${OPERATIONS[@]}"; do
    [ -f "$etat/$op.done" ] || refus "marqueur absent : $op.done (rien à superséder)"
    [ ! -e "$etat/$op.done.superseded-$stamp" ] || refus "cible déjà présente : $op.done.superseded-$stamp"
done

for op in "${OPERATIONS[@]}"; do
    mv -n "$etat/$op.done" "$etat/$op.done.superseded-$stamp"
    printf '%s SUPERSEDE %s -> %s.done.superseded-%s\n' "$(date -u +%FT%TZ)" "$op" "$op" "$stamp" \
        >> "$etat/execution.log"
done
echo "MARQUEURS_RETIRES ${OPERATIONS[*]} stamp=$stamp"
