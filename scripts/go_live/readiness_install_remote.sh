#!/usr/bin/env bash
# Installe, ou supersède, la paire de readiness du complément HGGSP sur l'hôte.
# Lu par l'orchestrateur et exécuté SUR l'hôte (bash -s) ; piloté par l'environnement :
#
#   D        répertoire des readiness de l'hôte
#   M, B     noms du manifeste V1 et de la liaison signée
#   NEW_M, NEW_B   empreintes sha256 de la nouvelle paire, déjà déposée dans INCOMING
#   OLD_M, OLD_B   empreintes pinnées de la paire que cette installation peut superséder
#                  (vides : aucune supersession n'est permise)
#   INCOMING répertoire de dépôt de la nouvelle paire, sur le même système de fichiers que D
#   STAMP    horodatage de l'archive
#
# Décisions, toutes fail-closed (code 4) :
#   aucune paire distante          -> installation
#   paire distante == nouvelle     -> déjà installée, rien n'est écrit
#   paire distante == OLD_M/OLD_B  -> supersession : l'ancienne paire est ARCHIVÉE
#                                     (copie vérifiée), puis remplacée par rename atomique
#   tout autre état (un seul fichier, empreinte inconnue, paire mixte) -> refus
#
# L'ancienne paire n'est jamais supprimée. Une paire mixte n'est jamais valide : la liaison
# signée est liée à l'empreinte du manifeste V1, donc les consommateurs la refusent. Les deux
# renommages ne sont pas atomiques ENSEMBLE : si le second échoue, l'ancienne paire est RESTAURÉE
# depuis l'archive (copie puis rename par fichier) ; si même la restauration échoue, le script le
# dit et l'archive reste la preuve. Un lien symbolique, même cassé, est une anomalie : refus.
# Le dépôt entrant est nettoyé à la sortie, y compris sur refus (il ne contient qu'une copie).
set -euo pipefail
umask 077

sha() { sha256sum "$1" | cut -d' ' -f1; }
existe() { [ -e "$1" ] || [ -L "$1" ]; }
reguliere() { [ -f "$1" ] && [ ! -L "$1" ]; }
refus() { echo "READINESS_REFUSEE : $1" >&2; exit 4; }

: "${D:?}" "${M:?}" "${B:?}" "${NEW_M:?}" "${NEW_B:?}" "${INCOMING:?}" "${STAMP:?}"
# Le dépôt entrant est nettoyé à la sortie : il doit être un sous-répertoire STRICT de D, jamais D
# lui-même (ce nettoyage supprimerait la paire active) ni un chemin qui en sorte.
[[ "$INCOMING" == "$D"/?* && "$INCOMING" != *..* ]] || { echo "READINESS_REFUSEE : dépôt entrant hors de $D" >&2; exit 4; }
nettoyer() { rm -f "$INCOMING/$M" "$INCOMING/$B"; rmdir "$INCOMING" 2>/dev/null || true; }
trap nettoyer EXIT
OLD_M="${OLD_M:-}"; OLD_B="${OLD_B:-}"
[[ "$NEW_M" =~ ^[0-9a-f]{64}$ && "$NEW_B" =~ ^[0-9a-f]{64}$ ]] || refus "empreintes de la nouvelle paire invalides"
if [ -n "$OLD_M$OLD_B" ]; then
    [[ "$OLD_M" =~ ^[0-9a-f]{64}$ && "$OLD_B" =~ ^[0-9a-f]{64}$ ]] || refus "empreintes de l'ancienne paire invalides"
    [ "$OLD_M" != "$NEW_M" ] && [ "$OLD_B" != "$NEW_B" ] || refus "l'ancienne et la nouvelle paire sont identiques"
fi
[[ "$STAMP" =~ ^[0-9A-Za-z._-]+$ ]] || refus "horodatage invalide"

