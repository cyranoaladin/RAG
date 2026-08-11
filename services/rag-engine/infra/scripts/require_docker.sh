#!/usr/bin/env bash
# Préflight Docker fail-closed pour les suites de gouvernance PostgreSQL.
#
# **Le défaut fermé ici.** ``requires_docker`` est un ``skipif`` : sans
# Docker, les suites de gouvernance étaient toutes sautées et pytest
# sortait 0. Le check requis « governance postgres » pouvait donc devenir
# vert en n'ayant rien prouvé — exactement le « vert non démontré » que la
# règle « Qualité des métriques » d'AGENTS.md proscrit.
#
# Ce script est la première des deux barrières. Il est partagé par la
# cible Make et par le job GitHub Actions, pour que le message de refus
# soit le même des deux côtés : une divergence de formulation entre CI et
# poste local rendrait le diagnostic plus difficile au pire moment.
#
# La seconde barrière vit dans ``tests/integration/_pg_authority.py``
# (NEXUS_REQUIRE_DOCKER) : elle couvre le cas où pytest serait invoqué
# directement, sans passer par ce script.
set -euo pipefail

fail() {
  echo "GOVERNANCE_DOCKER_PREFLIGHT_FAILED: $1" >&2
  echo "  Les suites de gouvernance PostgreSQL exigent un Docker réel." >&2
  echo "  Elles ne sont jamais sautées silencieusement : un check vert" >&2
  echo "  sans conteneur ne prouverait aucun invariant." >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "la commande 'docker' est introuvable dans le PATH"

if ! docker info >/dev/null 2>&1; then
  fail "le daemon Docker est injoignable ('docker info' a échoué)"
fi

echo "GOVERNANCE_DOCKER_PREFLIGHT=OK"
