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
# Tout-ou-rien, marqueurs ET journal : chaque renommage est VÉRIFIÉ (source disparue, cible
# présente) ; les deux enregistrements SUPERSEDE sont composés puis ajoutés en UNE écriture, une
# fois les deux marqueurs retirés. Au premier échec — renommage, écriture du journal, écriture
# partielle —, les marqueurs sont restaurés ET le journal est ramené à sa taille initiale : il ne
# reste jamais une ligne affirmant une supersession dont les `.done` ont été restaurés. Les marqueurs sont traités dans l'ordre inverse de
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
journal="$etat/execution.log"
taille_initiale=0

refus() { echo "SUPERSESSION_REFUSEE : $1" >&2; exit 3; }
annuler() {
    local op
    for op in "${faits[@]}"; do
        mv -T "$etat/$op.done.superseded-$stamp" "$etat/$op.done" 2>/dev/null \
            || echo "SUPERSESSION_ANNULATION_INCOMPLETE : $op.done.superseded-$stamp à restaurer à la main" >&2
    done
}
# Ramène le journal à sa taille initiale (écriture partielle comprise). Sans effet s'il n'a rien reçu.
restaurer_journal() {
    [ -f "$journal" ] && [ ! -L "$journal" ] || return 0
    local courante; courante="$(stat -c %s "$journal")"
    [ "$courante" = "$taille_initiale" ] && return 0
    truncate -s "$taille_initiale" "$journal" \
        && [ "$(stat -c %s "$journal")" = "$taille_initiale" ] \
        || echo "SUPERSESSION_JOURNAL_NON_RESTAURE : $journal à ramener à $taille_initiale octets à la main" >&2
}
[ -d "$etat" ] || refus "répertoire d'état introuvable"
[[ "$stamp" =~ ^[0-9A-Za-z._-]+$ ]] || refus "horodatage invalide"

for op in "${OPERATIONS[@]}"; do
    [ -f "$etat/$op.done" ] && [ ! -L "$etat/$op.done" ] || refus "marqueur absent ou non régulier : $op.done (rien à superséder)"
    [ ! -e "$etat/$op.done.superseded-$stamp" ] && [ ! -L "$etat/$op.done.superseded-$stamp" ] \
        || refus "cible déjà présente : $op.done.superseded-$stamp"
done

if [ -e "$journal" ] || [ -L "$journal" ]; then
    [ -f "$journal" ] && [ ! -L "$journal" ] && taille_initiale="$(stat -c %s "$journal")" \
        || refus "journal non régulier : $journal"
fi

for op in "${OPERATIONS[@]}"; do
    # `mv -n` ne dit pas si elle a déplacé : on le VÉRIFIE, puis on annule tout si ce n'est pas le cas.
    mv -n "$etat/$op.done" "$etat/$op.done.superseded-$stamp" || true
    if [ -e "$etat/$op.done" ] || [ ! -f "$etat/$op.done.superseded-$stamp" ]; then
        annuler
        refus "renommage non effectué : $op.done (tout est annulé)"
    fi
    faits+=("$op")
done

enregistrement=""
for op in "${OPERATIONS[@]}"; do
    enregistrement+="$(date -u +%FT%TZ) SUPERSEDE $op -> $op.done.superseded-$stamp"$'\n'
done
octets="$(printf '%s' "$enregistrement" | wc -c)"
if ! printf '%s' "$enregistrement" >> "$journal" \
    || [ "$(stat -c %s "$journal" 2>/dev/null)" != "$((taille_initiale + octets))" ]; then
    restaurer_journal
    annuler
    refus "journal non écrit ou écrit partiellement : marqueurs restaurés, journal ramené à $taille_initiale octets"
fi
echo "MARQUEURS_RETIRES ${OPERATIONS[*]} stamp=$stamp"
