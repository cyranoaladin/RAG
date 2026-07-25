# Histoire-Géographie-EMC — Troisième

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_11_2018-07-26_aj_2020) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **troisieme** — collège — tronc commun.
- Horaire : 3 h/semaine (histoire-géographie) + 0,5 h (EMC, environ 18 h/an).
- Collection cible : `rag_nexus_hg_troisieme_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_11_2018-07-26_aj_2020)
- **Histoire** : Le monde de 1914 à 1945 : guerres et totalitarismes, Le monde depuis 1945 : guerre froide, décolonisation, Ve République, La France, l'Union européenne et le monde.
- **Géographie** : Habiter les métropoles, Habiter les espaces de faible densité, Habiter l'outre-mer.
- **Enseignement moral et civique** : Droits et devoirs du citoyen, La justice et le droit, L'État de droit et la démocratie.

## 3. Épreuves
### DNB (session 2026 — barème 800 points)
- **400 points de contrôle continu** (moyennes annuelles, compétences du socle) + **400 points d'épreuves finales**.
- Épreuves finales : français (100 pts, 3 h), mathématiques (100 pts, 2 h), histoire-géographie et EMC (50 pts, 2 h), sciences — SVT ou physique-chimie (50 pts, 1 h), soutenance orale (100 pts, 15 min).
- La session et le barème applicables sont déclarés par note de service annuelle (session_policy: declared_or_null — jamais devinés).

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Pour le DNB en candidat individuel, les 400 points de contrôle continu sont remplacés par des épreuves ponctuelles complémentaires. Voir `Referentiels/REF_DNB.md`.

## 5. Attendus / compétences évaluées
Compétences mobilisées : analyser, argumenter, mobiliser des références précises, rédiger avec rigueur. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/histoire_geo/troisieme.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=troisieme`, `voie=college`, `matiere=hg`, `statut_enseignement=tronc_commun`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
