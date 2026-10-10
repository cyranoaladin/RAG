# Lot #293 — harnais HTTP du BFF pour le successeur public

Actualisation UTC : 2026-10-10. Base relue avant intégration :
`origin/main=744764c7dbc15143f88fd410d534d0a4c956e329`, arbre
`161eaf51bd54cc4fe4830c0d3715cb7f33162c82`. La branche #293 a
fusionné cette base sans réécrire son historique. Aucun staging ou production
n'a été modifié, et aucune réussite E2E live n'est revendiquée.

Le produit visé est la recherche étudiante des passages **textuels dérivés**,
avec citation complète. Les PDF originaux V4/V5 restent internes. Le harnais
`scripts/go_live/staging_bff_e2e.py` exige désormais un registre à onze
collections et à une seule release `student-public-successor-*`, en mode
`production`, `PROMOTABLE`, `PRODUCTION_ACTIVATION_ALLOWED` et `APPROVED`.
Il refuse donc les manifests V4/V5 `rehearsal` et les paquets successeurs
`candidate/NOT_PROMOTABLE/PRE_REVIEW`. L'index de scopes V3 est fourni
explicitement par `--scope-index`, doit être dans le checkout final, et doit
correspondre aux onze artefacts gouvernés de `packages/contracts`. Chaque
scope est public et lie `source_sha256` aux octets du subject final scellé.
Le rôle de test doit être autorisé dans `target_policy.roles` ; aucune
autorisation enseignant n'est déduite d'un scope étudiant.

Après ces préconditions, le harnais compare le SHA du build exposé par
`/api/health` au SHA exact du checkout propre et du `main` distant. Il signe
une session de test, vérifie le refus 401 sans session et le refus 403 hors
collection, puis exige des passages réels de la collection et des placements
scellés. En mode public étudiant, chaque passage doit être lié à un dérivé
`text/plain; charset=utf-8`, jamais à un PDF, et porter l'URI, le libellé,
la page, le concédant, `ETALAB-2.0`, la date et la notice de dérivation
exactement tels que scellés dans le registre d'artefacts. Le rapport privé
est écrit en mode `0600` et ne contient aucun jeton. Une invocation couvre
**une** collection ; la qualification complète exigera onze invocations et
l'acceptance directe API v2 distincte.

## Dépendances de câblage encore ouvertes

- Le paquet préparatoire recalculé depuis ce `main` est
  `student-public-successor-20261010-fcc84331e7700042` (11 collections,
  253 dérivés, 377 placements, 3 975 chunks **projetés**). Son manifeste
  `b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78`
  reste `candidate/NOT_PROMOTABLE/PRE_REVIEW`; ses scopes sont `NOT_ISSUED`.
  Ces valeurs ne sont pas codées en dur dans le harnais et ne prouvent aucune
  donnée servie sur staging.
- #294 est une proposition d'autorité, non l'émission des onze scopes V3.
  Elle borne `target_policy.roles` à `student`. Une recherche positive
  `teacher` sur le même scope serait donc refusée par le harnais. La preuve
  enseignant exige une autorité de scope distincte ou une politique finale
  explicitement approuvée couvrant ce rôle.
- Le Cockpit de `main` signe et valide encore le pilote
  `libre_terminale_maths_nsi_real_v1`. Le lot de câblage produit doit migrer
  `services/cockpit/src/server/pilot-scope.ts`,
  `services/cockpit/src/server/internal-token.ts`,
  `services/cockpit/src/app/api/search/route.ts` et
  `services/cockpit/scripts/mint-session-token.mjs` vers les scopes V3 émis,
  tout en conservant la sélection mono-matière de #318. Il faut également
  intégrer l'index final généré dans le build Cockpit et exposer son SHA exact
  dans `/api/health`. Aucun bypass `student → internal` n'est permis.
- Aucun BFF final ni release publique gouvernée n'est encore déployé sur une
  cible staging qualifiée. `BFF_E2E_LIVE_PASS=false`.

Après émission des scopes, approbation de la release et déploiement de la
cible finale, l'invocation doit fournir les chemins et empreintes **recalculés
depuis la release finale**, et non ceux du paquet préparatoire :

```bash
python3 scripts/go_live/staging_bff_e2e.py \
  --repository-root . \
  --cockpit-url http://127.0.0.1:18004 \
  --registry "$FINAL_REGISTRY_PATH" \
  --registry-sha256 "$FINAL_REGISTRY_SHA256" \
  --scope-index "$FINAL_SCOPE_INDEX_PATH" \
  --expected-sha "$(git rev-parse origin/main)" \
  --operator-id "$USER" \
  --collection rag_nexus_nsi_terminale_specialite \
  --student-mode public \
  --output "$NEXUS_QUALIFICATION_DIR/bff-e2e-nsi-public.json"
```

Six variables d'identité sont requises dans l'environnement opérateur, jamais
dans la ligne de commande. L'URL Cockpit est limitée à une origine loopback
sans identifiants ni redirection. Le mode public ne lève aucun verrou ; la
release, les droits, les scopes, le build et les résultats HTTP doivent tous
être vérifiés à la cible finale.

Vérification locale dans `/tmp/rag-pr293-main744-venv`, créé pour ce worktree :
`python -m pytest -q scripts/tests/test_staging_bff_e2e.py` : 25 tests verts ;
`ruff check` des deux fichiers Python : vert ; `git diff --check` : vert.
