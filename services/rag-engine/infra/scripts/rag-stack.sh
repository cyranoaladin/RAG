#!/usr/bin/env bash
# Enveloppe `docker compose` pour la pile rag-engine — rend la base atteinte
# visible AVANT d'agir.
#
# ─── LE PROBLÈME QU'IL RÉSOUT ──────────────────────────────────────────────
# Docker Compose préfixe chaque volume du nom du projet. Le même
# `docker-compose.v2.yml` produit donc `nexusrag_rag_pgvector_data` ou
# `infra_rag_pgvector_data` selon le nom de projet effectif — et **rien** dans
# la sortie de `docker compose up` ne dit lequel. Un `-p` en ligne de commande
# l'emporte silencieusement sur `COMPOSE_PROJECT_NAME` de `.env`.
#
# Le 27 août 2026, une soirée entière de remédiation de schéma a porté sur la
# base vestige au lieu de la base canonique, sans qu'aucun signal ne l'indique
# (ADR-0051).
#
# Ce script : résout le projet effectif, affiche le volume réellement visé et
# son contenu, et refuse tout projet divergent du projet canonique.
#
# ─── USAGE ─────────────────────────────────────────────────────────────────
#   ./scripts/rag-stack.sh up -d
#   ./scripts/rag-stack.sh ps
#   ./scripts/rag-stack.sh logs -f ingestor
#
# Tout argument est transmis tel quel à `docker compose`. La surcharge
# asynchrone héritée s'ajoute avec :
#   RAG_STACK_OVERLAYS=docker-compose.legacy-async.yml ./scripts/rag-stack.sh up -d
#
# Pour agir délibérément sur un autre projet (pile vestige, bac à sable) :
#   RAG_STACK_ALLOW_PROJECT=infra ./scripts/rag-stack.sh ps
# L'intention devient explicite et tracée dans la sortie.

set -euo pipefail

# Racines dérivées de l'emplacement du script : aucun chemin machine-local.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd -- "$script_dir/.." && pwd)"

canonical_project=nexusrag
environment_file="$infra_dir/.env"

if (( $# == 0 )); then
    printf 'usage: %s <commande docker compose> [args...]\n' "${0##*/}" >&2
    exit 2
fi

# ── Refuser un `-p` en ligne de commande ───────────────────────────────────
# C'est exactement le geste qui bascule de base sans le dire.
for argument in "$@"; do
    case "$argument" in
        -p|--project-name|-p=*|--project-name=*)
            printf '%s\n' \
                "REFUS: ne pas passer -p/--project-name a ce script." \
                "Le projet vient de COMPOSE_PROJECT_NAME dans infra/.env (ADR-0051)." \
                "Pour viser deliberement un autre projet :" \
                "  RAG_STACK_ALLOW_PROJECT=<nom> ${0##*/} $*" >&2
            exit 2
            ;;
    esac
done

# ── Résoudre le projet effectif, dans l'ordre de priorité de Compose ───────
project="${COMPOSE_PROJECT_NAME:-}"
if [[ -z "$project" && -f "$environment_file" ]]; then
    project="$(
        sed -n 's/^[[:space:]]*COMPOSE_PROJECT_NAME=\(.*\)$/\1/p' \
            "$environment_file" | tail -n1
    )"
fi
if [[ -z "$project" ]]; then
    printf '%s\n' \
        "REFUS: COMPOSE_PROJECT_NAME introuvable." \
        "Attendu dans l'environnement ou dans infra/.env." \
        "Sans lui, Compose deduit le projet du nom du repertoire : la base" \
        "atteinte devient imprevisible (ADR-0051)." >&2
    exit 2
fi

allowed_project="${RAG_STACK_ALLOW_PROJECT:-$canonical_project}"
if [[ "$project" != "$allowed_project" ]]; then
    printf '%s\n' \
        "REFUS: projet '$project' != projet canonique '$canonical_project'." \
        "Volume vise : ${project}_rag_pgvector_data" \
        "Canonique   : ${canonical_project}_rag_pgvector_data" \
        "Si c'est deliberé : RAG_STACK_ALLOW_PROJECT=$project ${0##*/} $*" >&2
    exit 2
fi

# ── Composer la ligne de commande ──────────────────────────────────────────
compose_arguments=(--project-directory "$infra_dir" -f "$infra_dir/docker-compose.v2.yml")
overlay_names="${RAG_STACK_OVERLAYS:-}"
if [[ -n "$overlay_names" ]]; then
    while IFS= read -r overlay_name; do
        [[ -n "$overlay_name" ]] || continue
        if [[ ! -f "$infra_dir/$overlay_name" ]]; then
            printf 'REFUS: surcharge introuvable: %s\n' "$overlay_name" >&2
            exit 2
        fi
        compose_arguments+=(-f "$infra_dir/$overlay_name")
    done < <(tr ',: ' '\n' <<<"$overlay_names")
fi

# ── Annoncer la cible réelle avant d'agir ──────────────────────────────────
volume="${project}_rag_pgvector_data"
printf '── pile rag-engine ───────────────────────────────────────────\n'
printf '   projet          : %s%s\n' "$project" \
    "$( [[ "$project" == "$canonical_project" ]] && echo ' (canonique)' || echo ' (NON CANONIQUE)' )"
printf '   volume pgvector : %s\n' "$volume"

if docker volume inspect "$volume" >/dev/null 2>&1; then
    container="$(
        docker ps --filter "label=com.docker.compose.project=$project" \
                  --filter "label=com.docker.compose.service=pgvector" \
                  --format '{{.Names}}' | head -n1
    )"
    if [[ -n "$container" ]]; then
        # Lecture seule, tolérante : une base non démarrée ne doit pas empêcher
        # un `down` ou un `logs`.
        summary="$(
            docker exec "$container" psql -U "${PGVECTOR_USER:-raguser}" \
                -d "${PGVECTOR_DB:-ragdb}" -X -At -c \
                "SELECT count(*)||' chunks, '||count(DISTINCT collection)||' collections'
                 FROM rag_chunks;" 2>/dev/null || true
        )"
        [[ -n "$summary" ]] && printf '   contenu         : %s\n' "$summary"
    fi
else
    printf '   contenu         : volume absent (sera cree)\n'
fi
printf '──────────────────────────────────────────────────────────────\n'

exec docker compose "${compose_arguments[@]}" "$@"
