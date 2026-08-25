# Lot 2 — convergence sûre des moteurs A et B

## Verdict

`NO_GO`

Le Lot 2 rend la convergence exécutable et fail-closed sans migrer ni modifier
la production. Le moteur B est la seule architecture canonique. Le moteur A
reste intact, limité à la compatibilité et au rollback. Les fixtures locales
sont synthétiques ; aucune parité réelle A/B, restauration, bascule de trafic
ou autorisation de cutover n'est déclarée.

## Identité du lot

| Élément | Valeur |
| --- | --- |
| Date | 2026-08-25 |
| Baseline `origin/main` | `ca0a21f59bd25c7e472cf2d6accc5b8e79ed74bd` |
| Branche | `rag-engine/motor-convergence-20260825` |
| Head implémentation avant rapport | `091b29c19e429c793456e2653c78a7c8c7812a41` |
| Head code après corrections de revue | `910071b587f8b3c2dfc33cfcca033ba096f94604` |
| Contrat canonique | `packages/contracts`, `nexus-contracts` 0.14.0 |
| Moteur canonique | B — `rag-pedago` + `rag-engine` + pgvector + e5-large 1024D |
| Moteur de continuité | A — Streamlit/FastAPI legacy + ChromaDB + Ollama + SQLite |
| Mutation production | aucune |
| Verrou de gouvernance levé | aucun |

## Matrice de convergence

Les statuts mesurent uniquement ce qui est démontré dans le périmètre du lot.
`VERIFIED_LOCAL` ne vaut ni staging ni production.

| Capacité | Moteur A observé | Moteur B canonique | Preuve du Lot 2 | Écart réel restant | Lot propriétaire | Statut |
| --- | --- | --- | --- | --- | --- | --- |
| Réingestion gouvernée | écriture directe Chroma incompatible | pipeline `quality → gate → review` obligatoire | migrateur direct tombstoné ; préparation exhaustive sans autorité | exécuter sur capture réelle puis publier avec autorités | 2 puis 7/8 | `VERIFIED_LOCAL` |
| Ingestion fichier | présente dans le legacy | propriétaire B, surface production fermée | politique seulement | parcours canonique réel et E2E | 3 | `PARTIAL` |
| Ingestion URL | présente dans le legacy | writer réseau absent du runtime de lecture | politique seulement | chaîne Web gouvernée, retries, snapshots, DLQ | 4 | `PARTIAL` |
| Google Drive | connecteur et état SQLite legacy | propriétaire B | inventaire requis dans la capture | auth, inventaire 100 %, sync réelle et idempotence | 5 | `PARTIAL` |
| Retrieval | Chroma 768D en compatibilité | `/search/v2`, pgvector 1024D | comparateur déterministe sur passages canoniques | captures A/B sur corpus réel et seuils approuvés | 7/8 | `IMPLEMENTED_UNVERIFIED` |
| Filtres et isolation | filtres legacy non autoritaires | scopes gouvernés attendus | fuites collection/niveau/scope à tolérance zéro dans le comparateur | black-box réel multi-tenant/collections | 3 et 7 | `VERIFIED_LOCAL` |
| Citations | comportement legacy à recapturer | citations obligatoires | liaison citation↔passage testée | preuve retrieval sur corpus réel | 3 et 7 | `VERIFIED_LOCAL` |
| Droits et review | non alignés sur la gouvernance canonique | enum partagée et statut review | droit inconnu/non revu refuse fail-closed | décisions réelles et autorités scellées | 7 | `VERIFIED_LOCAL` |
| Catalogue | `catalog.sqlite` | catalogue/collections B | snapshot SQLite distinct et dispositions exhaustives | réconciliation réelle A↔B | 5/7 | `VERIFIED_LOCAL` |
| API externe | API legacy | propriétaire B | A bloqué dans la politique | clés API, quotas et black-box externe | 3 | `PARTIAL` |
| UI/cockpit | UI legacy active | cockpit/backend canonique | A bloqué dans la politique | E2E déployé sur même contrat/corpus | 6 | `PARTIAL` |
| Backup/restauration | actifs A explicitement reconstructibles | backup pgvector lié à l'inventaire B | contrat de preuve et runbook | backup frais et restore rehearsal réel | 8 | `IMPLEMENTED_UNVERIFIED` |
| Canary/rollback | A conservé | B cible canary | topologie A→B, rollback A, smoke B imposés | exécution de trafic et observation | 8/9 | `IMPLEMENTED_UNVERIFIED` |

