# Protocole d’évaluation retrieval metadata-only

## 1. Objectif

Définir une première évaluation retrieval sans moteur vectoriel, sans embeddings, sans Qdrant et sans document réel.

## 2. Périmètre

Le périmètre suit le scope pilote 17C :

- matière : mathématiques ;
- niveau : terminale ;
- voie : générale ;
- enseignement : spécialité mathématiques ;
- contexte : AEFE Tunisie ;
- candidat : scolarisé ;
- usage : préparation pédagogique encadrée Nexus Réussite.

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
- aucun appel réseau ;
- aucune génération de réponse finale ;
- aucun data/staging.

## 4. Évaluation autorisée

Uniquement :

- requêtes synthétiques ;
- profils élèves synthétiques ;
- filtres metadata attendus ;
- exigences de citation ;
- critères de pertinence pédagogiques ;
- cas de refus ;
- validation de cohérence déclarative.

## 5. Types de cas

- recherche de fiche de cours ;
- recherche d’exercice ;
- recherche de sujet type bac ;
- recherche de correction ;
- recherche ciblée par notion ;
- recherche interdite faute de droits ;
- recherche non répondable sans corpus réel.

## 6. Critères de pertinence

Un cas metadata-only est valide si :

- le niveau est terminale ;
- la matière est mathématiques ;
- l’enseignement est spécialité ;
- la visibilité est explicite ;
- les droits sont compatibles retrieval ;
- les filtres attendus sont complets ;
- les citations sont exigées ;
- aucune réponse finale n’est générée ;
- aucun document réel n’est nécessaire.

## 7. Conditions avant retrieval réel

Avant tout retrieval réel :

- corpus réel validé humainement ;
- documents listés ;
- droits confirmés ;
- parsing séparé ;
- chunking séparé ;
- embeddings séparés ;
- Qdrant séparé ;
- golden set validé ;
- tests et doctors verts.

## 8. Cohérence des cas metadata-only

Un cas metadata_filter_only prêt pour revue exige :

- profil élève cohérent avec le scope 17C ;
- expected_filters complet ;
- droits retrieval explicites ;
- visibilité student_visible ;
- notions non vides ;
- compétences non vides ;
- citations obligatoires ;
- critères pédagogiques non vides ;
- aucune génération de réponse.

## 9. Cohérence des cas de refus

Un cas de refus prêt pour revue exige :

- expected_filters vide ;
- comportement refuse_* ;
- critère must_refuse_* ou no_answer_generation ;
- aucune génération de réponse.
