#!/usr/bin/env bash
# Un concept, une autorite.
#
# Ce controle ne mesure pas la qualite du code : il mesure combien d endroits
# DECIDENT la meme chose. Deux endroits qui decident finissent toujours par
# diverger, et le jour ou ils divergent, aucun des deux ne fait autorite.
#
# Il echoue quand un fichier non epingle se met a decider, quand la politique
# d actualite s arroge la decision d une autre autorite, ou quand la matrice
# de servabilite devient une source de verite de production.
set -euo pipefail

REPO_ROOT="${1:-$(git rev-parse --show-toplevel)}"
BASELINE="$REPO_ROOT/scripts/authority-uniqueness.baseline"
POLICY="$REPO_ROOT/services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml"

if ! INSIDE="$(git -C "$REPO_ROOT" rev-parse --is-inside-work-tree 2>/dev/null)" \
        || [ "$INSIDE" != "true" ]; then
    echo "ERROR: repository root is not a Git worktree: $REPO_ROOT" >&2
    exit 2
fi
[ -f "$BASELINE" ] || { echo "ERROR: baseline absente: $BASELINE" >&2; exit 2; }

STATUS=0

pinned() {  # pinned <REGLE> -> chemins epingles, un par ligne
    awk -v r="$1" -F'\t' '!/^#/ && NF==2 && $1==r {print $2}' "$BASELINE" | sort -u
}

# git grep rend 1 quand il ne trouve rien. Ici, "rien" est un resultat
# legitime — souvent le resultat SOUHAITE — pas une erreur.
observed() { git -C "$REPO_ROOT" grep -lI "$@" 2>/dev/null | sort -u || true; }

compare() {  # compare <REGLE> <libelle> <observes...>
    local regle="$1" libelle="$2"; shift 2
    local pin obs new gone
    pin="$(pinned "$regle")"
    obs="$(cat)"
    new="$(comm -13 <(printf '%s\n' "$pin") <(printf '%s\n' "$obs") | sed '/^$/d')"
    gone="$(comm -23 <(printf '%s\n' "$pin") <(printf '%s\n' "$obs") | sed '/^$/d')"
    if [ -n "$new" ]; then
        echo "ERROR: $libelle — autorite non epinglee :" >&2
        printf '  %s\n' $new >&2
        echo "  Si cette seconde autorite est deliberee, ajoute-la a la baseline" >&2
        echo "  en disant pourquoi. Sinon, fais consommer l autorite canonique." >&2
        STATUS=1
    fi
    if [ -n "$gone" ]; then
        echo "NOTE: $libelle — epinglee mais absente, retire ces lignes de la baseline :" >&2
        printf '  %s\n' $gone >&2
        STATUS=1
    fi
    printf '%s\t%s\n' "$regle" "$(printf '%s\n' "$obs" | sed '/^$/d' | wc -l)"
}

echo "== NEXUS-AUTHORITY-UNIQUENESS-V1"

# R1 — la matrice de servabilite reste derivee.
observed 'servability_matrix_v1' -- ':!*tests/*' ':!docs/*' \
    | compare MATRIX_READER "matrice de servabilite lue en production"

# R2 — la politique d actualite n a aucun lecteur de production.
POLICY_READERS="$(observed 'nexus_rag_currentness_policy_v1' -- ':!*tests/*' ':!docs/*' || true)"
POLICY_READERS="$(printf '%s\n' "$POLICY_READERS" | sed '/^$/d')"
if [ -n "$POLICY_READERS" ]; then
    echo "ERROR: la politique d actualite est applied=false et a un lecteur de production :" >&2
    printf '  %s\n' $POLICY_READERS >&2
    echo "  La lire en production revient a l appliquer sans son ADR." >&2
    STATUS=1
fi
printf 'CURRENTNESS_POLICY_PRODUCTION_READERS\t%s\n' \
    "$(printf '%s\n' "$POLICY_READERS" | sed '/^$/d' | wc -l)"

# R3 — la politique d actualite ne decide rien qui appartienne a un autre gate.
if [ -f "$POLICY" ]; then
    INTRUS=""
    for gate in PROGRAM_VERSION_COMPATIBLE PII_GATE_PASS RIGHTS_GATE_PASS \
                CLASSIFICATION_GATE_PASS PLACEMENT_GATE_PASS; do
        if awk '/^  conditions_all_required:/{f=1;next} /^  [a-z_]+:/{f=0} f' "$POLICY" \
                | grep -qF -- "- $gate"; then
            INTRUS="$INTRUS $gate"
        fi
    done
    if [ -n "$INTRUS" ]; then
        echo "ERROR: la politique d actualite s arroge la decision d un autre gate :$INTRUS" >&2
        echo "  Chacune de ces conditions appartient a une autre autorite (ADR-0055)." >&2
        STATUS=1
    fi
    printf 'CURRENTNESS_FOREIGN_GATE_CONDITIONS\t%s\n' "$(printf '%s' "$INTRUS" | wc -w)"
fi

# R4 — un seul producteur AuthorizationSetV2 hors du contrat.
observed 'AuthorizationSetV2\.build\|parse_authorization_set_v2\|verify_authorization_binding_set_v2' \
    -- ':!packages/contracts/*' ':!*tests/*' ':!docs/*' \
    | compare AUTHORIZATION_V2_PRODUCER "producteur AuthorizationSetV2"

# R5 — un seul mecanisme de selection de release.
observed 'select_release_authority\|resoudre_source_du_registre' \
    -- ':!*tests/*' ':!docs/*' \
    | compare RELEASE_SELECTION "selection de release"

# R6 — aucune autorisation V1 ne doit servir une nouvelle release.
V1_NEW="$(observed 'AUTHORIZATION_SET_PROTOCOL_VERSION[^_]' \
    -- 'services/rag-pedago/data/releases/**' 'governance/**' || true)"
V1_NEW="$(printf '%s\n' "$V1_NEW" | sed '/^$/d')"
if [ -n "$V1_NEW" ]; then
    echo "ERROR: autorisation V1 posee dans un repertoire de release :" >&2
    printf '  %s\n' $V1_NEW >&2
    STATUS=1
fi
printf 'V1_NEW_RELEASE_FALLBACK\t%s\n' "$(printf '%s\n' "$V1_NEW" | sed '/^$/d' | wc -l)"

if [ "$STATUS" -ne 0 ]; then
    echo "NEXUS-AUTHORITY-UNIQUENESS-V1: FAIL" >&2
else
    echo "NEXUS-AUTHORITY-UNIQUENESS-V1: PASS"
fi
exit "$STATUS"
