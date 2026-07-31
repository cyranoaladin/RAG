# Finalisation go-live du pilote Nexus — conception validée

> Statut : validé par le commanditaire le 31 juillet 2026.
>
> Autorité reçue : engager une transition de gouvernance explicite vers un
> go-live contrôlé. Cette autorité ne permet ni de contourner les preuves, ni
> d'activer un verrou par effet de bord, ni de déclarer prêtes des collections
> dont la substance n'est pas démontrée.
>
> Périmètre de release : `libre_terminale`, spécialités Mathématiques et NSI.

## 1. Décision

La première release publique exploitable de Nexus porte sur le vertical pilote
`libre_terminale` Mathématiques + NSI. Elle doit être terminée, testée, déployée
et réversible sur ce périmètre avant toute extension aux autres collections.

La cible d'architecture publique multi-matières décrite dans
`2026-07-29-go-live-public-multimatieres-design.md` reste valide. Le présent
document remplace uniquement son lancement atomique à 59 collections par une
progression prouvable : pilote d'abord, extension ensuite par collection.

Le projet n'utilise pas « 100 % » pour signifier que toute la roadmap future est
épuisée. Pour cette release, « 100 % » signifie que tous les critères de sortie
du pilote sont démontrés sur l'environnement cible, sans exception cachée,
preuve locale non publiée ou dette bloquante.

## 2. Alternatives examinées

### 2.1 Clôture `metadata-only`

Cette option préserverait les verrous actuels et permettrait une clôture rapide
du dépôt. Elle est rejetée comme go-live produit : les documents réels, l'UI
runtime, la génération sourcée et l'ingestion curatée resteraient désactivés.

### 2.2 Pilote contrôlé Mathématiques + NSI

Cette option est retenue. Elle limite le risque et rend possible un contrôle
exhaustif de la substance, des droits, du retrieval, des citations et de
l'exploitation réelle.

### 2.3 Ouverture immédiate des 59 collections

Cette option est différée. Le dépôt annonce 59 collections, mais seules quelques
collections possèdent aujourd'hui une substance indexée démontrée. Une présence
de taxonomie ou de référence générique ne constitue pas une preuve pédagogique.

## 3. État initial vérifié

Au début de la finalisation :

- `main` local et `origin/main` pointent sur le même commit
  `60e97e66692ce25fa5467668ca1e74ea3c3c4973` ;
- la CI GitHub de ce commit est verte ;
- la PR 77 et la PR 56 sont encore ouvertes en brouillon ;
- LOT38, LOT39bis et LOT40 comportent des éléments uniquement conservés dans
  des stashes locaux ;
- LOT39 fournit un harnais testé, mais aucun golden actif ni baseline réelle ;
- les configurations de gouvernance conservent notamment
  `real_documents_allowed`, `ui_runtime_allowed`,
  `answer_generation_allowed` et `curated_ingestion_allowed` à `false` ;
- tous les cas de `transition_authorization.yml` interdisent encore le corpus
  réel, les fichiers réels et le pipeline réel ;
- la checklist de production n'est pas remplie avec des preuves issues d'un
  environnement cible ;
- les rapports LOT32 et LOT35 interdisent encore de conclure à un go-live
  complet.

Une CI source verte prouve donc la qualité du commit, pas la readiness du
système déployé.

## 4. Invariants non négociables

Les règles d'`AGENTS.md` restent applicables pendant tous les lots :

1. `packages/contracts` reste l'unique source des contrats partagés.
2. Le cockpit passe uniquement par l'API contractuelle de `rag-engine`.
3. Aucun service n'importe directement le code d'un autre service.
4. Aucun document ne rejoint l'index servi sans
   `quality → gate → review`.
5. Chaque verrou est activé explicitement, avec autorisation et ADR ; aucune
   activation transitive ou implicite n'est acceptée.
6. Les droits, la provenance, l'absence de PII, les checksums et le rollback
   sont démontrés pour l'intégralité du corpus pilote.
7. Chaque lot utilise une branche, une PR et un rapport distincts.
8. Aucun secret, jeton, identifiant ou chemin absolu machine-local n'est
   versionné.
9. Une métrique verte porte sur tout son périmètre déclaré.
10. Toute erreur de contrat, de gouvernance, de données ou de preuve ferme le
    chemin public en mode fail-closed.

## 5. Source de vérité et hygiène Git

`main` devient l'unique source de vérité de la release selon les règles
suivantes :

