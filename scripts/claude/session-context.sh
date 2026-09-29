#!/usr/bin/env bash
# Contexte SessionStart de Claude Code : où suis-je, sur quoi, dans quel état.
#
# Sortie courte, injectée dans le contexte. Chaque ligne dit d'où vient
# l'information : un `origin/main` local n'est que l'état du dernier fetch,
# jamais l'état live de GitHub. Aucun secret, aucune variable d'environnement
# n'est imprimé. Le hook n'échoue jamais la session : SessionStart n'est pas
# bloquant, une erreur se contente de réduire le contexte.
set -uo pipefail

cwd="$(jq -r '.cwd // empty' 2>/dev/null || true)"
[ -n "$cwd" ] || cwd="$PWD"
cd "$cwd" 2>/dev/null || exit 0
top="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0

branch="$(git branch --show-current 2>/dev/null)"
head="$(git rev-parse --short=12 HEAD 2>/dev/null)"
dirty="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
main_ref="$(git rev-parse --short=12 origin/main 2>/dev/null || echo '?')"
fetch_head="$(git rev-parse --git-common-dir 2>/dev/null)/FETCH_HEAD"
fetched_at="$(date -r "$fetch_head" '+%Y-%m-%d %H:%M' 2>/dev/null || echo 'jamais')"
counts="$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null || echo '? ?')"
behind="${counts%%[[:space:]]*}"
ahead="${counts##*[[:space:]]}"
worktrees="$(git worktree list 2>/dev/null | wc -l | tr -d ' ')"

echo "## Contexte Nexus RAG (hook SessionStart)"
echo "- worktree : ${top}"
echo "- branche : ${branch:-HEAD détachée} @ ${head} ; fichiers modifiés/non suivis : ${dirty}"
echo "- origin/main LOCAL (dernier fetch : ${fetched_at}) : ${main_ref} ; HEAD en avance ${ahead}, en retard ${behind}"
echo "- worktrees du dépôt : ${worktrees} (d'autres lots peuvent être actifs : ne pas y écrire)"
case "$branch" in
    main|master) echo "- ATTENTION : branche protégée. Créer un worktree et une branche de lot avant toute modification." ;;
esac

if [ -n "$branch" ] && command -v gh >/dev/null 2>&1; then
    pr="$(timeout 6 gh pr view "$branch" --json number,state,isDraft,reviewDecision,headRefOid \
        --jq '"#\(.number) \(.state) draft=\(.isDraft) review=\(.reviewDecision // "NONE") head=\(.headRefOid[0:12])"' \
        2>/dev/null)"
    if [ -n "$pr" ]; then
        echo "- PR de la branche (LIVE lu à $(date '+%H:%M')) : ${pr}"
    else
        echo "- PR de la branche : aucune trouvée ou GitHub injoignable"
    fi
fi
echo "- Tout état LIVE (main, PR, CI, serveur, base) se relit avant décision : \`git fetch\`, \`gh\`, sonde."
exit 0
