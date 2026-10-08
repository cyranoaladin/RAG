#!/usr/bin/env bash
# Installe, ou supersède, la paire de readiness du complément HGGSP sur l'hôte.
# Lu par l'orchestrateur et exécuté SUR l'hôte (bash -s) ; piloté par l'environnement :
#
#   D        répertoire des readiness de l'hôte (sans « / » final)
#   M, B     noms (basename) du manifeste V1 et de la liaison signée
#   NEW_M, NEW_B   empreintes sha256 de la nouvelle paire, déjà déposée dans INCOMING
#   OLD_M, OLD_B   empreintes pinnées de la paire que cette installation peut superséder
#                  (vides : aucune supersession n'est permise)
#   INCOMING dépôt de la nouvelle paire : enfant direct de D, nommé .incoming-*
#   STAMP    horodatage de l'archive
#
# Décisions, toutes fail-closed (code 4) :
#   aucune paire distante          -> installation
#   paire distante == nouvelle     -> déjà installée, rien n'est écrit
#   paire distante == OLD_M/OLD_B  -> supersession : l'ancienne paire est ARCHIVÉE
#                                     (copie vérifiée), puis remplacée par rename
#   tout autre état (un seul fichier, empreinte inconnue, paire mixte, lien symbolique) -> refus
#
# Garanties, et leurs limites :
#   * l'ancienne paire n'est jamais supprimée : elle reste dans l'archive ;
#   * les deux renommages ne sont PAS atomiques ensemble. Si le second échoue, la restauration
#     prépare d'abord les DEUX anciens fichiers sous des noms temporaires vérifiés, puis les
#     renomme ; si elle n'aboutit pas, le script REFUSE en disant l'état exact des deux fichiers
#     (jamais « paire restaurée » sans l'avoir vérifié) ;
#   * toutes les entrées sont validées AVANT que le nettoyage de sortie existe : ni nom, ni
#     chemin non validé ne peut le faire supprimer autre chose que les deux fichiers déposés ;
#   * INCOMING doit être un répertoire réel (jamais un lien), enfant direct de D ; le nettoyage
#     le revérifie avant de supprimer. Un répertoire de D remplaçable par un tiers n'est pas
#     défendu ici : D est supposé appartenir à root et être en 0700.
set -euo pipefail
umask 077

sha() { sha256sum "$1" | cut -d' ' -f1; }
existe() { [ -e "$1" ] || [ -L "$1" ]; }
reguliere() { [ -f "$1" ] && [ ! -L "$1" ]; }
refus() { echo "READINESS_REFUSEE : $1" >&2; exit 4; }
nom_valide() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ && "$1" != *..* ]]; }
hex64() { [[ "$1" =~ ^[0-9a-f]{64}$ ]]; }

# ── toutes les entrées, validées AVANT tout nettoyage possible ────────────────
: "${D:?}" "${M:?}" "${B:?}" "${NEW_M:?}" "${NEW_B:?}" "${INCOMING:?}" "${STAMP:?}"
OLD_M="${OLD_M:-}"; OLD_B="${OLD_B:-}"
nom_valide "$M" && nom_valide "$B" && [ "$M" != "$B" ] || refus "noms de fichiers invalides (basename simple requis)"
hex64 "$NEW_M" && hex64 "$NEW_B" || refus "empreintes de la nouvelle paire invalides"
if [ -n "$OLD_M$OLD_B" ]; then
    hex64 "$OLD_M" && hex64 "$OLD_B" || refus "empreintes de l'ancienne paire invalides"
    [ "$OLD_M" != "$NEW_M" ] && [ "$OLD_B" != "$NEW_B" ] || refus "l'ancienne et la nouvelle paire sont identiques"
fi
[[ "$STAMP" =~ ^[0-9A-Za-z._-]+$ ]] || refus "horodatage invalide"
[[ "$D" == /* && "$D" != */ && "$D" != *..* ]] || refus "destination invalide (chemin absolu, sans « / » final)"
[ -d "$D" ] && [ ! -L "$D" ] || refus "destination absente ou lien symbolique : $D"
[ "$(dirname -- "$INCOMING")" = "$D" ] && [[ "$(basename -- "$INCOMING")" =~ ^\.incoming-[A-Za-z0-9._-]+$ ]] \
    || refus "dépôt entrant : doit être un enfant direct $D/.incoming-*"
[ -d "$INCOMING" ] && [ ! -L "$INCOMING" ] || refus "dépôt entrant absent, non répertoire ou lien symbolique"

# Le nettoyage de sortie ne supprime que les deux fichiers déposés, après avoir revérifié le dépôt.
nettoyer() {
    [ -d "$INCOMING" ] && [ ! -L "$INCOMING" ] || return 0
    rm -f -- "$INCOMING/$M" "$INCOMING/$B"
    rmdir -- "$INCOMING" 2>/dev/null || true
}
trap nettoyer EXIT

reguliere "$INCOMING/$M" && reguliere "$INCOMING/$B" || refus "nouvelle paire absente ou non régulière dans $INCOMING"
[ "$(sha "$INCOMING/$M")" = "$NEW_M" ] || refus "manifeste déposé différent de l'empreinte attendue"
[ "$(sha "$INCOMING/$B")" = "$NEW_B" ] || refus "liaison déposée différente de l'empreinte attendue"