Les chaînes API externe, Web, Drive et UI sont volontairement reportées aux
lots propriétaires. Elles ne sont pas rendues vertes par ce lot de
convergence.

## Livrables

### Frontière de migration

- `migrate_chroma_to_pgvector.py` refuse toute invocation avant import d'une
  primitive réseau, DB ou Docker ;
- aucune copie de vecteur 768D vers 1024D ;
- aucune méthode `migrate`, `copy`, `transfer` ou `run` exploitable ; le seul
  `main` est le tombstone qui refuse avec le code `78`.

### Politique versionnée

- protocole `NEXUS-ENGINE-CONVERGENCE-V1` ;
- propriétaire canonique B pour huit capacités ;
- états A fermés `blocked`, `compatibility_only`, `rollback_only` ;
- neuf collections legacy rapprochées exactement de la découverte connue ;
- seules les deux cibles NSI fines sont allowlistées ;
- défaut `REVIEW_REQUIRED` ou `QUARANTINE`, jamais
  `REINGEST_GOVERNED` par simple nom de collection ;
- `cutover_status=NO_GO`.

### Capture et préparation legacy

Le protocole `NEXUS-LEGACY-CAPTURE-V1` exige producteur, commit, fenêtre de
validité, contexte de capture, Chroma, deux SQLite indépendants, pgvector,
uploads, configurations, images et modèles. La lecture est bornée et refuse
contenu, embeddings, ligne surdimensionnée, schéma ouvert, doublon de clé et
identifiant sensible.

Chaque objet ou collection vide a exactement une disposition. Les doublons
restent inventoriés. La sortie ne confère ni droits, ni statut reviewed, ni
retrievability, ni autorisation ; `migration_complete=false`.

### Parité A/B hors runtime

Le comparateur consomme trois fichiers locaux réguliers et bornés, marqués
exclusivement `SYNTHETIC_TEST_ONLY` et `NOT_REAL_PARITY_EVIDENCE`. Il lie les
captures au SHA-256 du témoin, ferme l'allowlist et compare les séquences par
unités `source_sha256 + canonical_span_id + content_hash`. Le contexte d'accès
`internal` est explicite et validé par le contrat partagé. Les invariants de
scope, citation, compatibilité des droits avec ce contexte, égalité des droits
A/B sur un même passage, review et témoin hors collection sont indépendants
des seuils de métriques. Un protocole opérateur distinct reste à construire
avant toute capture réelle.

Le CLI publie un rapport nouveau par lien atomique, ne remplace jamais une
cible, refuse les FIFOs et renvoie :

- `2` pour une entrée ou publication invalide ;
- `3` pour un rapport `FAIL_CLOSED` ;
- `0` uniquement pour `METRICS_ONLY_THRESHOLDS_UNAPPROVED`.

Le code `0` n'est donc pas un PASS de parité.

### Manifeste de cutover

Le protocole `NEXUS-ENGINE-CUTOVER-V1` :

- borne taille, profondeur et types JSON ;
- refuse symlinks, FIFOs et chaînes non UTF-8 ;
- lie comptes et digests stables aux inventaires Chroma/SQLite/uploads ;
- lie le backup B à l'identité de base, au head et au digest pgvector ;
- impose active A, canary B, rollback A et un smoke B borné ;
- interdit la substitution entre cinq types de preuve ;
- interdit toute preuve positive dans le Lot 2 ;
- n'accepte que `NO_GO`.

