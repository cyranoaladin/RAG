# Lot go-live — réconciliation de l'attribution des releases scellées V2

## Défaillance observée

**LIVE — instantané du 2026-10-08 à 12:16:24 UTC, pas état durable.** Une
lecture directe de `nexus-staging-pgvector-1`, base dédiée
`ragdb_profile_gate_v4`, rôle `raguser`, dans une transaction `READ ONLY`,
donne 315 artefacts, tous avec `source_kind=sealed_release`, aucun avec
`source_kind=source_label`, et 315 dont `source_label` égale l'hôte de
`source_uri`. Les 315 portent aussi `rights=officiel_public` et
`official=true`. La même base a 11 collections et 479 placements. La
commande de lecture, sans valeur de secret, est :

```sh
ssh -o ProxyJump=none -o BatchMode=yes nexus-prod \
  'date -u +%Y-%m-%dT%H:%M:%SZ; docker exec -i nexus-staging-pgvector-1 sh -c '\''exec psql -X -v ON_ERROR_STOP=1 -At -F "|" -U "$POSTGRES_USER" -d ragdb_profile_gate_v4'\''' <<'SQL'
BEGIN READ ONLY;
SELECT current_database(), current_user, current_setting('transaction_read_only');
SELECT count(*) AS artifacts_total,
       count(*) FILTER (WHERE source_kind = 'sealed_release') AS sealed_release_kind,
       count(*) FILTER (WHERE source_kind = source_label) AS kind_equals_label,
       count(*) FILTER (WHERE source_label = substring(source_uri from '^https?://([^/:?#]+)')) AS label_equals_uri_host,
       count(*) FILTER (WHERE rights = 'officiel_public') AS public_official_rights,
       count(*) FILTER (WHERE official IS TRUE) AS official_true
FROM public.rag_artifacts;
SELECT count(DISTINCT collection) AS collections_total,
       count(*) AS placements_total
FROM public.rag_artifact_placements;
COMMIT;
SQL
```

Sortie expurgée :

```text
2026-10-08T12:16:24Z
BEGIN
ragdb_profile_gate_v4|raguser|on
315|315|0|315|315|315
11|479
COMMIT
```

Lors de la tentative de démarrage API précédente, le validateur avait
signalé `wrong_artifact_metadata` dans chacune des 11 collections, puis
`release database reconciliation unavailable`. Ce journal de tentative
est un **diagnostic daté**, pas un état de service courant. Le rapprochement
avec le code d'attribution ci-dessous explique le champ divergent ; ce lot
ne change aucun manifeste ni enregistrement produit.

## Cause et correction

`derive_sealed_release_artifact_attribution` établit explicitement
`source_kind=sealed_release` : la release est acquise par transfert scellé et
n'a pas d'URL canonique de découverte. Cette valeur fait partie de
l'attribution durable relue et attestée avant publication ; Worker B publie
cette attribution sans la recalculer. `source_url` reste une URL de provenance,
dont l'hôte donne `source_label`, pas le mode d'acquisition.

`evaluate_release_snapshot` attend désormais `sealed_release` **uniquement**
pour `MULTILEVEL_AGGREGATE_RELEASE_V2`. Le comportement Wave 0 et multilevel V1
reste identique. Les comparaisons exactes de `source_label` avec l'hôte du
manifeste, de `source_uri` avec son URL, du SHA-256 de contenu, du type de
document, des droits et du statut officiel demeurent obligatoires. Une
substitution de `source_kind` par le domaine, qui passait avant, est refusée.

Il s'agit d'une correction de parité entre l'attribution déjà gouvernée et
le lecteur de readiness, sans modification du contrat `nexus-contracts`, des
verrous de gouvernance, du schéma, des manifestes ou des données.

## Vérification locale

**SEALED — code testé :** commit
`c71bb4aafabd6432c7c383788cdd4a29ee129858`, tree
`2931cac8caf13e04b340b0a0aa7fc67076473505`, basé sur
`96f7506af14847c8084f07ed597995e029f5c63d`. La modification ultérieure
de ce rapport ne touche aucun fichier Python. Les commandes ont été lancées
depuis ce worktree, avec les sources de ses propres packages en tête de
`PYTHONPATH` :

```sh
cd services/rag-engine
PYTHONPATH=src:../../packages/contracts/src:../../packages/release-chain/src:../../packages/pdf-page-policy/src python3 -m pytest -q tests/test_release_readiness.py tests/test_h2f_artifact_attribution.py tests/test_sealed_release_attribution.py tests/test_publication_resume.py --tb=short
# Exit 0 : 247/247 cas collectés, 0 échec (192 readiness + 55 attribution/publication).

cd ../..
PYTHONPATH=packages/contracts/src:packages/release-chain/src:packages/pdf-page-policy/src python3 -m pytest -q packages/release-chain/tests --tb=short
# Exit 0 : 56 passed, 2 avertissements de dépréciation setuptools/pkg_resources.

python3 -m ruff check packages/release-chain/src/nexus_release_chain/release_readiness.py services/rag-engine/tests/test_release_readiness.py
# Exit 0 : All checks passed!
git diff --check origin/main...HEAD
# Exit 0 : aucune erreur.
```

Avant le correctif, sur la base `d9c05db7d19130ba96bc191b1e0ef8ae8b9d4279`
avec les deux tests nouveaux seuls dans le worktree, la commande
`PYTHONPATH=src /tmp/nexus-release-source-kind-venv-d9c05db7/bin/python -m pytest -q tests/test_release_readiness.py -k 'v2_sealed_release_attribution_is_required_for_readiness or v2_discovery_kind_cannot_substitute_reviewed_sealed_attribution'`
a produit **2 failed** : l'attribution scellée était refusée et le domaine
était accepté. Après correction, les deux tests et la fixture V2 de partage
d'artefact passent. La CI de la PR reste la validation intégrale au HEAD final.

## Limite opérationnelle

Cette correction ne vaut pas qualification staging : après fusion, rebâtir
l'image API depuis le nouveau `main`, relire le staging en préflight, puis
rejouer la réconciliation HTTP réelle des 11 collections. Le validateur doit
encore refuser toute divergence d'un autre champ gouverné.
