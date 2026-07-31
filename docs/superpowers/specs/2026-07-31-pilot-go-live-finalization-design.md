# Finalisation go-live du pilote Nexus — conception validée

> Statut : validé par le commanditaire le 31 juillet 2026, puis renforcé après
> revue indépendante.
>
> Autorité reçue : préparer la transition et exécuter les lots de preuve du
> pilote. Cette autorité ne vaut ni promotion des verrous ni décision finale
> d'ouverture ; ces deux décisions humaines sont séparées en section 7.
>
> Périmètre de release : tenant `libre_terminale`, spécialités Mathématiques et
> NSI, année scolaire `2026-2027`.

## 1. Décision et définition de « 100 % »

La première release publique exploitable de Nexus porte sur le vertical pilote
`libre_terminale` Mathématiques + NSI. Elle doit être terminée, testée, déployée
et réversible sur ce périmètre avant toute extension.

Pour cette release, « 100 % » signifie que tous les critères de sortie du
pilote sont démontrés sur l'environnement cible, sans preuve uniquement locale,
exception cachée ou dette bloquante. Cela ne signifie pas que les 57 autres
collections ni les phases d'extension de la roadmap sont achevées.

La conception multi-matières du 29 juillet 2026 reste une cible d'architecture,
mais le présent document est l'unique norme de recette du pilote. Aucun critère
de ce pilote ne dépend implicitement d'un autre document de conception.

## 2. Alternatives examinées

### 2.1 Clôture `metadata-only`

Rejetée comme go-live produit : documents réels, UI runtime, génération sourcée
et ingestion curatée resteraient désactivés.

### 2.2 Pilote contrôlé Mathématiques + NSI

Option retenue. Elle permet un contrôle exhaustif de la substance, des droits,
du retrieval, des citations et de l'exploitation réelle.

### 2.3 Ouverture immédiate des 59 collections

Différée. Une taxonomie ou une référence générique ne prouve pas qu'une
collection possède des ressources qui enseignent réellement chaque notion.

## 3. Périmètre canonique

### 3.1 Identité et routage

Le pilote accepte uniquement les profils contractuels suivants :

| Dimension | Valeur autorisée |
| --- | --- |
| tenant | `libre_terminale` |
| niveau | `terminale` |
| voie | `generale` |
| statut d'enseignement | `specialite` |
| audience dérivée | `libre` |
| statut détaillé | `candidat_libre` |
| candidat | `individuel`, `libre` ou `cned_libre` |
| matière primaire | `maths` ou `nsi` |
| année scolaire | `2026-2027` |

L'identité autoritative provient de la session Nexus transformée en
`InternalIdentity`. Les champs envoyés par le navigateur ne peuvent jamais
élargir le tenant, le niveau, la voie, l'audience, le statut, le candidat ou les
matières. Toute divergence entre session, requête et collection retourne un
refus avant accès à PostgreSQL.

### 3.2 Collections et taxonomies

Les deux seules collections publiables sont :

| Collection | Taxonomie canonique | Programme |
| --- | --- | --- |
| `rag_nexus_maths_terminale_gen_specialite` | `services/rag-pedago/taxonomy/maths/terminale_gen_specialite.yml` | `BOEN_special_8_2019-07-25` |
| `rag_nexus_nsi_terminale_specialite` | `services/rag-pedago/taxonomy/nsi/terminale.yml` | `BOEN_special_8_2019-07-25` |

LOT38 crée le scope `libre_terminale_maths_nsi_real_v1`. Il ne réutilise pas
le scope historique `math_terminale_specialite_metadata_only_v1`, qui reste
metadata-only et AEFE. Le nouveau scope contient les SHA-256 exacts des deux
taxonomies et refuse leur remplacement silencieux.

Les 39 notions obligatoires sont :

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

Une modification de cette liste, du programme ou des identifiants de collection
constitue un changement de périmètre : nouveau SHA de scope, revue des goldens
et nouvelle décision de promotion.

## 4. Exigences d'architecture normatives

Le pilote conserve explicitement les exigences suivantes :

