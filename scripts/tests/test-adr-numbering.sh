#!/usr/bin/env bash
# test-adr-numbering.sh — Suite de tests du garde-fou de numérotation des ADR.
#
# Chaque cas monte un dépôt git jetable, y copie le garde-fou, et vérifie son verdict.
# Le cas « la prose ne réserve rien » est une régression : la première version du garde-fou
# lisait tous les numéros du registre, y compris ceux cités en colonne de provenance, et
# tenait ADR-0044 pour réservé.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD_SCRIPT="$SCRIPT_DIR/../check-adr-numbering.sh"

PASS=0
FAIL=0
TOTAL=0

assert_exit() {
    local name="$1" expected="$2" actual="$3"
    TOTAL=$((TOTAL + 1))
    if [ "$actual" -eq "$expected" ]; then
        echo "  PASS  $name (exit $actual)"; PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (expected exit $expected, got $actual)"; FAIL=$((FAIL + 1))
        echo "$LAST_OUTPUT" | sed 's/^/          /'
    fi
}

assert_contains() {
    local name="$1" output="$2" pattern="$3"
    TOTAL=$((TOTAL + 1))
    if echo "$output" | grep -q "$pattern"; then
        echo "  PASS  $name (contains '$pattern')"; PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (missing '$pattern')"; FAIL=$((FAIL + 1))
    fi
}

# --- Dépôt jetable : docs/adr/ADR-0001-*.md et le garde-fou ---
make_sandbox() {
    local dir; dir="$(mktemp -d)"
    mkdir -p "$dir/scripts/tests" "$dir/docs/adr" "$dir/docs/reports"
    cp "$GUARD_SCRIPT" "$dir/scripts/check-adr-numbering.sh"
    echo "# ADR-0001" > "$dir/docs/adr/ADR-0001-fondation.md"
    git -C "$dir" init -q
    git -C "$dir" config user.email t@t; git -C "$dir" config user.name t
    echo "$dir"
}

run_guard() {
    local dir="$1" code
    git -C "$dir" add -A >/dev/null 2>&1
    set +e
    LAST_OUTPUT=$(cd "$dir" && bash scripts/check-adr-numbering.sh 2>&1)
    code=$?
    set -e
    LAST_EXIT="$code"
}

echo "=== check-adr-numbering.sh ==="

# 1. Dépôt sain
D=$(make_sandbox); run_guard "$D"
assert_exit "depot_sain" 0 "$LAST_EXIT"
assert_contains "depot_sain_msg" "$LAST_OUTPUT" "OK:"
rm -rf "$D"

# 2. Deux fichiers pour un même numéro
D=$(make_sandbox)
echo "# doublon" > "$D/docs/adr/ADR-0001-autre-sujet.md"
run_guard "$D"
assert_exit "doublon_numero" 1 "$LAST_EXIT"
assert_contains "doublon_msg" "$LAST_OUTPUT" "plusieurs fichiers"
rm -rf "$D"

# 3. Numéro référencé en prose, sans fichier ni registre
D=$(make_sandbox)
echo "Voir ADR-0042 pour le détail." > "$D/docs/reports/rapport.md"
run_guard "$D"
assert_exit "reference_sans_fichier" 1 "$LAST_EXIT"
assert_contains "reference_sans_fichier_msg" "$LAST_OUTPUT" "ADR-0042"
rm -rf "$D"

# 4. Le même numéro, déclaré au registre
D=$(make_sandbox)
echo "Voir ADR-0042 pour le détail." > "$D/docs/reports/rapport.md"
printf '<!-- adr-registry:begin -->\n```\nADR-0042  reserve  sujet\n```\n<!-- adr-registry:end -->\n' \
    > "$D/docs/adr/RESERVATIONS.md"
run_guard "$D"
assert_exit "reference_declaree" 0 "$LAST_EXIT"
rm -rf "$D"

# 5. Réservation obsolète : le fichier existe, l'entrée traîne
D=$(make_sandbox)
printf '<!-- adr-registry:begin -->\n```\nADR-0001  reserve  deja ecrit\n```\n<!-- adr-registry:end -->\n' \
    > "$D/docs/adr/RESERVATIONS.md"
run_guard "$D"
assert_exit "reservation_obsolete" 1 "$LAST_EXIT"
assert_contains "reservation_obsolete_msg" "$LAST_OUTPUT" "obsolète"
rm -rf "$D"

# 6. RÉGRESSION — la prose du registre ne réserve rien
#    ADR-0042 n'est cité qu'en dehors des marqueurs : il doit rester non déclaré.
D=$(make_sandbox)
echo "Voir ADR-0042 pour le détail." > "$D/docs/reports/rapport.md"
printf 'Ce numero est cite en provenance : ADR-0042.\n<!-- adr-registry:begin -->\n```\n```\n<!-- adr-registry:end -->\n' \
    > "$D/docs/adr/RESERVATIONS.md"
run_guard "$D"
assert_exit "prose_ne_reserve_rien" 1 "$LAST_EXIT"
assert_contains "prose_ne_reserve_rien_msg" "$LAST_OUTPUT" "ADR-0042"
rm -rf "$D"

# 7. Les fixtures de test emploient des numéros fictifs, et sont exclues
D=$(make_sandbox)
echo "network_allowed: true  # ADR-9998" > "$D/scripts/tests/fixture.sh"
run_guard "$D"
assert_exit "fixtures_exclues" 0 "$LAST_EXIT"
rm -rf "$D"

echo ""
echo "Total: $PASS/$TOTAL passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
