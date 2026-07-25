# SNT — Seconde

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_1_2019-01-22) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **seconde** — voie générale — SNT.
- Horaire : 1 h 30/semaine.
- Collection cible : `rag_nexus_snt_seconde_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_1_2019-01-22)
- **Le monde numérique** : Internet : architecture et protocoles, Le Web : HTTP, HTML, liens, Les réseaux sociaux.
- **Les données** : Données structurées et traitement, Localisation, cartographie et mobilité.
- **Objets connectés et images** : Objets connectés et informatique embarquée, La photographie numérique.

## 3. Épreuves
### Pas d'examen national en seconde
- Évaluation en contrôle continu ; la classe de seconde prépare le choix des **3 enseignements de spécialité** de première (voie générale) ou de la série technologique.
- Les moyennes de seconde alimentent le contrôle continu du baccalauréat.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : chercher, modéliser, représenter, raisonner, calculer, communiquer. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/snt/seconde.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=seconde`, `voie=generale`, `matiere=snt`, `statut_enseignement=snt`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