- domaine public : `https://nexusreussite.academy` ;
- cockpit Next.js avec BFF same-origin et session Nexus/Auth.js ;
- aucun appel navigateur direct à pgvector, aux documents bruts, à OpenRouter
  ou à une API munie d'un secret statique ;
- `packages/contracts` comme unique source des DTO Python et TypeScript générés ;
- `rag-engine` comme seul plan de données et seul publisher vers pgvector ;
- `rag-pedago` comme plan de contrôle sans écriture directe dans pgvector ;
- PostgreSQL/pgvector, Redis, cockpit et moteur dans le Compose de production
  durci, derrière Nginx/TLS ;
- embedding `intfloat/multilingual-e5-large`, dimension 1024, artifact local
  read-only et révision/digest obligatoires dans le manifeste de release ;
- reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`, révision/digest obligatoires ;
- RRF `alpha=0.7`, `k_rrf=60`, seuil de rerank `1.90` tant qu'une nouvelle
  calibration LOT43 ne prouve pas et ne versionne pas une autre valeur ;
- génération OpenRouter serveur uniquement avec modèle
  `openai/gpt-4o-mini`, timeout de 8 secondes, prompt versionné et validateur de
  citations ;
- trois conversations simultanées au maximum, une par utilisateur, file
  bornée à six demandes, puis refus explicite `429`/`503` ;
- quota de six requêtes de chat par minute et par utilisateur ;
- aucun retry après envoi d'une requête générative ; circuit ouvert 60 secondes
  après cinq échecs fournisseur en 60 secondes ;
- panne OpenRouter, preuve insuffisante ou citation invalide : refus fail-closed,
  jamais de réponse inventée ni de fallback non homologué ;
- aucun contenu complet de conversation, secret ou PII transmis aux logs ou au
  fournisseur.

Si l'un de ces paramètres change, le manifeste de release, les tests concernés
et la baseline sont régénérés avant promotion.

## 5. État initial vérifié

Au début de la finalisation :

- `main` et `origin/main` pointent sur
  `60e97e66692ce25fa5467668ca1e74ea3c3c4973`, dont la CI est verte ;
- les PR 56 et 77 sont encore ouvertes en brouillon ;
- LOT38, LOT39bis et LOT40 ont des éléments uniquement dans des stashes ;
- LOT39 fournit le harnais, mais aucun golden actif ni baseline réelle ;
- les verrous `real_documents_allowed`, `ui_runtime_allowed`,
  `answer_generation_allowed` et `curated_ingestion_allowed` sont à `false` ;
- tous les cas de transition interdisent encore corpus, fichiers et pipeline
  réels ;
- la checklist de production n'a pas de preuves de l'environnement cible ;
- LOT32 et LOT35 interdisent toujours un verdict go-live complet.

Une CI source verte prouve la qualité du commit, pas la readiness du système.

## 6. Invariants non négociables

1. Le cockpit ne communique qu'avec l'API contractuelle de `rag-engine`.
2. Aucun service n'importe directement le code d'un autre service.
3. Aucun document ne rejoint l'index servi sans
   `quality → gate → review`.
4. Aucun verrou n'est activé par effet de bord.
5. Chaque lot utilise une branche, une PR et un rapport distincts.
6. Aucun secret, PII ni chemin absolu machine-local n'est versionné.
7. Les contrôles de substance, droits, provenance, PII et couverture portent
   sur 100 % du corpus et des 39 notions.
8. Toute erreur de contrat, d'identité, de gouvernance, de donnée ou de preuve
   ferme le chemin public.
9. Un stash, un worktree ou un répertoire runtime n'est jamais une livraison.
10. Un test d'intégration requis n'est ni remplacé par un mock, ni ignoré.

## 7. Autorités et décisions séparées

Trois décisions différentes sont requises :

| Décision | Autorité | Moment | Preuve |
| --- | --- | --- | --- |
| `PREPARE_TRANSITION` | commanditaire/lead | déjà reçue le 31 juillet 2026 | validation du présent design et commit du design |
| `PROMOTE_GOVERNANCE` | commanditaire/lead, jamais l'agent implémenteur seul | après LOT43 vert, avant fusion de LOT44 | approbation GitHub explicite de la PR LOT44, référencée dans `docs/releases/pilot_v1/promotion_authorization.yml` |
| `GO_LIVE_READY` | commanditaire/lead | après LOT45, depuis les preuves de production | approbation GitHub explicite du rapport LOT45 et entrée horodatée dans `docs/releases/pilot_v1/release_decision.yml` |

Le lead est le propriétaire humain du dépôt ou son délégataire humain déclaré.
Une validation d'agent, un test vert ou un merge automatique ne remplace pas
ces deux dernières décisions. Sans preuve d'autorité, LOT44 et LOT46 s'arrêtent.

## 8. Source de vérité multi-support

`main` est la source de vérité des intentions, contrats et références
immuables, mais certains objets ne doivent pas être dans Git :

| Objet | Store autoritatif | Référence versionnée dans `main` | Accès et rétention |
| --- | --- | --- | --- |
| code, configs, ADR, goldens, rapports nettoyés | GitHub `main` + tag | contenu Git | lecture publique/équipe selon dépôt ; conservation historique |
| corpus réel sous droits | object store chiffré, adressé par contenu | URI opaque, taille, licence et SHA-256 dans le manifeste | publisher + reviewers ; durée de publication + 12 mois de preuve, sauf retrait légal immédiat |
| images de conteneur | registre OCI | digest `sha256` de chaque image | opérateurs ; tag de release + deux releases précédentes, minimum 90 jours |
| base publiée | PostgreSQL cible | migration head, manifeste de publication et digest du backup | services/opérateurs ; backups quotidiens 30 jours et hebdomadaires 12 semaines |
| sauvegardes | stockage chiffré hors hôte | identifiant opaque, date, digest et résultat du restore | opérateurs autorisés uniquement ; politique précédente |
| secrets | fichier secret root-only `0600` sur l'hôte + copie de reprise chiffrée | noms requis seulement, jamais valeur ni hash | opérateurs ; rotation à chaque incident et à chaque changement de rôle |
| preuves brutes d'environnement | archive d'audit chiffrée hors Git | digest, horodatage et synthèse expurgée | lead + opérateurs ; 12 mois minimum |

Le manifeste `docs/releases/pilot_v1/release_manifest.yml` relie ces stores. Une
référence manquante, mutable sans version ou dont le digest diffère entraîne
`NO_GO`.

## 9. Séquence de livraison par lots

Chaque ligne ci-dessous correspond à une branche, une PR et un rapport séparés.
Un lot ne commence qu'après fusion du prédécesseur, sauf analyse read-only.

| Lot | Responsabilité unique | Rapport | Dépend de |
| --- | --- | --- | --- |
| LOT37R | réconcilier PR 56/77, CI et travaux Git nécessaires | `docs/reports/lot_37r_source_truth_reconciliation.md` | design |
| LOT38 | créer la politique réelle dormante et ses tests de réfutation, sans activer les verrous globaux | `docs/reports/lot_38_governance_transition.md` | LOT37R |
| LOT39bis | versionner goldens substantiels et seuils absolus, sans revendiquer de baseline nominale | `docs/reports/lot_39bis_golden_suite.md` | LOT38 |
| LOT40 | migrations et retrieval hybride nominal | `docs/reports/lot_40_hybrid_retrieval.md` | LOT39bis |
| LOT41 | imposer identité et filtres serveur exhaustifs | `docs/reports/lot_41_profile_filter_enforcement.md` | LOT40 |
| LOT42 | qualifier puis publier le corpus pilote dans une DB de validation | `docs/reports/lot_42_pilot_corpus_publication.md` | LOT41 |
| LOT43 | figer snapshot, baseline, sécurité et performance ; produire le verdict pré-promotion | `docs/reports/lot_43_pilot_evaluation.md` | LOT42 |
| LOT44 | promouvoir explicitement les verrous et les kill switches du pilote | `docs/reports/lot_44_governance_promotion.md` | LOT43 + `PROMOTE_GOVERNANCE` |
| LOT45 | déployer, tester et exercer backup/restore/rollback en production sombre | `docs/reports/lot_45_pilot_production_readiness.md` | LOT44 |
| LOT46 | réconcilier tous les artefacts, fusionner la décision finale et créer le tag | `docs/reports/lot_46_pilot_release.md` | LOT45 + `GO_LIVE_READY` |

Si un lot échoue, il reste `NO_GO`; sa correction passe par un lot/PR de
remédiation distinct avant de reprendre la séquence.

## 10. Contrats de chaque lot

### 10.1 LOT37R — réconciliation Git et CI

- comparer les PR 56 et 77 au `main` courant ;
- rebaser/reconstruire uniquement les apports nécessaires ;
- fermer les doublons/obsolètes avec justification ;
- auditer les stashes LOT38 à LOT40 sans application globale ;
- conserver une CI globale fail-closed sans récursion de `ci-local.sh` ;
- ne supprimer que les branches prouvées fusionnées ou remplacées.

### 10.2 LOT38 — politique dormante

LOT38 ajoute l'ADR, le scope `libre_terminale_maths_nsi_real_v1`, la matrice
d'autorisation et des tests de réfutation. Tous les verrous globaux restent à
`false`. La politique représente l'état `eligible_for_promotion`, jamais
`active`.

Les tests doivent refuser : autorisation absente, partielle, périmée, signature
absente, taxonomie modifiée, collection supplémentaire, mauvais tenant/profil,
droits inconnus, PII non vérifiée ou rollback absent. Chaque consommateur
runtime doit charger le scope autorisé et refuser tout hors-scope ; un simple
booléen global ne suffit pas.

### 10.3 LOT39bis — goldens absolus

La suite contient au minimum :

- cinq requêtes positives distinctes par notion, soit 195 requêtes ;
- vingt cas négatifs/confusion par matière, soit 40 supplémentaires ;
- total minimal : 235 requêtes ;
- chaque notion reliée à une ressource substantielle et à au moins un jugement
  positif ;
- `must_not_return` pour chaque cas de fuite pertinent ;
- revue humaine de 100 % des requêtes et de leurs jugements.

LOT39bis fixe les seuils de section 11 et le hash de la suite. Il ne fabrique
pas de baseline sans corpus publié ni DB réelle.

### 10.4 LOT40 — retrieval et migrations

- PostgreSQL/pgvector reproductible, migration head consigné ;
- dense + lexical + RRF + rerank selon section 4 ;
- préfixes `query:` et `passage:` canoniques ;
- ordre total stable et MMR déterministe ;
- citations conformes au contrat ;
- tests unitaires, migrations, intégration DB et smoke réels.

Une migration additive/transactionnelle fournit et teste un down migration.
Une migration destructive ou dont le retour perdrait des données n'a pas de
down trompeur : elle utilise expand/contract et exige avant application un
backup dont le restore a été testé. Sans l'une de ces deux stratégies, la
migration est refusée.

### 10.5 LOT41 — filtres et identité

Le serveur dérive et applique simultanément : `tenant`, `niveau`, `voie`,
`matiere`, `statut_enseignement`, `candidat`, `audience`, `rights`,
`visibility`, `review_status=reviewed`, collections autorisées et année de
programme. Le client peut seulement restreindre, jamais élargir.

Les tests couvrent la matrice des trois valeurs de candidat, deux matières,
profils AEFE/hors niveau/hors voie, collection arbitraire, override client,
IDOR, cache après révocation et contenu `needs_review`/quarantaine.

### 10.6 LOT42 — publication gouvernée

Chaque ressource suit :

```text
staging hors index
  → extraction/chunking
  → quality et substance
  → reviewer_pedagogique + reviewer_droits + reviewer_technique
  → responsable_validation
  → package canonique + hashes
  → publisher rag-engine
  → vérification de l'index publié