Il valide uniquement un manifeste de gates négatifs (`value=false`,
`evidence=null`). Un contrat futur distinct devra valider les évidences réelles
positives ; le validateur du Lot 2 ne peut pas servir à ce cutover.

## Digests locaux des artefacts synthétiques

| Artefact | SHA-256 |
| --- | --- |
| Politique de convergence | `63980d9cd9944feef0ca3a7d7b1cecdcc9bfbffe2a2467793e9a717693e2cef4` |
| Capture legacy synthétique | `12f0a1e07c35cf44018a6a0142ca31d61a392e7be9a1ea3b19b750a480b35e1a` |
| Témoin de parité synthétique | `23994eb04af4313dbc4a6a5448512860f82a2ce053525527177c1d90527707ba` |
| Capture A synthétique | `7c73bea64a2840797fbba61a062be354ce6533e8f2722a9871bb2b29f9c408fc` |
| Capture B synthétique | `c20409dc4193b8f880c7d7ddf04b24e712f05d9da2cf62c0fd96c1a4a1e46aa9` |
| Cutover `NO_GO` synthétique | `30fa420835cb56fc20cf4e1fe4d9cb8f113a508435970eff99c7e2580e960bfa` |

Ces digests authentifient seulement des fixtures de test versionnées. Ils ne
sont ni des digests de corpus réel ni des preuves de production.

## Commits d'implémentation

| Commit | Objet |
| --- | --- |
| `ae4c85ff642236523bef3a7169a2b0b7c9c51528` | conception approuvée |
| `c8c740704ab8c95fd6d562f9dbb3609b624dedaf` | plan d'implémentation |
| `eb31f7015a951fbb21f4f9b213a0ef7b23766791` | tombstone Chroma→pgvector |
| `4583af3b1f8f29115d7566c89064feb876219851` | politique de convergence |
| `fe7b76e21b01643efa771b98cf3eabbfc44d02ea` | préparation legacy gouvernée |
| `c2759a767efe3764215d11fbee45238e0a07634d` | parité sur passages scellés |
| `b24a163e4be8945e0c76f43efad036b6500a31c1` | manifeste de cutover fail-closed |
| `091b29c19e429c793456e2653c78a7c8c7812a41` | liaisons de preuves du cutover |
| `cafca11` | ADR, runbook et rapport de convergence |
| `7dd1ca7` | normalisation du fichier de test de politique |
| `7d23d22` | preuves locales du Lot 2 |
| `096f221` | invariants de droits et lectures locales bornées |
| `910071b` | entrées YAML récursives et droits globaux par passage |

## TDD et revues adversariales

Les cycles rouges ont notamment reproduit puis fermé :

- import/mutation possible depuis l'ancien migrateur ;
- politiques incomplètes ou collections découvertes omises ;
- capture contenant texte/embedding, preuve expirée, SQLite incohérent ou
  disposition non exhaustive ;
- allowlist non typée, ordre de résultats invisible, faux code de sortie zéro,
  identifiants sensibles et publication interrompue ;
- FIFO bloquante, fichiers non réguliers, JSON hostile, Unicode surrogate,
  preuves de quiescence étrangères aux inventaires, backup B non lié,
  topologie inversée et smoke sans canary.

Deux agents indépendants ont relu contradictoirement chaque frontière majeure.
La revue complète a détecté puis fait reproduire deux P1 initiaux : divergence
de droits A/B non refusée et lecteurs YAML/JSONL susceptibles de suivre un
symlink ou de bloquer sur une FIFO. Une seconde passe a détecté la comparaison
des droits limitée à chaque requête ainsi qu'une profondeur YAML susceptible
de produire une exception brute. Les cycles rouges correspondants sont fermés
par un contexte d'accès explicite, l'égalité globale des droits par identité de
passage même après déplacement inter-requêtes, le rejet des contradictions
intra-capture, une erreur YAML assainie et des ouvertures
`O_NONBLOCK`/`O_NOFOLLOW` suivies de `fstat`, contrôle de fichier régulier et
bornes de taille. Les deux agents contradictoires ont approuvé l'exact head
`910071b587f8b3c2dfc33cfcca033ba096f94604` sans P0/P1/P2. Ces revues restent
des contrôles de code ; elles ne sont pas une trusted-human-review GitHub et ne
fournissent aucune identité humaine.

