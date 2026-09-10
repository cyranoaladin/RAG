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

# Le controle et sa baseline CITENT les motifs qu ils cherchent. Sans cette
# exclusion, ils se detectent eux-memes comme secondes autorites — et le faux
# positif n apparait qu une fois les fichiers SUIVIS par git, donc apres le
# commit, jamais pendant la mise au point.
SOI=(
    ":!scripts/check-authority-uniqueness.sh"
    ":!scripts/authority-uniqueness.baseline"
    ":!scripts/tests/test-authority-uniqueness.sh"
)

pinned() {  # pinned <REGLE> -> chemins epingles, un par ligne
    awk -v r="$1" -F'\t' '!/^#/ && NF==2 && $1==r {print $2}' "$BASELINE" | sort -u
}

# git grep rend 1 quand il ne trouve rien. Ici, "rien" est un resultat
# legitime — souvent le resultat SOUHAITE — pas une erreur.
observed() {
    git -C "$REPO_ROOT" grep -lI "$@" "${SOI[@]}" 2>/dev/null | sort -u || true
}

# ATTENTION : compare doit etre appelee DIRECTEMENT, jamais au bout d un
# pipeline. Dans `observed ... | compare ...`, compare tourne dans un
# sous-shell : son STATUS=1 meurt avec lui, et le controle rend 0 alors qu il
# vient d imprimer une erreur. Les observes passent donc en 3e argument.
compare() {  # compare <REGLE> <libelle> <observes>
    local regle="$1" libelle="$2" obs="$3"
    local pin new gone
    pin="$(pinned "$regle")"
    new="$(comm -13 <(printf '%s\n' "$pin" | sed '/^$/d') \
                    <(printf '%s\n' "$obs" | sed '/^$/d'))"
    gone="$(comm -23 <(printf '%s\n' "$pin" | sed '/^$/d') \
                     <(printf '%s\n' "$obs" | sed '/^$/d'))"
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

# R1 — la matrice de servabilite reste derivee, jamais une autorite.
compare MATRIX_READER "matrice de servabilite lue en production" \
    "$(observed 'servability_matrix_v1' -- ':!*tests/*' ':!docs/*')"

# R2 — la politique d actualite n a aucun lecteur de production.
POLICY_READERS="$(observed 'nexus_rag_currentness_policy_v1' -- ':!*tests/*' ':!docs/*')"
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

# R4 — un seul PRODUCTEUR AuthorizationSetV2 hors du contrat.
#
#      Produire, charger et verifier sont trois choses. Produire, c est appeler
#      `AuthorizationSetV2.build`. Une premiere version comptait aussi le gate
#      d egalite d ensemble comme une production : elle signalait alors chaque
#      consommateur migre comme un second producteur, c est-a-dire qu elle
#      punissait exactement le progres qu on cherche.
compare AUTHORIZATION_V2_PRODUCER "producteur AuthorizationSetV2" \
    "$(observed 'AuthorizationSetV2\.build' \
        -- ':!packages/contracts/*' ':!*tests/*' ':!docs/*')"

# Mesure, pas regle : combien de consommateurs runtime verifient un document
# V2. Les DEUX points d entree comptent — le gate d egalite d ensemble seul,
# ou la verification complete qui le contient. Ne compter que le premier
# sous-estimait la migration : un consommateur qui appelle le verificateur
# complet tient le gate, par construction.
AUTH_V2_GATE_CONSUMERS="$(observed \
    'verify_authorization_binding_set_v2\|verify_authorization_set_v2' \
    -- ':!packages/contracts/*' ':!packages/release-chain/*' ':!*tests/*' ':!docs/*')"

# Mesure : combien de consommateurs passent par le chargeur canonique.
AUTH_LOADER_CONSUMERS="$(observed 'load_authorization_set' \
    -- ':!packages/contracts/*' ':!*tests/*' ':!docs/*')"
printf 'AUTH_LOADER_CONSUMERS\t%s\n' \
    "$(printf '%s\n' "$AUTH_LOADER_CONSUMERS" | sed '/^$/d' | wc -l)"
printf 'AUTH_V2_GATE_CONSUMERS\t%s\n' \
    "$(printf '%s\n' "$AUTH_V2_GATE_CONSUMERS" | sed '/^$/d' | wc -l)"

# R4b — un seul CHARGEUR. Neuf consommateurs qui choisissent chacun entre V1 et
#       V2 finissent par ne pas choisir pareil : le choix se fait une fois.
#
#       Le foyer canonique est DANS le contrat : choisir entre deux versions
#       d un contrat est une affaire de contrat, et l image du worker
#       d ingestion n embarque pas la chaine de release. Le module qui DEFINIT
#       les parseurs est donc exclu, pas le paquet entier — sinon le chargeur
#       canonique lui-meme deviendrait invisible. Le fichier d exports du
#       paquet l est aussi : re-exporter un nom n est pas decider avec.
compare AUTHORIZATION_LOADER "chargeur d autorisation" \
    "$(observed 'parse_authorization_set_v2' \
        -- ':!packages/contracts/src/nexus_contracts/authorization_set.py' \
           ':!packages/contracts/src/nexus_contracts/__init__.py' \
           ':!*tests/*' ':!docs/*')"

# R5 — un seul mecanisme de selection de release.
compare RELEASE_SELECTION "selection de release" \
    "$(observed 'select_release_authority\|resoudre_source_du_registre' \
        -- ':!*tests/*' ':!docs/*')"

# R6 — aucune autorisation V1 ne doit servir une nouvelle release.
V1_NEW="$(observed 'AUTHORIZATION_SET_PROTOCOL_VERSION[^_]' \
    -- 'services/rag-pedago/data/releases/**' 'governance/**')"
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