```

Les trois reviewers spécialisés doivent approuver. Tout désaccord ou champ
inconnu mène à `quarantine` ou `request_more_information`; aucune majorité ni
override du responsable n'est autorisé. Chaque décision porte l'identifiant
stable du reviewer authentifié, son rôle, l'heure UTC et le hash du package.
Le responsable vérifie l'unanimité et produit une signature Ed25519 détachée du
JSON canonique. Le registre des clés publiques est versionné ; les clés privées
restent dans le secret store. Le publisher refuse une clé inconnue, révoquée ou
une signature invalide. Tous les reviewers figurent dans un registry autorisé ;
les décisions et tentatives sont append-only.

Une révocation produit un package de retrait lié au package initial, désactive
immédiatement les chunks dans l'index, invalide les caches et force une nouvelle
baseline. La preuve de revue inclut le nombre exact de ressources/chunks et
doit couvrir 100 % du manifeste.

### 10.7 LOT43 — baseline reproductible

Le manifeste d'évaluation lie obligatoirement :

- SHA de `main`, migrations, contrats et taxonomies ;
- hash de la suite golden ;
- manifeste corpus, tous les doc/chunk SHA et snapshot DB ;
- modèle embedding, dimension, révision et digest d'artifact ;
- reranker, révision et digest ;
- RRF, top-k, MMR, seuils et version du code ;
- prompt et modèle OpenRouter pour les tests génératifs ;
- environnement matériel et versions runtime.

Toute valeur non épinglée ou tout digest divergent interdit la comparaison.
La baseline initiale doit d'abord satisfaire tous les seuils absolus ; elle ne
peut pas devenir verte uniquement parce qu'aucune baseline précédente n'existe.

### 10.8 LOT44 — promotion

Après l'approbation `PROMOTE_GOVERNANCE`, LOT44 passe explicitement les verrous
nécessaires à `true`, chacun relié à l'ADR et au manifeste LOT43. Cette PR rend
le code capable de servir le pilote, mais les kill switches d'exploitation
restent désactivés par défaut :

- `RAG_PUBLIC_PILOT_ENABLED=false` ;
- `RAG_GENERATION_ENABLED=false` ;
- `RAG_CURATED_PUBLICATION_ENABLED=false`.

Absence, valeur invalide ou scope différent équivaut à `false`. L'allowlist
runtime ne contient que les deux collections de section 3.

### 10.9 LOT45 — production sombre

Environnement logique : `nexus-production-1`, serveur Ubuntu 22.04/24.04,
minimum 8 vCPU, 32 Go RAM, 100 Go SSD. Domaine public :
`https://nexusreussite.academy`. Les domaines historiques
`rag-ui.nexusreussite.academy` et `rag-api.nexusreussite.academy` servent
uniquement au canary opérateur/rollback et ne donnent pas au navigateur un
accès direct au moteur gouverné.

