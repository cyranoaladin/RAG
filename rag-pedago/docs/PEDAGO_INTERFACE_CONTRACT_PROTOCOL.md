# Protocole de contrat d’interface pédagogique metadata-only

## 1. Objectif

Définir le contrat d’interface pédagogique du RAG sans API runtime, sans serveur, sans UI réelle, sans retrieval réel et sans génération de réponse.

## 2. Périmètre

Le contrat suit le scope 17C et l’évaluation 17D :

- mathématiques ;
- terminale ;
- voie générale ;
- spécialité mathématiques ;
- contexte AEFE Tunisie ;
- candidat scolarisé ;
- usage pédagogique encadré Nexus Réussite.

## 3. Interdictions

- aucun serveur ;
- aucun endpoint réel ;
- aucun runtime API ;
- aucun composant UI réel ;
- aucun retrieval réel ;
- aucun document réel ;
- aucun PDF ;
- aucune ingestion ;
- aucun parsing ;
- aucun chunking ;
- aucun embedding ;
- aucun Qdrant ;
- aucune génération de réponse finale ;
- aucun réseau ;
- aucun data/staging.

## 4. Personas

Personas autorisés :

- eleve ;
- enseignant ;
- administrateur_pedagogique.

## 5. Parcours autorisés

- recherche metadata-only par l’élève ;
- revue pédagogique par l’enseignant ;
- validation de refus contrôlé ;
- vérification des citations exigées ;
- affichage d’un état sans source ;
- affichage d’une impossibilité de réponse.

## 6. Sorties autorisées

Uniquement :

- filtres metadata attendus ;
- politique de citation attendue ;
- comportement attendu ;
- état de refus ;
- message d’explication non génératif ;
- exigences de revue humaine.

## 7. Sorties interdites

- réponse pédagogique finale ;
- contenu d’un document réel ;
- extrait PDF ;
- citation non sourcée ;
- résultat retrieval réel ;
- score vectoriel ;
- identifiant Qdrant ;
- contenu privé élève.

## 8. Conditions avant API/UI réelle

Avant toute API/UI réelle :

- endpoint réel loti séparément ;
- droits validés ;
- corpus validé ;
- retrieval réel validé ;
- citations testées ;
- refus contrôlés testés ;
- sécurité et journalisation définies ;
- revue humaine validée ;
- tests et doctors verts.

## 9. Cohérence du contrat déclaratif

Un contrat prêt pour revue exige :

- références 17C et 17D exactes ;
- personas requis présents ;
- interactions typées ;
- comportements attendus autorisés ;
- filtres metadata minimaux pour les interactions non-refus ;
- refus sans filtres exploitables ;
- aucune route, endpoint, méthode HTTP, serveur ou runtime UI ;
- aucune génération de réponse.

## 10. Politique stricte de citation et refus

Un contrat prêt pour revue exige :

- citations obligatoires ;
- source_trace_required ;
- aucune réponse sans source ;
- refus obligatoire sans source ;
- refus obligatoire pour document réel ;
- refus obligatoire pour droits inconnus ;
- aucune génération de réponse en cas de refus.