reguliere "$INCOMING/$M" && reguliere "$INCOMING/$B" || refus "nouvelle paire absente ou non régulière dans $INCOMING"
[ "$(sha "$INCOMING/$M")" = "$NEW_M" ] || refus "manifeste déposé différent de l'empreinte attendue"
[ "$(sha "$INCOMING/$B")" = "$NEW_B" ] || refus "liaison déposée différente de l'empreinte attendue"

existe_m=0; existe_b=0
existe "$D/$M" && existe_m=1
existe "$D/$B" && existe_b=1

if [ "$existe_m$existe_b" = "00" ]; then
    install -d -m 0700 "$D"
    mv -T "$INCOMING/$M" "$D/$M"
    if ! mv -T "$INCOMING/$B" "$D/$B"; then
        mv -T "$D/$M" "$INCOMING/$M" || true  # annule : pas de paire partielle
        refus "installation interrompue : manifeste remis dans $INCOMING"
    fi
    chmod 600 "$D/$M" "$D/$B"
    [ "$(sha "$D/$M")" = "$NEW_M" ] && [ "$(sha "$D/$B")" = "$NEW_B" ] || refus "paire installée divergente"
    nettoyer
    echo "READINESS_INSTALLED manifest=$NEW_M binding=$NEW_B"
    exit 0
fi

[ "$existe_m$existe_b" = "11" ] || refus "paire distante partielle (un seul fichier présent)"
reguliere "$D/$M" && reguliere "$D/$B" || refus "un élément distant n'est pas un fichier régulier (lien symbolique ou autre)"
rm_sha="$(sha "$D/$M")"; rb_sha="$(sha "$D/$B")"

if [ "$rm_sha" = "$NEW_M" ] && [ "$rb_sha" = "$NEW_B" ]; then
    nettoyer
    echo "READINESS_ALREADY_INSTALLED manifest=$NEW_M binding=$NEW_B"
    exit 0
fi

[ -n "$OLD_M" ] && [ "$rm_sha" = "$OLD_M" ] && [ "$rb_sha" = "$OLD_B" ] \
    || refus "paire distante divergente et non supersédable (manifeste $rm_sha, liaison $rb_sha)"

archive="$D/superseded/$STAMP-${rm_sha:0:12}"
[ ! -e "$archive" ] || refus "archive de supersession déjà présente : $archive"
install -d -m 0700 "$D/superseded" "$archive"
cp -p "$D/$M" "$archive/$M"
cp -p "$D/$B" "$archive/$B"
[ "$(sha "$archive/$M")" = "$OLD_M" ] && [ "$(sha "$archive/$B")" = "$OLD_B" ] \
    || refus "archive de l'ancienne paire non conforme : rien n'est remplacé"
chmod 400 "$archive/$M" "$archive/$B"

restaurer() {  # remet l'ancienne paire depuis l'archive : copie à côté, puis rename atomique par fichier
    local f
    for f in "$M" "$B"; do
        cp -p "$archive/$f" "$D/$f.restauration" && mv -T "$D/$f.restauration" "$D/$f" || return 1
    done
    chmod 600 "$D/$M" "$D/$B"
    [ "$(sha "$D/$M")" = "$OLD_M" ] && [ "$(sha "$D/$B")" = "$OLD_B" ]
}
echec_remplacement() {
    if restaurer; then
        refus "$1 : ancienne paire restaurée depuis $archive"
    fi
    refus "$1 ET restauration impossible : l'ancienne paire reste archivée dans $archive"
}
if ! { mv -T "$INCOMING/$M" "$D/$M" && mv -T "$INCOMING/$B" "$D/$B"; }; then
    echec_remplacement "remplacement interrompu"
fi
chmod 600 "$D/$M" "$D/$B"
if ! { [ "$(sha "$D/$M")" = "$NEW_M" ] && [ "$(sha "$D/$B")" = "$NEW_B" ]; }; then
    echec_remplacement "paire supersédée divergente"
fi
nettoyer
echo "READINESS_SUPERSEDED old_manifest=$OLD_M old_binding=$OLD_B new_manifest=$NEW_M new_binding=$NEW_B archive=$archive"