LOT45 déploie d'abord avec les kill switches publics à `false`, exécute les
smokes, le test de charge, le soak, la sécurité, les alertes et le restore, puis
active le pilote pour la recette authentifiée. Il met à jour la checklist pour
faire de `lot_45_pilot_production_readiness.md` le rapport autoritatif ; le
rapport LOT26.4 reste une preuve historique, pas la décision courante.

### 10.10 LOT46 — clôture

LOT46 vérifie qu'aucun élément requis n'est seulement local, intègre la décision
`GO_LIVE_READY`, fusionne le manifeste final, nettoie les branches/stashes
uniquement après preuve de reprise ou d'obsolescence, puis crée et pousse un tag
annoté. Si l'autorisation finale manque, aucun tag go-live n'est créé.

## 11. Seuils de recette objectifs

### 11.1 Retrieval et citations

| Mesure | Seuil obligatoire |
| --- | --- |
| Recall@5 | ≥ 0,80 |
| Recall@10 | ≥ 0,90 |
| Recall@20 | ≥ 0,95 |
| nDCG@10 | ≥ 0,85 |
| MRR | ≥ 0,85 |
| fuite `must_not_return` | 0 |
| citations complètes/valides | 100 % |
| refus correct des 40 cas négatifs | 100 % |
| réponse vide sur requête positive | ≤ 2 % et aucune notion à 100 % vide |

