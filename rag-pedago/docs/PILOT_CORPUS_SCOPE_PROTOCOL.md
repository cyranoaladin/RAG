# Protocole de cadrage du corpus pilote

## 1. Objectif

Définir le périmètre d'un corpus pilote strictement synthétique ou metadata-only.

## 2. Périmètre du pilote

Le pilote cible prioritairement :

- matière : mathématiques ;
- niveau : terminale ;
- enseignement : spécialité mathématiques ;
- contexte : AEFE Tunisie ou contexte scolaire francophone équivalent ;
- type de candidat : candidat scolarisé ;
- usage : préparation pédagogique encadrée par Nexus Réussite.

## 3. Interdictions

- aucun document réel ;
- aucun PDF ;
- aucun DOCX ;
- aucun PPTX ;
- aucun XLSX ;
- aucune ingestion ;
- aucun parsing ;
- aucun chunking ;
- aucun embedding ;
- aucun Qdrant ;
- aucun scraping ;
- aucun réseau ;
- aucun data/staging.

## 4. Ressources autorisées

Uniquement :

- métadonnées synthétiques ;
- manifestes metadata-only ;
- fixtures synthétiques déjà versionnées ;
- références officielles déjà présentes ;
- taxonomies validées ;
- rapports Codex ;
- documents de protocole.

## 5. Métadonnées minimales obligatoires

Champs nécessaires pour un futur item pilote :

- doc_id ;
- source_type ;
- source_uri synthétique ou fixture ;
- sha256 synthétique si applicable ;
- niveau ;
- voie ;
- matière ;
- enseignement ;
- type_doc ;
- epreuve ;
- candidat ;
- rights ;
- visibility ;
- official_refs ;
- notions ;
- competences ;
- objectifs ;
- difficulty ;
- school_year ou session si applicable.

## 6. Critères d’acceptation

Un item pilote metadata-only est acceptable si :

- aucun document réel n’est requis ;
- les droits sont explicites ;
- la visibilité est explicite ;
- la matière et le niveau sont normalisés ;
- les références officielles sont présentes ou explicitement absentes ;
- les notions sont rattachées à une taxonomie existante ;
- l’item peut être audité sans lecture de contenu réel.

## 7. Exclusions

- tout item nécessitant un fichier réel ;
- tout item dont les droits sont inconnus ;
- tout item exposant une donnée élève réelle ;
- tout item dépendant d’un PDF ou d’une ressource privée ;
- tout item nécessitant embeddings ou Qdrant.

## 8. Conditions avant un futur corpus réel

- validation humaine écrite ;
- sources explicitement listées ;
- droits confirmés ;
- séparation parsing/chunking/embedding/upsert ;
- rollback prévu ;
- ledger protégé ;
- tests et doctors verts.

## 9. Cohérence du scope

Un scope prêt pour revue exige :

- valeurs pédagogiques strictes ;
- toutes les autorisations dangereuses à false ;
- toutes les ressources autorisées présentes ;
- aucune ressource réelle autorisée ;
- toutes les exclusions critiques présentes ;
- tous les champs metadata obligatoires présents ;
- tous les critères d’acceptation présents.
