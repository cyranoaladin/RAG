# Droit et Économie — Première STMG

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_2_2020-02-13) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **premiere** — voie technologique STMG — spécialité.
- Horaire : 6 h/semaine (3 h droit + 3 h économie).
- Collection cible : `rag_nexus_droiteco_premiere_stmg_specialite` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_2_2020-02-13)
- **Droit** : Sources du droit et système juridique, Le contrat : formation et exécution, Responsabilité civile et pénale.
- **Économie** : Marché et concurrence, Monnaie et financement de l'économie, Régulation et intervention de l'État.

## 3. Épreuves
### Évaluations en première
- Matières du tronc commun : évaluations communes de contrôle continu (coefficients fixés par note de service de la session — declared_or_null).
- Tous les élèves passent l'**épreuve anticipée de mathématiques** (écrit 2 h, sans calculatrice, coefficient 2, sujet différencié selon la voie).
- Les spécialités conservées en terminale donnent lieu aux épreuves terminales ; une spécialité abandonnée est évaluée sur le programme de première.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : analyser, argumenter, mobiliser des références précises, rédiger avec rigueur. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/stmg/droiteco_premiere.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=premiere`, `voie=technologique`, `matiere=droit_economie`, `statut_enseignement=specialite`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