Les seuils s'appliquent globalement, par matière et par notion ; une moyenne
globale ne masque pas une notion sans résultat substantiel.

### 11.2 Performance et stabilité

- retrieval : 0,5 requête/s pendant 15 minutes, au moins 450 requêtes,
  p95 ≤ 3 secondes, taux de 5xx < 1 % et aucune fuite ;
- chat : trois conversations simultanées pendant 30 minutes, au moins 90 tours,
  p95 bout en bout ≤ 15 secondes, premier événement ≤ 5 secondes,
  timeouts/5xx < 1 % ;
- surcharge au-delà des bornes : `429`/`503` en moins d'une seconde, sans file
  infinie, crash ni OOM ;
- soak sombre : 24 heures, probe authentifiée chaque minute, disponibilité
  ≥ 99,5 %, zéro dérive de gouvernance et zéro fuite de secret/PII.

### 11.3 Sécurité et exploitation

- zéro vulnérabilité critique ou élevée connue dans les dépendances et images
  effectivement déployées ;
- zéro secret dans Git, bundles et logs ;
- tous les tests RBAC, IDOR, CSRF, SSRF, XSS/CSP, injection documentaire,
  isolation tenant et révocation verts ;
- alertes disponibilité, 5xx, p95, saturation, échec OpenRouter, échec backup et
  dérive de gouvernance déclenchées synthétiquement puis reçues ;
