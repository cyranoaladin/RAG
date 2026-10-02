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
# Tout-ou-rien : chaque renommage est VÉRIFIÉ (source disparue, cible présente) ; au premier
# échec, les renommages déjà faits sont annulés et rien n'est journalisé. Le journal n'est écrit
# qu'une fois les deux marqueurs retirés. Les marqueurs sont traités dans l'ordre inverse de
# l'exécution (préflight d'abord) : un état interrompu ne peut donc jamais faire sauter le
# préflight tout en rejouant l'installation.
#
# Refus (code 3) : un des deux marqueurs absent (rien à superséder, ou état déjà partiel),
# une cible de renommage déjà présente, un répertoire invalide.
set -euo pipefail

etat="${1:?répertoire de STATE_DIR attendu}"
stamp="${2:?horodatage attendu}"
OPERATIONS=(successor_preflight successor_readiness_install)
faits=()

refus() { echo "SUPERSESSION_REFUSEE : $1" >&2; exit 3; }
annuler() {
    local op
    for op in "${faits[@]}"; do
        mv -T "$etat/$op.done.superseded-$stamp" "$etat/$op.done" 2>/dev/null \
            || echo "SUPERSESSION_ANNULATION_INCOMPLETE : $op.done.superseded-$stamp à restaurer à la main" >&2
    done
}
[ -d "$etat" ] || refus "répertoire d'état introuvable"
[[ "$stamp" =~ ^[0-9A-Za-z._-]+$ ]] || refus "horodatage invalide"

for op in "${OPERATIONS[@]}"; do
    [ -f "$etat/$op.done" ] && [ ! -L "$etat/$op.done" ] || refus "marqueur absent ou non régulier : $op.done (rien à superséder)"
    [ ! -e "$etat/$op.done.superseded-$stamp" ] && [ ! -L "$etat/$op.done.superseded-$stamp" ] \
        || refus "cible déjà présente : $op.done.superseded-$stamp"
done

for op in "${OPERATIONS[@]}"; do
    # `mv -n` ne dit pas si elle a déplacé : on le VÉRIFIE, puis on annule tout si ce n'est pas le cas.
    mv -n "$etat/$op.done" "$etat/$op.done.superseded-$stamp" || true
    if [ -e "$etat/$op.done" ] || [ ! -f "$etat/$op.done.superseded-$stamp" ]; then
        annuler
        refus "renommage non effectué : $op.done (tout est annulé)"
    fi
    faits+=("$op")
done

for op in "${OPERATIONS[@]}"; do
    if ! printf '%s SUPERSEDE %s -> %s.done.superseded-%s\n' "$(date -u +%FT%TZ)" "$op" "$op" "$stamp" \
        >> "$etat/execution.log"; then
        annuler
        refus "journal non écrit (tout est annulé)"
    fi
done
echo "MARQUEURS_RETIRES ${OPERATIONS[*]} stamp=$stamp"
