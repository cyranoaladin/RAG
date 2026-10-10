# Lot #293 — harnais HTTP du BFF pour le successeur public

Actualisation UTC : 2026-10-10. Base relue avant intégration :
`origin/main=18af99119269a20a6651ca784d8f7022219c0cc8` après #323,
arbre `4188b6ccdac11aa8604c3325481b72ba7c9afe97`. La branche #293 a
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
autorisation enseignant n'est déduite d'un scope étudiant. Sur un scope
`roles: [student]`, le harnais ne tente jamais de signer `teacher` : il teste
le 403 hors collection avec la session `student` et inscrit
`teacher_e2e_verified=false`, `teacher_status=null` et
`NOT_RUN_SCOPE_ROLE_NOT_ISSUED`. Son `verification_status` est alors
`STUDENT_ONLY_VERIFIED`, la sortie `BFF_E2E_PASS=false` et
`STUDENT_PUBLIC_BFF_E2E_PASS=true` en mode public. Le statut global `VERIFIED`
et `BFF_E2E_PASS=true` exigent aussi le parcours positif `teacher`, exécuté
seulement si ce rôle figure explicitement dans le scope final émis. Le mode
historique `internal`, même si son refus étudiant est vérifié, porte
`INTERNAL_STUDENT_REFUSAL_VERIFIED` et ne peut pas satisfaire ce statut global.

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

Le contrôle de release examine maintenant **tous les placements de tous les
subjects du manifest lié au registre**, même si le BFF ne retourne qu'un
passage d'une collection. Il exige `placement_status=active`,
`review_status=reviewed` et `currentness` dans l'enum canonique
`{current, official_snapshot}` ; en mode étudiant public, il exige également
`visibility=public` sur chaque placement. Ces champs restent associés au
placement lu afin qu'une réponse ne puisse pas effacer une révocation, une
revue pendante ou une obsolescence. `citation.rights` doit correspondre à un
droit présent dans `evidence_subject.rights` du scope V3 signé, limité aux
valeurs autorisées en contexte public par `nexus_contracts.document` :
`officiel_public` et `public_allowed`. Une chaîne non vide comme `unknown`
ne suffit plus. Le contrôle ne change ni le rôle étudiant, ni la visibilité
des placements, ni la politique de droits du runtime.

## Dépendances de câblage encore ouvertes

- Le paquet préparatoire recalculé depuis ce `main` est
  `student-public-successor-20261010-fcc84331e7700042` (11 collections,
  253 dérivés, 377 placements, 3 975 chunks **projetés**). Son manifeste
  `b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78`
  reste `candidate/NOT_PROMOTABLE/PRE_REVIEW`; ses scopes sont `NOT_ISSUED`.
  Ces valeurs ne sont pas codées en dur dans le harnais et ne prouvent aucune
  donnée servie sur staging.
  Le manifest intégré par #323 a été relu dans ce checkout : son digest est
  bien `b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78`,
  son état demeure `candidate/NOT_PROMOTABLE/PRE_REVIEW` et il interdit
  l'activation production. Cette lecture est locale, pas un E2E.
- #294 est une proposition d'autorité, non l'émission des onze scopes V3.
  Elle borne `target_policy.roles` à `student`. Le harnais ne revendique donc
  aucune preuve positive `teacher` pour cette proposition. La preuve
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
- Aucun agrégateur de readiness du `main` courant, ni le vérificateur externe
  préparatoire de #319, ne consomme encore le type
  `NEXUS-FINAL-STAGING-BFF-E2E-V1`. L'ancien contrôleur Cockpit lit une autre
  preuve historique. Avant de déclarer le produit global prêt, l'agrégateur
  final devra exiger `teacher_e2e_verified=true` si son contrat requiert le
  parcours enseignant ; `STUDENT_ONLY_VERIFIED` ne ferme pas ce gate.

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
`python -m pytest -q scripts/tests/test_staging_bff_e2e.py` : 40 tests verts,
dont les sabotages RED→GREEN d'un second placement révoqué, en revue pendante,
obsolète ou interne, d'un placement révoqué dans une autre collection du
manifest, de citations aux droits `unknown`, `usage_interne` ou publics
hors du scope signé, et de scopes étudiant contenant des droits non publics.
Le parcours `student` seul et le parcours `teacher`
explicitement autorisé restent couverts ;
`ruff check` des deux fichiers Python : vert ; `git diff --check` : vert.
Après intégration de #323 : 40 tests du harnais verts et 61 tests ciblés
supplémentaires verts sur le transfert public, l'inventaire et les contrats
de droits, citations et scopes V3. Ces suites ont tourné dans le venv propre
du worktree, avec `nexus-contracts` installé en éditable depuis ce **même**
worktree ; aucune dépendance éditable d'un autre checkout n'a été utilisée.
