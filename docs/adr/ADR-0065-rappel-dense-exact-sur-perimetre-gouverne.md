# ADR-0065 — Rappel dense exact sur le périmètre gouverné

- **Statut** : proposé ; devient accepté après revue du HEAD exact et fusion.
- **Date** : 2026-10-08.
- **S'appuie sur** : ADR-0001, ADR-0055, ADR-0060, ADR-0062 et ADR-0063.
- **Contrat** : aucune modification de `nexus-contracts`.

## Fait déclencheur

Sur le staging mixte V4 + HGGSP V5, l'image de retrieval épinglée interroge
8 268 chunks physiques sous onze scopes gouvernés. La sonde du checkout
`6f33805601bdd04b9b10b3ae75febf01c63773e2` a relevé 12 manques sur
12 316 visites chunk–scope et sept refus distincts `dense ann tie overflow`.
Les 12 manques représentent huit chunks physiques : quatre DGEMC, un HGGSP
servi sous deux scopes, un HLP sous deux scopes et deux NSI sous deux scopes.
Pour chacune des 12 visites, la requête par le vecteur stocké donne une
distance exacte nulle et le même SQL, évalué sans index ANN, place ce chunk
au rang un. L'index HNSW global (`m=16`, `ef_construction=64`) l'omet du top 5
avec `hnsw.ef_search=40`, même en `strict_order`. La JSON diagnostique
`retrieval-probe-mixed-diagnostic-6f338056.json` porte l'empreinte SHA-256
`246814ea1b8899f0a9aed57a16a50724c388cf97c7ad5e371eceac00cea6e1c5`.
Ce diagnostic n'est pas une qualification finale.

## Décision

Pour le canal dense v2, établir **d'abord** l'ensemble des chunks autorisés
par le scope serveur : dimensions, rôle/visibilité, droits de l'artefact,
placement actif, actualité, revue et provenance. Un chunk gouverné peut être
placé sous plusieurs collections ; sa colonne `rag_chunks.collection` ne
constitue pas l'autorité d'accès. Calculer ensuite la distance cosinus exacte
sur cet ensemble matérialisé, prendre au plus 201 candidats, puis conserver
la projection de citation, l'ordre stable dans le pool, la limite 200 et le
diagnostic à la frontière 200/201 existants.

Le parcours normal n'emploie pas l'index HNSW pour choisir ce préfixe. Il ne
désactive pas globalement ou par requête `enable_indexscan` : les index B-tree
de placement et d'`artifact_id` restent utilisables. Aucun index, table,
migration, droit, seuil ni dimension de scope n'est ajouté par cette décision.
Le canal lexical et le contrat API restent inchangés.

Les sept refus d'égalité restent observables. Un ordre total exact pourrait
permettre une autre décision sur les égalités, mais elle requiert un ADR
distinct et ne fait pas partie de ce correctif. Ni un résultat top 5 rempli
ni une augmentation de `ef_search` ne prouvent le rappel : le top 5 était
rempli dans les douze échecs.

## Alternatives écartées

- Augmenter `ef_search`, `max_scan_tuples`, `scan_mem_multiplier` ou rebâtir
  l'index améliore possiblement le rappel de cet index, sans garantie exacte
  sur les releases futures. Le test ponctuel à `ef_search=100` a réparé une
  seule visite DGEMC ; il ne valide pas les onze scopes.
- Un HNSW partiel sur la collection physique ne représente pas les placements
  gouvernés multi-collections. Une table vectorielle par placement ajouterait
  une seconde projection à maintenir et un nouveau chemin de publication.
- Un fallback exact conditionné à un top 5 vide ou incomplet ne détecte pas
  les échecs observés, qui renvoient cinq candidats plausibles.
- `SET LOCAL enable_indexscan=off` prouve la cause sur un cas mais retire
  aussi les index B-tree utiles. Un `EXPLAIN ANALYZE` diagnostique a mesuré
  environ 1,5 s pour cette forme brute sur DGEMC ; elle n'est pas la forme
  retenue pour le runtime.

## Preuves exigées avant activation

1. Tests PostgreSQL réels : ensemble autorisé exact, refus hors scope,
   droits/revue/actualité/visibilité, citations complètes, multi-placement,
   limite 201 et refus d'égalité conservé. Un plan d'exécution vérifie que
   le tri par distance suit la matérialisation du jeu gouverné et qu'aucun
   HNSW ne sélectionne le préfixe.
2. Sonde finale sur le staging final : onze scopes, 12 316 visites attendues
   tant que les manifests restent ceux-ci, zéro manque dense, aucun candidat
   hors scope. Les refus d'égalité sont rapportés séparément et ne sont pas
   convertis en succès silencieux.
3. Golden finale, liée aux manifests et à l'image servis, couvrant les onze
   collections, les accents, frontières, rôles et citations. Aucun seuil
   n'est relevé après la mesure.
4. C0 sur la vraie cible de qualification : huit clients, 240 requêtes,
   p50 ≤ 3 000 ms, p95 ≤ 6 000 ms, p99 ≤ 7 500 ms, zéro erreur/timeout et
   au plus dix connexions DB. Le temps du tri exact est un risque mesuré,
   pas une raison de relâcher le budget.

La fusion du code n'établit ni `QUALITY_PASS` ni `LOAD_PASS`. Les images et
les preuves finales doivent être reconstruites et rejouées au SHA final.
