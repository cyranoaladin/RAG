# Enseignement scientifique — Première

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_1_2019-01-22) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **premiere** — voie générale — enseignement scientifique.
- Horaire : 2 h/semaine.
- Collection cible : `rag_nexus_es_premiere_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_1_2019-01-22)
- **Une longue histoire de la matière** : Les éléments chimiques dans l'Univers, La structure de la Terre et l'histoire de son âge.
- **La Terre, la vie et l'organisation du vivant** : La biodiversité et son évolution, L'organisation du vivant et sa complexité.
- **Les enjeux contemporains de la planète** : Ressources naturelles et utilisation, Climat, énergie et activités humaines.
- **Le son, une musique à entendre** : Physique du son et perception, Le son porteur d'information.

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
- Taxonomie : `services/rag-pedago/taxonomy/enseignement_scientifique/premiere.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=premiere`, `voie=generale`, `matiere=es`, `statut_enseignement=enseignement_scientifique`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