# État d'un fichier distant, pour des messages exacts : absent | lien | ancien | nouveau | inconnu
etat_de() {  # $1 = chemin ; $2 = empreinte « ancienne » ; $3 = empreinte « nouvelle »
    if [ -L "$1" ]; then echo lien
    elif [ ! -e "$1" ]; then echo absent
    elif [ ! -f "$1" ]; then echo non-regulier
    else
        local s; s="$(sha "$1")"
        if [ -n "$2" ] && [ "$s" = "$2" ]; then echo ancien
        elif [ "$s" = "$3" ]; then echo nouveau
        else echo inconnu; fi
    fi
}
etat_paire() { echo "manifeste=$(etat_de "$D/$M" "$OLD_M" "$NEW_M") liaison=$(etat_de "$D/$B" "$OLD_B" "$NEW_B")"; }

existe_m=0; existe_b=0
existe "$D/$M" && existe_m=1
existe "$D/$B" && existe_b=1

# ── aucune paire distante : installation ──────────────────────────────────────
if [ "$existe_m$existe_b" = "00" ]; then
    mv -T -- "$INCOMING/$M" "$D/$M"
    if ! mv -T -- "$INCOMING/$B" "$D/$B"; then
        # Retrait de notre propre copie, puis VÉRIFICATION : jamais de paire partielle active.
        mv -T -- "$D/$M" "$INCOMING/$M" 2>/dev/null || true
        if [ ! -e "$D/$M" ] && [ ! -L "$D/$M" ] && [ ! -e "$D/$B" ] && [ ! -L "$D/$B" ]; then
            refus "installation interrompue : aucune paire active (le dépôt entrant est nettoyé à la sortie, rien à y récupérer ; déposer à nouveau la paire pour réessayer)"
        fi
        refus "installation interrompue ET retrait impossible : paire PARTIELLE active dans $D ($(etat_paire)) ; à corriger à la main"
    fi
    chmod 600 "$D/$M" "$D/$B"
    [ "$(sha "$D/$M")" = "$NEW_M" ] && [ "$(sha "$D/$B")" = "$NEW_B" ] || refus "paire installée divergente ($(etat_paire))"
    echo "READINESS_INSTALLED manifest=$NEW_M binding=$NEW_B"
    exit 0
fi

[ "$existe_m$existe_b" = "11" ] || refus "paire distante partielle (un seul fichier présent) : $(etat_paire)"
reguliere "$D/$M" && reguliere "$D/$B" || refus "un élément distant n'est pas un fichier régulier (lien symbolique ou autre) : $(etat_paire)"
rm_sha="$(sha "$D/$M")"; rb_sha="$(sha "$D/$B")"

if [ "$rm_sha" = "$NEW_M" ] && [ "$rb_sha" = "$NEW_B" ]; then
    echo "READINESS_ALREADY_INSTALLED manifest=$NEW_M binding=$NEW_B"
    exit 0
fi

[ -n "$OLD_M" ] && [ "$rm_sha" = "$OLD_M" ] && [ "$rb_sha" = "$OLD_B" ] \
    || refus "paire distante divergente et non supersédable (manifeste $rm_sha, liaison $rb_sha)"

# ── supersession : archive vérifiée, puis remplacement ────────────────────────
archive="$D/superseded/$STAMP-${rm_sha:0:12}"
[ ! -e "$archive" ] || refus "archive de supersession déjà présente : $archive"
install -d -m 0700 "$D/superseded" "$archive"
cp -p -- "$D/$M" "$archive/$M"
cp -p -- "$D/$B" "$archive/$B"
[ "$(sha "$archive/$M")" = "$OLD_M" ] && [ "$(sha "$archive/$B")" = "$OLD_B" ] \
    || refus "archive de l'ancienne paire non conforme : rien n'est remplacé"
chmod 400 "$archive/$M" "$archive/$B"

temp_m="$D/$M.restauration"; temp_b="$D/$B.restauration"
retirer_temporaires() { rm -f -- "$temp_m" "$temp_b"; }

# Remet l'ancienne paire : les DEUX anciens fichiers sont d'abord copiés et vérifiés sous des
# noms temporaires, puis renommés. Succès seulement si les deux fichiers actifs ont l'ancienne
# empreinte, vérifiée à l'instant.
restaurer() {
    retirer_temporaires
    cp -p -- "$archive/$M" "$temp_m" && cp -p -- "$archive/$B" "$temp_b" || return 1
    [ "$(sha "$temp_m")" = "$OLD_M" ] && [ "$(sha "$temp_b")" = "$OLD_B" ] || return 1
    chmod 600 "$temp_m" "$temp_b"
    mv -T -- "$temp_m" "$D/$M" && mv -T -- "$temp_b" "$D/$B" || return 1
    [ "$(sha "$D/$M")" = "$OLD_M" ] && [ "$(sha "$D/$B")" = "$OLD_B" ]
}

echec_remplacement() {  # $1 = cause
    if restaurer; then
        refus "$1 : ancienne paire restaurée et vérifiée depuis $archive ($(etat_paire))"
    fi
    retirer_temporaires
    refus "$1 ET restauration INCOMPLÈTE : la paire active n'est PAS garantie valide ($(etat_paire)) ; l'ancienne paire est intacte dans $archive"
}

if ! { mv -T -- "$INCOMING/$M" "$D/$M" && mv -T -- "$INCOMING/$B" "$D/$B"; }; then
    echec_remplacement "remplacement interrompu"
fi
chmod 600 "$D/$M" "$D/$B"
if ! { [ "$(sha "$D/$M")" = "$NEW_M" ] && [ "$(sha "$D/$B")" = "$NEW_B" ]; }; then
    echec_remplacement "paire supersédée divergente"
fi
echo "READINESS_SUPERSEDED old_manifest=$OLD_M old_binding=$OLD_B new_manifest=$NEW_M new_binding=$NEW_B archive=$archive"
