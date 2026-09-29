#!/bin/sh
# Enveloppe fail-closed du garde PreToolUse.
#
# Claude Code laisse passer l'action quand un hook sort avec un code autre que
# 0 ou 2, dépasse son délai, ou ne peut pas démarrer. Cette enveloppe en POSIX
# sh ramène deux de ces pannes à un refus explicite :
#
# - interpréteur Python introuvable ou non exécutable ;
# - garde plus lent que NEXUS_GUARD_TIMEOUT secondes (10 par défaut, sous le
#   délai de 15 s déclaré dans .claude/settings.json) ou en échec.
#
# Elle ne protège PAS contre sa propre absence (branche sans ce fichier,
# chemin cassé) ni contre l'absence de /bin/sh : les règles natives
# `deny`/`ask` restent alors la seule défense.
#
# NEXUS_GUARD_PYTHON et NEXUS_GUARD_TIMEOUT existent pour les épreuves de
# panne ; ils sont lus dans l'environnement du processus Claude Code, qu'une
# commande Bash du modèle ne peut pas modifier.

deny() {
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[nexus pretool-guard] %s"}}\n' "$1"
    exit 0
}

dir=$(dirname "$0")
python=${NEXUS_GUARD_PYTHON:-python3}
limit=${NEXUS_GUARD_TIMEOUT:-10}

command -v "$python" >/dev/null 2>&1 || deny "interpréteur Python introuvable : garde inopérant, action refusée par prudence"
[ -r "$dir/pretool-guard.py" ] || deny "garde Python absent : action refusée par prudence"

if command -v timeout >/dev/null 2>&1; then
    out=$(timeout "$limit" "$python" "$dir/pretool-guard.py")
else
    out=$("$python" "$dir/pretool-guard.py")
fi
code=$?
[ "$code" -eq 124 ] && deny "garde trop lent (plus de ${limit} s) : action refusée par prudence"
[ "$code" -eq 0 ] || deny "garde en échec (code $code) : action refusée par prudence"
[ -z "$out" ] || printf '%s\n' "$out"
exit 0
