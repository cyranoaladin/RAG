# LOT38 — Transition de gouvernance du pilote

## Erratum LOT41T — 2026-08-02

Cet erratum prime sur les déclarations historiques concernées ci-dessous sans
modifier les résultats ni les SHA alors observés. Les tests LOT38 validaient la
structure et la cohérence interne de revendications locales ; ils ne prouvaient
ni une autorité GitHub authentifiée, ni la liaison du contenu du package à son
scope autorisé, ni des attestations `quality → gate → review` indépendantes.
Ces artefacts ne peuvent donc ouvrir aucune transition et LOT41T les traite
désormais explicitement en échec fermé.

## Verdict

**LOT38_LOCAL_CI_GREEN_AWAITING_REVIEWS_AND_CHECKS**

**GO_LIVE: NO_GO**

Ce verdict porte uniquement sur la politique de validation dormante. La CI
locale canonique est verte et sa synthèse est versionnée. Les revues finales,
la PR et ses checks GitHub n'ont pas encore été exécutés ou observés sur la
tête documentaire finale.

## Périmètre

LOT38 versionne le scope `libre_terminale_maths_nsi_real_v1`, la politique
`libre_terminale_validation_policy_v1`, leurs validateurs fail-closed, les
tests de réfutation, un audit déterministe sans effet de bord et
[l'ADR-0021](../adr/ADR-0021-politique-validation-pilote-dormante.md).
Le SHA-256 brut de cet ADR est
`b344d906be0c633372fb434677524aa3372f33044876b535a4aa1ef406bd5b69`.

Le lot reste strictement dormant : aucun document réel n'est lu, aucune
connexion DB, bucket ou réseau n'est ouverte, aucun appel OpenRouter n'est
émis, aucune migration ou route runtime n'est ajoutée et aucun verrou global
n'est activé. `packages/contracts`, les endpoints cockpit/rag-engine et Compose
restent hors périmètre.

## Audit du stash

Le stash immuable `906558ab06c384dd3b5ed0ed5387646a06585427` a été audité
sans application et sans suppression. LOT38 en retient seulement l'intention
d'un garde réfutable et fail-closed ; il n'en reprend pas le diff global.

Sont explicitement exclus :

- les activations de `ui_runtime_allowed` et `real_documents_allowed` ;
- la migration `002_fail_closed.sql` ;
- les modifications de retrieval, de review et de Compose ;
- la suppression de `tests/golden_queries/.gitkeep` ;
- le rattrapage général des `except Exception` ;
- le plan de reprise multi-lots devenu obsolète.

Le stash demeure un artefact local non livré et ne constitue pas une source de
vérité.

## Scope canonique

Le fichier
[`pilot_validation_scope.yml`](../../services/rag-pedago/configs/pilot_validation_scope.yml)
a pour SHA-256 brut
`b55ef1383fceabbbe0bf30c47a45a1fce607697f56bac340162156fabcf0fe26`.
Il impose exactement l'identité suivante : tenant `libre_terminale`, niveau
`terminale`, voie `generale`, statut `specialite`, audience `libre`, candidats
`cned_libre`, `individuel` ou `libre`, année scolaire `2026-2027` et état
`eligible_for_promotion`, jamais `active`.

| Matière | Collection unique | Taxonomie | SHA-256 brut |
|---|---|---|---|
| Mathématiques | `rag_nexus_maths_terminale_gen_specialite` | `services/rag-pedago/taxonomy/maths/terminale_gen_specialite.yml` | `4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6` |
| NSI | `rag_nexus_nsi_terminale_specialite` | `services/rag-pedago/taxonomy/nsi/terminale.yml` | `b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f` |

Le scope contient exactement 39 notions :

- Mathématiques (13) : `suites_limites`, `continuite`,
  `derivation_convexite`, `logarithme`, `primitives_integration`,
  `equations_differentielles`, `combinatoire`, `geometrie_espace`,
  `produit_scalaire_espace`, `succession_epreuves`,
  `variables_aleatoires_esperance`, `loi_grands_nombres`, `python` ;
- NSI (26) : `listes`, `piles`, `files`, `arbres`, `graphes`,
  `dictionnaires`, `recursivite`, `diviser_pour_regner`,
  `programmation_dynamique`, `parcours_graphes`, `recherche`, `tri`,
  `modele_relationnel`, `sql`, `contraintes`, `jointures`, `processus`,
  `protocoles`, `reseaux`, `routage`, `securisation`, `poo`,
  `tests_mise_au_point`, `gestion_modules`, `paradigme_fonctionnel`,
  `calculabilite_decidabilite`.

Toute différence de chemin, digest, collection, notion ou identité est un refus
et exige un nouveau scope adressé par contenu.

## Politique dormante

Le fichier
[`pilot_validation_policy.yml`](../../services/rag-pedago/configs/pilot_validation_policy.yml)
a pour SHA-256 brut
`bb548458ec83cacc2abe0c55104ade4bb44cb06828000bf50b9c97d8f3412bad`.
Son état est `eligible_for_promotion`, jamais `active`, et sa frontière
d'activation est LOT41A.

Les quatre capacités de validation sont exactement à `false` :
`validation_real_documents_allowed`, `validation_pipeline_allowed`,
`validation_answer_generation_allowed` et `validation_openrouter_allowed`.
Les quatre verrous publics sont également exactement à `false` :
`real_documents_allowed`, `ui_runtime_allowed`,
`answer_generation_allowed` et `curated_ingestion_allowed`.

`nexus-validation-1` n'est à ce stade qu'une intention d'isolation configurée,
non une isolation prouvée. LOT38 ne fournit aucun exécuteur. LOT41 doit
raccorder `rag-engine` au scope par contrat/API ou artefact signé, sans import
ni lecture directe du code `rag-pedago`. LOT41A doit fournir l'autorisation
humaine GitHub indépendante liée au payload et au head approuvé. LOT42 doit
prouver ce raccordement et la chaîne `quality → gate → review` avant toute
publication.

## Tests de réfutation

Une exécution ciblée observée sur la tête
`d70857a68ee279c15545742b591ac585f5d5fb93` sous Python 3.11.14 a terminé avec
`353 passed`. Elle couvre les modules LOT38 du scope, de la politique, de
l'autorisation, du CLI et du garde de sécurité Make. Elle réfute notamment les
digests ou taxonomies divergents, les notions/collections/identités hors scope,
les capacités partielles, les autorisations absentes, périmées ou
auto-déclarées, les preuves GitHub incohérentes, les droits/PII/rollback
incomplets, les packages sans `quality → gate → review`, les YAML ambigus, trop
grands ou trop profonds et les effets de bord du CLI.

La commande `make PY=python3 pilot-validation-policy-audit`, observée dans le
même environnement, a rendu `DORMANT` et `GO_LIVE: NO_GO` avec un code de sortie
nul.

Une première CI complète, antérieure au correctif `971daba`, a révélé que cette
nouvelle cible Make n'était pas classée. Le test correctif a d'abord reproduit
le refus, puis la cible a été classée une seule fois sous `SAFE_DIAGNOSTIC` ;
les 31 tests du garde Make et ses audits réels sont ensuite devenus verts. Le
journal de cette exécution antérieure n'est pas réutilisé comme preuve.

Une CI verte sur `971daba` a été invalidée après que la revue finale a reproduit
deux défauts fail-closed : des clés YAML contradictoires pouvaient ouvrir une
autorisation et une entrée très profonde levait `RecursionError`. Dix-sept
tests RED ont couvert toutes les frontières YAML ; un parseur partagé refuse
désormais les doublons, les documents supérieurs à 1 MiB et les profondeurs de
64 niveaux ou plus. Cette exécution antérieure n'est plus une preuve de la tête
de code courante.

Une CI verte sur `3ff775e` a ensuite été invalidée par la troisième revue du
diff complet : des types Python hors annotation levaient encore
`AttributeError` pour le scope ou les politiques. Bien que ce finding P2 ne
puisse pas ouvrir d'accès et qu'aucun consommateur runtime n'existe dans LOT38,
il a été corrigé afin de ne laisser aucune dette connue dans le garde. Douze
tests RED couvrent `None`, chaîne, entier et objet sur les trois paramètres ;
ils retournent désormais un refus structuré. Cette CI n'est pas non plus une
preuve de la tête courante.

La CI locale canonique probante a été réexécutée sous Python 3.11.14 et Node
22.22.0 sur le SHA source exact
`d70857a68ee279c15545742b591ac585f5d5fb93`. Son dernier bloc racine contient
exactement 13 lignes `PASS`, aucune ligne `FAIL` et
`Total: 13 passed, 0 failed`. Le journal brut reste hors Git ; son SHA-256 est
`521a67d58b02176fcf99bb0b4125a5bda1eb147af094708c0ef7715fbcd281a4`.

## Matrice de preuve

| critère | responsable | commande/procédure | environnement | artefact | digest | verdict |
|---|---|---|---|---|---|---|
| Suite ciblée LOT38 | auteur technique LOT38 | `PYTHONPATH=. .venv/bin/python -m pytest -q tests/unit/test_pilot_validation_scope.py tests/unit/test_pilot_validation_policy.py tests/unit/test_pilot_validation_authorization.py tests/unit/test_pilot_validation_policy_audit.py tests/unit/test_make_target_safety_audit.py` | worktree LOT38, Python 3.11.14 verrouillé | tête Git testée | `d70857a68ee279c15545742b591ac585f5d5fb93` | PASS (`353 passed`) |
| Audit dormant déterministe | auteur technique LOT38 | `make pilot-validation-policy-audit` depuis `services/rag-pedago` | même tête et Python 3.11.14 | politique canonique | `bb548458ec83cacc2abe0c55104ade4bb44cb06828000bf50b9c97d8f3412bad` | PASS (`DORMANT`, `GO_LIVE: NO_GO`) |
| Adressage du scope | auteur technique LOT38 | `sha256sum` du scope et des deux taxonomies | worktree LOT38 | scope ; taxonomie Mathématiques ; taxonomie NSI | `b55ef1383fceabbbe0bf30c47a45a1fce607697f56bac340162156fabcf0fe26` ; `4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6` ; `b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f` | PASS |
| Garde canonique des verrous | auteur technique LOT38 | `bash scripts/check-governance-locks.sh` et diff exact des trois fichiers protégés contre `origin/main` | tête `d70857a68ee279c15545742b591ac585f5d5fb93` | baseline ; script de garde ; contrat public | `91ee6d451ce8893a51849b702f3cb3d2889c71dd5f74221f0ea64633cc701572` ; `ce7ea4d1651c07c9cd02c3bf4e2644cf2837e50dc1fd47fa5401535359ae79a5` ; `60dcee3598f0f2cc1524ecdda6b58642ffc9f84ad88f5b5d48989913de9dfb11` | PASS (`18/18`, diff protégé vide) |
| CI locale canonique | auteur technique LOT38 | exécution unique post-correctif de `bash scripts/ci-local.sh` sur `ciSourceSha` | Python 3.11.14, Node 22.22.0 | journal brut hors Git | `521a67d58b02176fcf99bb0b4125a5bda1eb147af094708c0ef7715fbcd281a4` | PASS (`13 passed, 0 failed`) |
| Synthèse de CI | auteur technique LOT38 | comparaison exhaustive du dernier bloc racine, de ses 13 lignes PASS, de l'absence de FAIL et du total au journal brut | même exécution canonique | `docs/reports/evidence/lot_38/ci-local-summary.txt` | `179b999d22dbed280696573203dcf4a94ab5629747b8738d48c77e0e6b1bc32a` | PASS |
| Revues finales | reviewers indépendants | conformité design, qualité code/tests, puis diff complet `origin/main...HEAD` | tête finale exacte | verdicts de revue | `PENDING` | PENDING |
| Checks PR GitHub | GitHub Actions | six checks stricts sur le head exact de la PR | GitHub, événement `pull_request` | run immuable et readback | `PENDING` | PENDING |

## Dettes et frontières

- Le lanceur Python 3.11 initial de l'hôte était défaillant. Les preuves
  finales utilisent un lanceur Python 3.11.14 hors dépôt et l'environnement
  verrouillé du service ; les 353 tests ciblés, le typecheck et la CI canonique
  sont verts sans modification opportuniste des dépendances ou du code hors
  LOT38.
- L'isolation de `nexus-validation-1`, ses credentials, son DSN, son bucket et
  son réseau restent à démontrer ; la configuration ne contient que les noms
  de références d'environnement.
- Le raccordement runtime appartient à LOT41, l'autorisation humaine GitHub à
  LOT41A et la qualification/publication avec `quality → gate → review` à
  LOT42.
- LOT38 ne résout aucune dette globale de corpus, retrieval, sécurité,
  performance, déploiement, rollback de production ou activation publique.
  Elles restent bloquantes jusqu'aux lots prévus par la conception du pilote.

## Décision de livraison

LOT38 dispose d'une CI locale canonique et d'une synthèse vertes, mais n'est pas
prêt à être fusionné tant que les revues indépendantes et les six checks GitHub
de la tête finale ne sont pas verts. Le lot ne peut être publié que par sa
branche, sa PR et un squash conforme à la protection de `main`.

Même après fusion, LOT38 autorisera seulement la poursuite de la séquence vers
LOT39bis. Il n'autorise ni document réel, ni promotion de gouvernance, ni
activation publique : le verdict global demeure `GO_LIVE: NO_GO`.
