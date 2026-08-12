# Spécialité Mathématiques — Première

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel 2026 (`BOEN_14_2026-04-02_MENE2602917A`) ;
> éduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **premiere** — voie générale — spécialité.
- Horaire : 4 h/semaine.
- Collection cible : `rag_nexus_maths_premiere_gen_specialite` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (`BOEN_14_2026-04-02_MENE2602917A`)
- **Algèbre** : Suites numériques : modes de génération et variations, Second degré : forme canonique, équations, signe, Manipulations algébriques et dénombrement introductif.
- **Analyse** : Dérivation : nombre dérivé, fonction dérivée, Variations et courbes représentatives, La fonction exponentielle, Fonctions trigonométriques.
- **Géométrie** : Calcul vectoriel et colinéarité, Produit scalaire et applications, Géométrie repérée : droites et cercles.
- **Probabilités et statistiques** : Probabilités conditionnelles et indépendance, Variables aléatoires et espérance, La loi binomiale.
- **Algorithmique et programmation** : Python en appui des autres domaines.

## 3. Épreuves
### Évaluations en première
- Matières du tronc commun : évaluations communes de contrôle continu (coefficients fixés par note de service de la session — declared_or_null).
- Tous les élèves passent l'**épreuve anticipée de mathématiques** (écrit 2 h, sans calculatrice, coefficient 2, sujet différencié selon la voie).
- Les spécialités conservées en terminale donnent lieu aux épreuves terminales ; une spécialité abandonnée est évaluée sur le programme de première.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : chercher, modéliser, représenter, raisonner, calculer, communiquer. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/maths/premiere_gen_specialite.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=premiere`, `voie=generale`, `matiere=maths`, `statut_enseignement=specialite`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
