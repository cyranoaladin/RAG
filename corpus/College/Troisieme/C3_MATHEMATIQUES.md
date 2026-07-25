# Mathématiques — Troisième

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_11_2018-07-26_aj_2020) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **troisieme** — collège — tronc commun.
- Horaire : 3 h 30/semaine (+ accompagnement personnalisé).
- Collection cible : `rag_nexus_maths_troisieme_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_11_2018-07-26_aj_2020)
- **Nombres et calculs** : Calcul littéral et identités remarquables, Factorisation et développement, Équations du premier degré et équations-produits, Puissances et notation scientifique, Arithmétique : diviseurs, PGCD, nombres premiers.
- **Fonctions** : Notion de fonction : image, antécédent, représentation, Fonctions linéaires et affines, Proportionnalité et pourcentages.
- **Espace et géométrie** : Théorème de Thalès et réciproque, Trigonométrie dans le triangle rectangle, Transformations : homothéties et rotations, Pyramides, cônes, sphères : sections et volumes.
- **Statistiques et probabilités** : Statistiques descriptives : moyenne, médiane, étendue, Probabilités : événements, arbres, expériences à deux épreuves.
- **Algorithmique et programmation** : Programmation par blocs (Scratch), Variables, boucles et conditionnelles.

## 3. Épreuves
### DNB (session 2026 — barème 800 points)
- **400 points de contrôle continu** (moyennes annuelles, compétences du socle) + **400 points d'épreuves finales**.
- Épreuves finales : français (100 pts, 3 h), mathématiques (100 pts, 2 h), histoire-géographie et EMC (50 pts, 2 h), sciences — SVT ou physique-chimie (50 pts, 1 h), soutenance orale (100 pts, 15 min).
- La session et le barème applicables sont déclarés par note de service annuelle (session_policy: declared_or_null — jamais devinés).

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Pour le DNB en candidat individuel, les 400 points de contrôle continu sont remplacés par des épreuves ponctuelles complémentaires. Voir `Referentiels/REF_DNB.md`.

## 5. Attendus / compétences évaluées
Compétences mobilisées : chercher, modéliser, représenter, raisonner, calculer, communiquer. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/maths/troisieme.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=troisieme`, `voie=college`, `matiere=maths`, `statut_enseignement=tronc_commun`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