## Vérifications

Les vérifications exhaustives suivantes ont été exécutées sur le head de code
`7dd1ca7293d4557506d366de1c41edd2eeb35e0d`, avant les corrections de revue :

- suite ciblée Lot 2 : `160 passed` ;
- frontières existantes de non-régression : `174 passed` ;
- Ruff sur tous les fichiers Python du lot : PASS ;
- mypy sur les quatre modules source : PASS ;
- gouvernance : `18/18` verrous conformes ;
- hygiène du dépôt et `git diff --check` : PASS ;
- gitleaks différentiel `origin/main..HEAD`, dix commits, redaction totale :
  aucune fuite ;
- CI locale exhaustive : `17 passed, 0 failed` ;
- `rag-pedago` dans cette CI : `2807 passed, 2 skipped` ;
- `rag-engine` : lint, mypy sur 125 fichiers, suite non-intégration et smoke
  Docker hybride réels : PASS ;
- `cockpit` : lint, `179 passed`, build Next.js et audit npm sans
  vulnérabilité : PASS ;
- contrats, topologie CI, trusted-human-review, taxonomie et contrôles de
  gouvernance : PASS.

La première création de venv par `scripts/ci-local.sh` a exposé un défaut
machine préexistant : le binaire utilisateur `python3.11` sélectionné est une
installation uv relocalisée dont la bibliothèque standard pointe vers
`/install`. Le script et les Makefiles sont identiques à `origin/main`. La CI
exhaustive ci-dessus a donc été relancée sans changement dépôt avec un shim
temporaire `python3.11` vers Python 3.12.3, version compatible avec la règle
Python 3.11+, puis le shim a été supprimé automatiquement.

Sur le head corrigé `910071b587f8b3c2dfc33cfcca033ba096f94604` :

- suite ciblée Lot 2 : `173 passed` ;
- frontières existantes de non-régression : `174 passed` ;
- suites politique et parité directement affectées : `44 passed` ;
- Ruff sur tous les fichiers Python du Lot 2 : PASS ;
- mypy ciblé sur les quatre modules, contrat partagé résolu via `MYPYPATH` :
  PASS ;
- gouvernance : `18/18` verrous conformes ;
- deux revues contradictoires exact-head : APPROVED, aucun P0/P1/P2.

Après le commit documentaire final, les garde-fous et la CI seront rejoués sur
le nouveau head ; leurs résultats ne sont pas pré-déclarés dans ce rapport.

## Preuves réelles absentes et gates

Les éléments suivants restent explicitement non satisfaits :

- capture read-only exhaustive du moteur A réel ;
- réingestion gouvernée des objets réels ;
- captures A/B et seuils de parité approuvés ;
- backup frais et restore rehearsal isolé ;
- canary et rollback de trafic réellement exécutés ;
- observation staging/production ;
- trusted-human-review GitHub liée au head de la future PR ;
- autorisation opérateur de mutation production.

En conséquence :

- `snapshot_restored_verified=false` ;
- `real_parity_executed=false` ;
- `restore_rehearsal_verified=false` ;
- `traffic_rollback_tested=false` ;
- `cutover_authorized=false` ;
- verdict global `NO_GO`.

## Suivi du lot

| Lot | Branche | PR | SHA | CI | Revue | Déployé | Preuve réelle | Rollback | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | `rag-engine/motor-convergence-20260825` | à ouvrir | code corrigé et approuvé `910071b587f8b3c2dfc33cfcca033ba096f94604` ; head documentaire à figer | ciblée `173/173` ; non-régression `174/174` ; exhaustive antérieure `17/17` | deux revues contradictoires exact-head approuvées ; trusted-human-review GitHub à obtenir | non | non | contrat local seulement | `NO_GO` |
