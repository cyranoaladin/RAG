#!/usr/bin/env bash
# Un garde-fou qu aucune sabotage ne fait tomber ne garde rien.
#
# Chaque cas ci-dessous reintroduit UNE des six situations que le controle
# pretend detecter, dans une copie jetable du depot, et exige un echec.
set -euo pipefail

REPO_ROOT="${1:-$(git rev-parse --show-toplevel)}"
GUARD="$REPO_ROOT/scripts/check-authority-uniqueness.sh"
POLICY_REL="services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml"
FAILURES=0

banc() {  # banc -> imprime le chemin d une copie jetable, deja un depot git
    local dir; dir="$(mktemp -d)"
    git -C "$REPO_ROOT" archive HEAD | tar -x -C "$dir"
    git -C "$dir" init -q
    git -C "$dir" add -A >/dev/null 2>&1
    git -c user.email=t@t -c user.name=t -C "$dir" commit -qm banc >/dev/null 2>&1
    printf '%s' "$dir"
}

exige_echec() {  # exige_echec <libelle> <dir>
    local libelle="$1" dir="$2"
    if bash "$GUARD" "$dir" >/dev/null 2>&1; then
        echo "NON DETECTE: $libelle" >&2
        FAILURES=$((FAILURES + 1))
    else
        echo "detecte: $libelle"
    fi
    rm -rf -- "$dir"
}

# 1. un second lecteur de la matrice, en production
D="$(banc)"
printf 'MATRICE = "docs/reports/handoff/servability_matrix_v1.json"\n' \
    > "$D/services/rag-engine/src/ingestor/faux_lecteur_matrice.py"
git -C "$D" add -A >/dev/null 2>&1
exige_echec "matrice lue par un chemin de production" "$D"

# 2. un lecteur de production de la politique d actualite
D="$(banc)"
printf 'P = "configs/proposals/nexus_rag_currentness_policy_v1.yml"\n' \
    > "$D/services/rag-pedago/rag_pedago/governance/faux_lecteur_politique.py"
git -C "$D" add -A >/dev/null 2>&1
exige_echec "politique applied=false lue en production" "$D"

# 3. la politique se rearroge la decision programme
D="$(banc)"
python3 - "$D/$POLICY_REL" <<'PY'
import io, sys
p = sys.argv[1]
s = io.open(p, encoding="utf-8").read()
s = s.replace("    - NO_KNOWN_SUPERSEDING_CONFLICT",
              "    - NO_KNOWN_SUPERSEDING_CONFLICT\n    - PROGRAM_VERSION_COMPATIBLE", 1)
io.open(p, "w", encoding="utf-8").write(s)
PY
git -C "$D" add -A >/dev/null 2>&1
exige_echec "gate etranger reintroduit dans la politique" "$D"

# 4. un second producteur AuthorizationSetV2
D="$(banc)"
printf 'from nexus_contracts.authorization_set import AuthorizationSetV2\nx = AuthorizationSetV2.build\n' \
    > "$D/services/rag-engine/src/ingestor/faux_producteur_v2.py"
git -C "$D" add -A >/dev/null 2>&1
exige_echec "second producteur AuthorizationSetV2" "$D"

# 5. un troisieme selecteur de release
D="$(banc)"
printf 'def select_release_authority():\n    return "moi"\n' \
    > "$D/services/rag-engine/src/ingestor/faux_selecteur_release.py"
git -C "$D" add -A >/dev/null 2>&1
exige_echec "selecteur de release supplementaire" "$D"

# 6. une autorisation V1 posee dans un repertoire de release
D="$(banc)"
mkdir -p "$D/governance/authorizations"
printf '{"protocol": "AUTHORIZATION_SET_PROTOCOL_VERSION-x"}\n' \
    > "$D/governance/authorizations/faux.json"
git -C "$D" add -A >/dev/null 2>&1
exige_echec "autorisation V1 dans un repertoire de release" "$D"

# 7. controle negatif : un depot intact et COMMITE doit passer.
#
#    Le banc commite tout. C est essentiel : `git grep` ne voit que les
#    fichiers SUIVIS. Lancer ce controle negatif sur le worktree vivant, ou
#    les fichiers du garde-fou peuvent encore etre non suivis, laisserait
#    passer un garde-fou qui se detecte lui-meme — le defaut exact que le
#    cas 8 verifie.
D="$(banc)"
if bash "$GUARD" "$D" >/dev/null 2>&1; then
    echo "detecte: le depot intact et commite passe"
else
    echo "NON DETECTE: le depot intact devrait passer" >&2
    bash "$GUARD" "$D" >&2 || true
    FAILURES=$((FAILURES + 1))
fi
rm -rf -- "$D"

# 8. le garde-fou ne doit pas se prendre lui-meme pour une seconde autorite.
#
#    Il CITE les motifs qu il cherche. Sans exclusion de ses propres fichiers,
#    il se signale des qu il est suivi par git — donc apres le commit, jamais
#    pendant la mise au point.
D="$(banc)"
SORTIE="$(bash "$GUARD" "$D" 2>&1 || true)"
if printf '%s' "$SORTIE" | grep -q 'scripts/check-authority-uniqueness.sh\|scripts/authority-uniqueness.baseline\|scripts/tests/test-authority-uniqueness.sh'; then
    echo "NON DETECTE: le garde-fou se signale lui-meme" >&2
    FAILURES=$((FAILURES + 1))
else
    echo "detecte: le garde-fou ne se signale pas lui-meme"
fi
rm -rf -- "$D"

if [ "$FAILURES" -ne 0 ]; then
    echo "test-authority-uniqueness: $FAILURES cas non detectes" >&2
    exit 1
fi
echo "test-authority-uniqueness: PASS"
