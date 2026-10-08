# Lot — acceptation retrieval de l'union V4/V5

Statut : **suite préparée, exécution HTTP finale non encore effectuée**. Le jeu
[`final_v4_v5_acceptance.json`](../../services/rag-engine/tests/fixtures/final_v4_v5_acceptance.json)
fixe les questions et les seuils avant toute mesure de l'union publiée. Il est
lié par SHA-256 au registre mixte `59db12e8…da6af6`, au manifeste V4
`bab9c398…cda4be` et au manifeste HGGSP V5 `82863880…1daf`. Les sujets et
artefacts sont vérifiés par digest à l'exécution ; toute divergence refuse le
verdict. Le périmètre physique scellé est de **11 collections, 315 artefacts,
479 placements, 8 268 chunks distincts**. Les multi-placements donnent
**12 316 visites de chunks par scope** dans la sonde dense exhaustive : ce
second nombre ne doit pas être confondu avec la population physique.

Chaque collection porte trois questions étudiantes fixées ici : une factuelle,
une sans accents et une de notion. Chaque question déclare un `content_sha256`
attendu issu d'un document de programme officiel placé dans le sujet scellé.
L'acceptation HTTP vérifie chaque résultat (collection, contenu, chunk,
placement, revue, URI, page de citation et droits) avant de compter le rappel
de la source attendue. La page de citation doit égaler `page_start` du chunk
scellé ; `page_end` est vérifié dans l'oracle du manifeste, mais n'est pas un
champ exposé par le contrat HTTP actuel. Le libellé de source, absent du
manifeste, doit être non vide. Une réponse vide à une question positive échoue.

Pour chaque collection, la même requête hors corpus sur un filtre à huile de
tracteur exige une réponse HTTP 200 avec **zéro résultat**. Elle peut révéler
un défaut réel si le dense renvoie des voisins sans pertinence ; la suite ne
relâche pas ce critère après mesure. Les identités `student` sont actuellement
refusées en 403 car les 11 scopes gouvernés ont une visibilité `internal` ;
une requête avec un scope croisé doit également rendre 403. Ces refus ne sont
pas une preuve du futur parcours public étudiant : la future release publique
gouvernée devra re-sceller les manifests et réviser la suite explicitement.

Seuils fixés **avant mesure** : 33/33 questions positives non vides ; au moins
26/33 sources attendues dans les huit premiers résultats et 2/3 par
collection ; 11/11 réponses hors corpus vides ; 11/11 refus étudiant ; 11/11
refus de scope croisé ; zéro résultat hors scope ; zéro citation absente.
La sonde canonique `staging_retrieval_probe.py` doit couvrir les 11 scopes et
12 316 visites, et rapporter séparément chaque refus `dense ann tie overflow`
constaté à la source. Aucun ajustement du classement, du reranking, du nombre
de candidats ou des paramètres HNSW n'est inclus dans ce lot.

Exécution, **après** publication V5 74/74 et sonde dense finale, depuis le
checkout exact du SHA qualifié, avec les credentials opérateur déjà
provisionnés en environnement (jamais en argument ou dans le rapport) :

```bash
python scripts/go_live/final_retrieval_acceptance.py \
  --repository-root . \
  --api-url "$STAGING_API_URL" \
  --dense-probe-report "$DENSE_PROBE_REPORT" \
  --output "$QUALIFICATION_DIR/final-retrieval-acceptance.json"
```

Le programme rend 0 uniquement si le rapport vaut `verdict=pass`. Les 33
requêtes de la fixture peuvent être utilisées par C0 sans recopier ni changer
leurs textes ; l'émetteur JWT canonique partagé est
`rag_query.issue_scope_identity(scope_id, config=config, role="teacher")`.
L'API de transport est `rag_query_external.post_search`, avec trois
credentials distincts. Le rapport n'inclut aucun jeton ou secret.
Sur staging, le runner peut lire `COCKPIT_STAGING_API_KEY` si `RAG_API_KEY`
est absent. Dans l'image runtime dépourvue de Git, le SHA de checkout
précontrôlé sur l'hôte est transmis par `NEXUS_ACCEPTANCE_CHECKOUT_SHA` ; si
Git est présent, une divergence avec cette valeur bloque la recette.

Préparation vérifiée localement le 2026-10-08 sur `ee35544b` : 50 tests ciblés
de la suite, des clients HTTP et de l'émetteur étudiant, puis 5 tests de
refus `dense ann tie overflow`, ont réussi dans un venv propre lié à ce
worktree. Cette vérification synthétique ne vaut
pas mesure du staging final et ne produit pas `QUALITY_PASS=true`.
