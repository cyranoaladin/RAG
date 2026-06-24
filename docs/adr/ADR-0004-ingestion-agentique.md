# ADR-0004 — Ingestion agentique sous gouvernance

- **Statut** : Accepté
- **Date** : 2026-06-24
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0001 (séparation), ADR-0003 (audience/métadonnées)
- **Déclenche** : la remontée de la Phase 4 (ingestion) avant la fin de la Phase 1 ; la levée scopée des verrous `network_allowed`/`ingestion_allowed`
- **Conditionne** : Lots 4.1 (découverte), 4.2 (fetch admis), 4.3 (revue + import), puis reprise du Lot 1.1 (chunking) sur le contenu admis

## Contexte

L'audit du Lot 1.1 a établi que le corpus disciplinaire n'existe pas dans le dépôt : les fiches `SPE_*`/`TRONC_*` sont des fiches de cadrage (programme, épreuves, modalités), pas des cours. Décision (Option 2) : constituer le corpus pédagogique par **ingestion agentique** depuis des sources web officielles et libres, avant d'embedder. Cette acquisition touche le cœur des verrous de gouvernance de `rag-pedago` (`network_allowed`, `ingestion_allowed`) et doit donc être encadrée explicitement.

## Problème

Aller chercher du contenu sur le web et l'ingérer ouvre trois risques majeurs : conformité (robots.txt, droits/licences), qualité pédagogique (contenu hors-programme, erroné, daté), et sécurité/gouvernance (un agent autonome qui écrit dans le corpus sans contrôle). L'architecture doit produire du contenu utilisable **sans** sacrifier la gouvernance qu'on a durcie.

## Décision

### 1. Principe : les agents proposent, les gates et l'humain disposent
Aucun agent n'écrit jamais dans le corpus ni dans pgvector. Tout contenu candidat traverse la chaîne `découverte → admission de source → fetch → extraction → quality → revue humaine → controlled import → ledger` avant d'exister dans le corpus. Le LLM assiste (formuler des requêtes, évaluer la pertinence d'une source vis-à-vis d'une notion, nettoyer l'extraction) mais ne décide jamais seul d'un import.

### 2. Placement
Découverte, admission et orchestration vivent dans `rag-pedago` (plan de contrôle : `scrapers/`, `services/workers/`). L'indexation reste dans `rag-engine`. La frontière d'ADR-0001 est préservée.

### 3. Levée scopée et progressive des verrous
`network_allowed` et `ingestion_allowed` ne passent à `true` que par le protocole `transition_authorization`, référençant **cet ADR** dans le diff (le garde-fou `check-governance-locks.sh` l'exige et le valide). La levée est **scopée**, jamais « internet ouvert » :
- domaines limités à une **whitelist** dérivée de `official_sources.yml` + sources libres validées en revue ;
- **robots.txt respecté** sans exception ;
- accès **lecture seule** : pas d'exécution de JavaScript, pas de requêtes mutantes, pas d'authentification ;
- **rate limiting** et user-agent identifiable ;
- aucune capacité d'écriture déclenchée par le LLM.

La levée est progressive : le Lot 4.1 (découverte) ne lève **rien** ; le Lot 4.2 (fetch) lève `network_allowed` scopé ; `ingestion_allowed` n'est levé qu'au Lot 4.3, après revue humaine.

### 4. Admission de source et droits
Priorité absolue aux sources **officielles** (Éduscol, BO, sujets/annales officiels) et **libres** (Creative Commons compatibles, domaine public). Toute source candidate est qualifiée par `source_admission_policy` : licence/`rights` vérifiés, conformité robots, pertinence vis-à-vis d'une notion de la taxonomie. Refus si les droits sont incompatibles ou la source non admise. Aucune reproduction de contenu sous copyright sans licence explicite.

### 5. Étiquetage à l'admission (schéma ADR-0003)
Chaque unité admise est étiquetée : `audience` (`tous` pour le disciplinaire, `libre`/`aefe` pour le spécifique-statut), `official`, `rights`, `source_label`/`source_uri`, `notions` (mappées sur la taxonomie), `type_doc`. Cet étiquetage conditionne le chunking (Lot 1.1 repris) et le filtrage de retrieval.

### 6. LLM et coûts
La découverte et l'extraction mobilisent le routing LLM en mode **asynchrone/batch** (chemin async de l'architecture, p. ex. Chutes), pas le chemin temps réel : l'ingestion est un traitement de fond, pas une interaction élève. Le LLM n'a aucun accès en écriture.

## Découpage en lots

- **Lot 4.1 — Découverte (aucun verrou levé).** Depuis la taxonomie (notions maths/NSI Terminale) et `official_sources.yml`, générer un **plan d'acquisition** : par notion, les sources candidates (label, URI présumé, rights présumés, `type_doc`/`audience` visés). Mesurer la couverture des notions. Aucun réseau, aucun fetch.
- **Lot 4.2 — Fetch admis (levée `network_allowed` scopée, ADR-0004 référencé).** Fetch des sources admises (whitelist, robots.txt, read-only, rate limit), extraction HTML/PDF → texte, quality automatique. Sortie = contenu candidat, non encore importé.
- **Lot 4.3 — Revue + import (levée `ingestion_allowed`).** Revue humaine des sources/contenus, étiquetage final, controlled import au corpus + ledger.
- **Puis** reprise du Lot 1.1 (chunker durci) sur le contenu admis, puis Lot 1.2 (embeddings).

## Conséquences

### Positives
- Le corpus se constitue à partir de sources officielles/libres, traçables et conformes.
- La gouvernance durcie au Lot 0 trouve son usage : la levée des verrous est tracée et validée automatiquement.
- Le LLM est cantonné à un rôle d'assistance sans pouvoir d'écriture.

### Négatives
- Chaîne longue (découverte → revue → import) : l'acquisition n'est pas instantanée. C'est le prix de la conformité et de la qualité.
- Dépendance à une revue humaine sur le chemin critique (Lot 4.3).

### Risques et mitigations
- *Scraping non conforme* → whitelist + robots.txt + lecture seule + revue.
- *Contenu web de mauvaise qualité ou daté* → quality gate + revue humaine + priorité aux sources officielles.
- *Violation de droits* → `rights` vérifiés à l'admission, refus par défaut, pas de copyright sans licence.
- *Dérive d'un agent autonome* → aucun pouvoir d'écriture ; les verrous ne se lèvent que scopés et tracés.
- *Coût LLM* → routing async/batch.

## Suites
- Mettre `docs/ROADMAP.md` à jour : Phase 4 remontée avant la fin de Phase 1 ; Lot 1.1 (chunker) en pause, repris après l'import.
- Lot 4.1 : plan d'acquisition et couverture, sans réseau.
