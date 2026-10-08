#!/usr/bin/env bash
# Contrôle Stop léger : état du worktree en fin de tour.
#
# Ne bloque la fin du tour (sortie 2) que pour ce qui doit être corrigé avant
# de rendre la main : espaces fautifs dans le diff, secret évident dans un
# fichier modifié. Le reste est un rappel non bloquant, affiché à Claude via
# stderr seulement si la fin du tour est bloquée ; sinon il reste silencieux.
# `stop_hook_active` évite de boucler : un second passage ne rebloque pas.
# Aucune valeur de secret n'est imprimée : seulement le fichier concerné.
set -uo pipefail

input="$(cat)"
active="$(jq -r '.stop_hook_active // false' <<<"$input" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"$input" 2>/dev/null)"
[ "$active" = "true" ] && exit 0
cd "${cwd:-$PWD}" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

issues=""
ws="$(git diff --check 2>&1 | head -5; git diff --cached --check 2>&1 | head -5)"
[ -z "$ws" ] || issues="${issues}- git diff --check signale :\n${ws}\n"

secret_re='(-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|postgres(ql)?://[^:@/[:space:]]+:[^@$<{[:space:]]{6,}@)'
while IFS= read -r -d '' path; do
    [ -f "$path" ] || continue
    if grep -IEq "$secret_re" -- "$path" 2>/dev/null; then
        issues="${issues}- secret probable dans ${path} (valeur non affichée)\n"
    fi
done < <({ git diff --name-only -z; git diff --cached --name-only -z; git ls-files --others --exclude-standard -z; } 2>/dev/null)

suspect_re='(^|/)(\.env(\.[^/]*)?|id_(rsa|ed25519|ecdsa)|\.pgpass)$|\.(pem|key|p12|seed|dump|sql\.gz|pgdump)$'
while IFS= read -r -d '' path; do
    case "$path" in */.env.example|.env.example) continue ;; esac
    if grep -Eq "$suspect_re" <<<"$path"; then
        issues="${issues}- fichier non suivi suspect (secret, clé ou dump) : ${path} — l'ignorer ou le déplacer hors du dépôt\n"
    fi
done < <(git ls-files --others --exclude-standard -z 2>/dev/null)

if [ -n "$issues" ]; then
    printf 'Contrôle de fin de tour :\n%b\nCorriger avant de rendre la main. Rappel : ne déclarer aucun test comme passé sans l avoir exécuté.\n' "$issues" >&2
    exit 2
fi
exit 0