- aucune modification n'est commise directement sur `main` ;
- chaque changement est reconstruit depuis `main`, revu et fusionné par PR ;
- un stash n'est jamais considéré comme une livraison et n'est jamais appliqué
  en bloc sans audit ;
- les éléments utiles des stashes LOT38 à LOT40 sont réintroduits par petits
  diffs prouvés, avec tests rouges puis verts pour tout comportement ;
- les PR 56 et 77 sont comparées au `main` courant : les apports encore utiles
  sont rebasés ou reconstruits, les doublons et travaux obsolètes sont fermés
  avec justification ;
- les branches distantes historiques ne sont pas supprimées uniquement pour
  réduire leur nombre ; seules les branches fusionnées, obsolètes ou remplacées
  avec certitude sont nettoyées ;
- la release finale est identifiée par un tag annoté après fusion et validation
  de l'environnement cible.

À la clôture, aucun code, migration, configuration, golden ou preuve requis
pour reproduire la release ne doit exister uniquement dans un worktree, un
stash ou un répertoire runtime local.

## 6. Séquence de livraison

### 6.1 Assainissement des travaux ouverts

Avant la transition fonctionnelle :

- auditer les PR 56 et 77 contre le `main` courant ;
- déterminer pour chaque changement s'il est déjà intégré, toujours nécessaire,
  contradictoire ou obsolète ;
- ne reprendre que les changements nécessaires au pilote ;
- obtenir une CI globale réellement bloquante sans réintroduire la récursion
  historique de `scripts/ci-local.sh` ;
- consigner les décisions de fermeture ou de remplacement.

### 6.2 LOT38 — transition de gouvernance réfutable

LOT38 introduit une autorisation dédiée au pilote réel. Il doit :

- ajouter un ADR décrivant la portée, les risques, les preuves exigées et le
  rollback de la transition ;
- définir un cas d'autorisation explicite limité à
  `libre_terminale` Mathématiques + NSI ;
- représenter sans ambiguïté l'autorisation du corpus, des fichiers et du
  pipeline réels ;
- exiger le sign-off humain final, les droits, la provenance, l'absence de PII,
  le plan de checksum et le rollback ;
- lier chaque verrou activé à l'ADR sur une ligne ajoutée ;
- refuser tout niveau, matière, collection ou mode d'usage hors périmètre ;
- fournir des tests de réfutation : autorisation absente, partielle, périmée,
  incohérente ou hors pilote doit bloquer.

L'activation de `real_documents_allowed`, `ui_runtime_allowed`,
`answer_generation_allowed` ou `curated_ingestion_allowed` n'intervient que si
la sémantique d'autorisation correspondante existe et que ses tests sont verts.
Un simple passage de `false` à `true` est interdit.

Si la transition nécessite une évolution du contrat partagé, elle reçoit une
version SemVer et un ADR. Aucun service ne redéfinit localement cette évolution.

### 6.3 LOT39bis — goldens et baseline substantiels

LOT39bis complète le harnais déjà présent :

- au moins 200 requêtes dorées substantielles sur l'ensemble du pilote ;
- une couverture explicite des deux matières et des notions obligatoires ;
- des requêtes positives, négatives, ambiguës et de confusion inter-niveaux ;
- des jugements gradués, des résultats interdits `must_not_return` et des
  attentes de citations ;
- une empreinte déterministe de la suite ;
- une baseline produite contre le pipeline nominal et la base cible de test ;
- un garde CI qui refuse une régression, une fuite, une citation incomplète ou
  une suite plus petite/incompatible ;
- une revue de substance sur 100 % des requêtes, pas uniquement sur un
  échantillon.

Le fallback lexical peut servir au diagnostic, mais ne peut pas produire la
baseline nominale ni attester le pipeline hybride.

### 6.4 LOT40 — retrieval hybride et base réelle

LOT40 termine le chemin de retrieval du pilote :

- appliquer les migrations nécessaires sur une base PostgreSQL/pgvector de
  test reproductible ;
- combiner correctement recherche dense et lexicale ;
- appliquer côté serveur tenant, niveau, matière, droits, visibilité et statut
  de revue ;
- exclure tous les chunks non publiés, hors profil ou interdits ;
- conserver les préfixes d'embedding canoniques et un MMR déterministe ;
- retourner les citations contractuelles sans accès direct du cockpit à la DB ;
- exécuter les tests unitaires, d'intégration, migrations aller/retour, smoke et
  le harnais nominal ;
- mesurer les latences p50/p95 et documenter la capacité réellement prouvée.

Toute fonctionnalité LOT41 n'est intégrée que si un critère du pilote la rend
nécessaire. Elle reste sinon un lot distinct, sans mélange de périmètre.

