# LOT42 — proposition agrégée du successeur public A2

## Périmètre et statut

Branche issue de `origin/main` `902e9d5c95d2d369f41a18324fa05038913499b4`
(tree `cd12328851b5322de4758a40e6ffdfe4aa636589`). Ce lot prépare la
revue batch des 253 dérivés textuels et 377 placements de la release A2.
Il n'enregistre aucune attestation dans la cible réelle, ne lance aucun worker
et ne constitue ni autorité de publication ni preuve de qualité retrieval.

Le mode `propose-public-successor-release-batch-review` relit l'ancre de
contenu, A2, les sidecars droits/PII/actualité, les 253 descriptions de
chunks, le plan et les reçus de transfert V1/V2. Il ouvre ensuite **une
transaction PostgreSQL read-only**, recoupe le nom de DB et son
`system_identifier` avec le pin, mesure les 377 lignes de contrôle et leurs
identités de placement, rejoue chacune des 11 autorisations LOT41A-V2 et
vérifie la bijection complète avec le manifeste. Il produit 377 projections
en mémoire ; aucune projection ni attestation n'est écrite. Le reçu LOT42
canonique lie A2, le plan de transfert, le digest agrégé des projections et
l'identité de l'évaluateur dans sa provenance versionnée.

Le mode `record-public-successor-release-batch-attestation` est réservé à
l'après-review. Il vérifie d'abord la review GitHub au **HEAD exact** et son
challenge, puis relit le blob canonique approuvé depuis ce HEAD. Une
transaction `SERIALIZABLE` rejoue intégralement les mêmes sources, le pin,
les 11 autorisations et les 377 faits DB. Le reçu est reconstruit octet à
octet, y compris le digest des projections ; l'actualité A2 et la fenêtre
de revue sont revérifiées. Si tout concorde, les projections et les
attestations sont insérées dans **la même transaction**, puis committées
ensemble. Tout conflit d'attestation après projection déclenche un rollback.
Les lignes existantes de même digest restent idempotentes ; celles d'un autre
digest sont refusées.

## Préconditions opérateur

1. Préflight cible isolée, pin et transfert V1/V2 qualifiés ; ne pas utiliser
   l'ancien staging V4/V5 ni la production historique.
2. Rejouer `services/rag-engine/infra/scripts/provision_ingestion_control_roles.sh`
   **sur cette DB publique isolée seulement** : le rôle attestor doit pouvoir
   exécuter `pg_catalog.pg_control_system()` pour vérifier le pin. Le grant ne
   lui ajoute aucun droit d'écriture sur les ressources ou autorisations.
3. Utiliser un checkout propre au SHA approuvé et son environnement Python
   isolé. Fournir les chemins A1/A2, release, plan, reçu V1, pin et
   attestation V2 exacts, leurs SHA attendus, `review-id` et `evaluator`.
4. Commiter le reçu JSON canonique au chemin que la proposition imprime dans
   la PR de revue. Garder cette PR **OPEN et son HEAD figé** jusqu'à la review
   APPROVED exacte et à l'enregistrement. Ne pas confondre proposition et
   attestation active.
5. Après le statut trusted-human-review vert, invoquer le mode `record-...`
   avec ce chemin, `repository`, numéro de PR et HEAD exact. Recontrôler les
   377 attestations actives avant Worker B et le signer C. Ne fusionner la PR
   qu'au point prévu par le protocole du reçu historique post-merge.

## Vérification locale

- Suite ciblée : 20 tests verts sur le worktree ; 100 tests adjacents verts
  au total, dont divergences de
  population, scope, chunk count, A2 expirée, projection altérée, rollback
  après conflit, lecture réelle des 253 sidecars.
- Ruff et `git diff --check` verts.
- Un PostgreSQL Docker jetable, provisionné par les vrais scripts, a permis
  à l'attestor de lire `pg_control_system()` tout en confirmant l'absence de
  droits `INSERT` sur `resources` et `UPDATE` sur `scope_authorizations`.
  La même assertion figure dans la suite d'intégration des rôles ; son
  invocation pytest complète reste à effectuer dans l'environnement CI
  (le conftest général importe des dépendances hors du venv minimal de ce lot).
- Aucune proposition n'a été exécutée contre la DB publique réelle ; aucun
  reçu final, aucune review et aucune attestation active ne sont revendiqués.

Le typage ciblé ne montre aucune erreur nouvelle dans le module public. Le
`mypy` global signale encore des erreurs préexistantes dans les contrats,
`public_successor_activation.py` et des constantes non typées des modules
historiques. Ce lot ne les masque pas.
