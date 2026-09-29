#!/usr/bin/env bash
# Contrôle PostToolUse rapide après Write/Edit : syntaxe du seul fichier touché.
#
# Jamais de suite de tests ici : elles appartiennent au skill /qualify-lot.
# Chaque contrôle est borné à quelques secondes. Sortie 2 = problème à
# corriger, renvoyé à Claude sur stderr ; sortie 0 = rien à signaler.
# Les messages ne citent que le fichier et l'outil, jamais son contenu brut
# au-delà des lignes d'erreur de l'outil de syntaxe.
set -uo pipefail

input="$(cat)"
f="$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' <<<"$input" 2>/dev/null)"
cwd="$(jq -r '.cwd // empty' <<<"$input" 2>/dev/null)"
[ -n "$f" ] || exit 0
[ "${f#/}" = "$f" ] && f="${cwd:-$PWD}/$f"
[ -f "$f" ] || exit 0

problems=""
add() { problems="${problems}${1}"$'\n'; }

dir="$(dirname "$f")"
if git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    top="$(git -C "$dir" rev-parse --show-toplevel)"
    rel="${f#"$top"/}"
    ws="$(git -C "$top" diff --check -- "$rel" 2>&1 | head -5)"
    [ -z "$ws" ] || add "git diff --check : ${ws}"
fi

case "$f" in
    *.py)
        out="$(timeout 10 python3 -m py_compile "$f" 2>&1)" || add "py_compile : ${out}"
        if command -v ruff >/dev/null 2>&1; then
            out="$(timeout 10 ruff check --quiet --select E9,F63,F7,F82 "$f" 2>&1)" || add "ruff (erreurs fatales) : ${out}"
        fi ;;
    *.sh)
        out="$(bash -n "$f" 2>&1)" || add "bash -n : ${out}" ;;
    *.json)
        out="$(timeout 10 python3 -m json.tool "$f" 2>&1 >/dev/null)" || add "JSON invalide : ${out}" ;;
    *.yml|*.yaml)
        out="$(timeout 10 python3 -c 'import sys,yaml; list(yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")))' "$f" 2>&1)" \
            || { case "$out" in *"No module named 'yaml'"*) ;; *) add "YAML invalide : ${out}" ;; esac; } ;;
esac

# Chemin absolu machine-local AJOUTÉ dans un fichier versionnable (AGENTS.md) ;
# les lignes préexistantes ne sont pas imputées à la modification courante.
abs_re='/home/[a-z][a-z0-9_-]*/|/Users/[A-Za-z]'
if [ -n "${top:-}" ] && ! git -C "$top" check-ignore -q -- "$rel" 2>/dev/null; then
    if git -C "$top" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
        added="$(git -C "$top" diff -U0 -- "$rel" 2>/dev/null | grep -E '^\+[^+]' || true)"
    else
        added="$(cat -- "$f")"
    fi
    if grep -qE "$abs_re" <<<"$added"; then
        add "chemin absolu machine-local ajouté : dériver la racine de l'emplacement du fichier"
    fi
fi

if [ -n "$problems" ]; then
    printf 'Contrôle rapide en échec pour %s :\n%s' "$f" "$problems" | head -30 >&2
    exit 2
fi
exit 0