### 6.5 Publication gouvernée du corpus pilote

Chaque ressource candidate suit le circuit complet :

```text
source autorisée
  → staging hors index servi
  → extraction et chunking
  → qualité et substance
  → contrôle des droits/provenance/PII
  → gate
  → revue humaine
  → paquet de publication avec checksums
  → écriture par rag-engine
  → vérification dans l'index servi
```

La matrice de preuve relie pour chaque notion : ressource substantielle, droits,
chunks publiés, requêtes golden et résultats attendus. Une notion sans ressource
qui l'enseigne réellement bloque la promesse de couverture correspondante.

### 6.6 Validation de production

Le dernier lot s'exécute sur l'environnement cible et renseigne la checklist de
production avec des preuves horodatées :

- infrastructure, DNS, Nginx et TLS ;
- secrets distincts, permissions et absence de secrets dans Git/logs ;
- services et modèles healthy ;
- migrations appliquées et corpus pilote publié ;
- smoke tests d'authentification, retrieval, ingestion et revue ;
- E2E du cockpit, refus sans source et citations valides ;
- observabilité et alertes ;
- sauvegarde effectuée et restauration réellement testée ;
- rollback applicatif et données testé ;
- vérification de sécurité et des dépendances déployées ;
- validation finale `GO_LIVE_READY` dans le rapport de release.

Les preuves qui nécessitent un serveur, des secrets ou un DNS ne peuvent pas
être remplacées par des mocks ou par l'existence d'un script dans le dépôt.

## 7. Architecture de confiance du pilote

```text
Navigateur authentifié
        |
        v
Cockpit Next.js / BFF
        |
        | contrat canonique + identité minimisée
        v
rag-engine
   |             \
   |              \ génération sourcée autorisée
   v               v
pgvector publié   fournisseur homologué

rag-pedago
   |
   v
staging → quality → gate → review
                           |
                           v
                 paquet de publication
                           |
                           v
                    publisher rag-engine
```

Le chemin de lecture reste séparé du chemin de publication. Le cockpit ne voit
ni documents bruts, ni identifiants de base, ni secrets fournisseur.

## 8. Critères de sortie obligatoires

La release est déclarée prête uniquement si tous les critères suivants sont
verts simultanément :

1. `main` est propre, synchronisé et protégé par PR.
2. La CI du SHA candidat est entièrement verte.
3. Aucune PR requise pour le pilote ne reste ouverte.
4. Aucun artefact nécessaire au pilote n'existe uniquement localement.
5. La transition LOT38 est cohérente, testée, reliée à son ADR et limitée au
   pilote.
6. Les goldens LOT39bis et leur baseline sont versionnés et reproductibles.
7. Le retrieval nominal LOT40 passe contre PostgreSQL/pgvector réel.
8. Le corpus pilote a franchi `quality → gate → review` dans son intégralité.
9. Aucun contenu non revu, hors droits ou hors profil n'est retourné.
10. Les réponses sans preuve suffisante sont refusées ; les autres citent des
    sources valides.
11. La checklist de production est remplie avec des preuves de l'environnement
    cible.
12. Backup, restore et rollback sont testés.
13. Aucun secret ni PII n'est détecté dans Git ou les journaux de validation.
14. Le rapport final contient le SHA, le tag, les versions, les métriques, les
    preuves et la décision `GO_LIVE_READY`.

Un seul critère rouge maintient le verdict `NO_GO`.

## 9. Rollback et incidents

La release conserve au minimum :

- l'image et le SHA applicatif précédents ;
- une sauvegarde cohérente de la base avant migration/publication ;
- les manifestes et checksums des corpus avant/après ;
- une procédure de retrait immédiat du chemin public ;
- une migration de retour testée ou, si elle est irréversible, une restauration
  testée ;
- un moyen de désactiver génération et UI sans perdre les preuves ;
- une journalisation d'incident sans contenu élève ni secret.

Après rollback, les verrous et autorisations doivent refléter l'état réellement
servi. Un rollback applicatif qui laisse un corpus ou un verrou dans un état
plus permissif est considéré incomplet.

## 10. Extensions après le pilote

Chaque collection supplémentaire répète les mêmes preuves : autorisation,
substance exhaustive, publication gouvernée, goldens, évaluation, readiness et
rollback. Le succès du pilote valide le procédé, pas automatiquement les 57
autres collections.

La roadmap multi-niveaux et multi-matières reste ouverte après la release pilote
et ne doit pas être confondue avec une dette cachée du périmètre livré.