- RPO ≤ 24 heures ; RTO ≤ 2 heures ; restore complet exécuté en ≤ 2 heures ;
- rollback applicatif et données exécuté en ≤ 30 minutes après décision.

## 12. Matrice de preuve minimale

Chaque rapport de lot contient une table :

`critère → responsable → commande/procédure → environnement → artefact → digest
→ verdict`.

Le responsable est l'auteur technique pour les tests, l'un des quatre rôles de
review pour le corpus, l'opérateur pour la production et le lead pour les deux
autorisations humaines. Une ligne sans environnement, digest ou responsable
est incomplète.

Les dettes de `docs/reports/lot_0_dettes.md` sont classées par LOT37R en :
`bloquante_pilote`, `non_bloquante_avec_preuve` ou `hors_perimetre`. Toute dette
touchant droits, notions, contenu non revu, chunking, contrat, sécurité ou
reproductibilité est bloquante tant que LOT43 n'a pas prouvé le contraire.

## 13. Critères de sortie

La release est prête uniquement si :

1. `main` est propre, synchronisé et protégé par PR ;
2. la CI du SHA candidat est entièrement verte ;
3. aucune PR requise pour le pilote ne reste ouverte ;
4. aucun artefact requis n'existe uniquement localement ;
5. les deux autorisations humaines requises sont prouvées ;
6. la politique LOT38 et la promotion LOT44 sont cohérentes et limitées ;
7. les 235+ goldens et la baseline reproductible passent les seuils ;
8. les migrations et le retrieval passent contre PostgreSQL réel ;
9. les 39 notions ont une substance publiée et revue ;
10. aucun contenu non revu, hors droits/profil ou révoqué n'est retourné ;
11. la checklist LOT45 contient toutes les preuves de l'environnement cible ;
12. backup, restore, alertes et rollback respectent les objectifs ;
13. le rapport LOT46 relie SHA, tag, images, corpus, DB, métriques et décision.

Un seul critère rouge maintient le verdict `NO_GO`.

## 14. Rollback fail-closed

Les verrous versionnés indiquent qu'une capacité est autorisable ; les kill
switches d'exploitation indiquent si elle est effectivement servie. Le rollback
ne modifie donc jamais directement `main` :

1. passer les trois kill switches à `false` dans le secret/config store ;
2. recharger les services et vérifier que UI, génération et publication
   refusent ;
3. restaurer les images précédentes par digest ;
4. exécuter le down migration testé ou le restore correspondant à la stratégie
   déclarée ;
5. vérifier manifestes, corpus actif, caches et autorisations ;
6. consigner l'incident et les preuves dans l'archive d'audit.

Les switches sont fermés par défaut et testés sans dépendre de l'état des
booléens Git. Un rollback qui laisse un corpus, un cache ou une route plus
permissif que l'état servi est incomplet.

## 15. Extensions après le pilote

Chaque collection supplémentaire répète autorisation, substance exhaustive,
publication, goldens, évaluation, readiness et rollback. Le pilote valide le
procédé, jamais automatiquement les autres collections.
