# LOT42 — proposition agrégée du successeur public A2

## Périmètre et statut

Branche issue de `origin/main` `902e9d5c95d2d369f41a18324fa05038913499b4`
(tree `cd12328851b5322de4758a40e6ffdfe4aa636589`). Ce lot prépare la
revue batch des 253 dérivés textuels et 377 placements de la release A2.
Il n'enregistre aucune attestation dans la cible réelle, ne lance aucun worker
et ne constitue ni autorité de publication ni preuve de qualité retrieval.

Le mode `propose-public-successor-release-batch-review` relit l'ancre de
contenu, A2, les sidecars droits/PII/actualité, les 253 descriptions de
chunks, le plan et les reçus de transfert V1/V2. Il exige le digest V2 et
rejoue le vérificateur canonique de cible qualifiée depuis l'hôte opérateur :
machine, PostgreSQL, pin, chemin, inode, 253 textes et leurs reçus sont
recontrôlés. La sonde indépendante du pin observe aussi le conteneur Docker
vivant à travers `/var/run/docker.sock` et lie le socket PostgreSQL connecté
au port publié par **ce même conteneur**, puis compare l'observation complète
au pin. Il ouvre ensuite **une transaction PostgreSQL read-only**,
recoupe le nom de DB et son `system_identifier` avec le pin, mesure les 377
lignes de contrôle, leurs identités de placement et les dix dimensions de
scope persistées, dont `visibility` et `audience`. Chacune des 11
autorisations LOT41A-V2 doit retrouver exactement le profil scellé A2,
`rights_categories=[public_allowed]` et le scope de chaque ressource.
Il produit 377 projections en mémoire ; aucune projection ni attestation
n'est écrite. Le reçu LOT42 canonique lie A2, le plan de transfert, le pin,
la V2, le digest agrégé des projections et l'identité de l'évaluateur dans
sa provenance versionnée.

Le mode `record-public-successor-release-batch-attestation` est réservé à
l'après-review. Il vérifie d'abord la review GitHub au **HEAD exact** et son
challenge, exige `trusted-human-review/head-pinned=success`, puis relit le
blob canonique approuvé depuis ce HEAD. Une
transaction `SERIALIZABLE` rejoue intégralement les mêmes sources, le pin,
les 11 autorisations et les 377 faits DB. Le reçu est reconstruit octet à
octet, y compris le digest des projections ; l'actualité A2 et la fenêtre
de revue sont revérifiées. Si tout concorde, les projections et les
attestations sont insérées dans **la même transaction**, puis committées
ensemble. Tout conflit d'attestation après projection déclenche un rollback.
Les attestations écrivent les `profile_id`, `profile_version`,
`profile_fingerprint` et `manifest_digest` exacts des autorisations A2,
jamais ceux de l'ancienne release V4/V5. La review exacte et le statut requis
sont relus juste avant le commit ; A2, le pin vivant, les 253 fichiers/reçus
et les fenêtres temporelles A2/review sont rejoués une seconde fois à cet
instant. Toute divergence annule la transaction.
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
   isolé, **sur l'hôte de qualification qui voit le répertoire de destination
   réel**. Fournir les chemins ancre/A2, release, plan, reçu V1, pin et
   attestation V2 exacts, `--destination-root` absolu, leurs SHA attendus
   (dont `--target-pin-sha256` et `--transfer-v2-sha256`), `review-id` et
   `evaluator`. `PG_INGESTION_CONTROL_ATTESTOR_DSN` doit viser la DB isolée
   du pin via un port TCP loopback explicite publié par le conteneur Docker.
   L'hôte opérateur doit avoir accès en lecture à son socket Docker local et
   au répertoire de destination ; si ces accès manquent, la sonde refuse.
   Le runtime
   ne monte pas le dépôt ; ces CLI se lancent depuis le checkout opérateur
   propre, sans bind mount du dépôt en production.
4. Commiter le reçu JSON canonique au chemin que la proposition imprime dans
   la PR de revue. Garder cette PR **OPEN et son HEAD figé** jusqu'à la review
   APPROVED exacte et à l'enregistrement. Ne pas confondre proposition et
   attestation active.
5. Après le statut trusted-human-review vert, invoquer le mode `record-...`
   avec ce chemin, `repository`, numéro de PR et HEAD exact. Recontrôler les
   377 attestations actives avant Worker B et le signer C. Ne fusionner la PR
   qu'au point prévu par le protocole du reçu historique post-merge.

## Vérification locale

- Suite ciblée : 23 tests verts sur le worktree ; 80 tests adjacents verts
  au total, dont divergences de population, scope DB `internal`, catégorie
  de droits non publique, chunk count, A2 expirée, projection altérée,
  statut GitHub requis rouge, review changée avant commit, A2 ou fenêtre de
  revue expirée avant commit, conteneur vivant différent du pin, rollback
  après conflit et lecture réelle des 253 sidecars.
- Ruff et `git diff --check` verts.
- Un PostgreSQL Docker jetable, provisionné par les vrais scripts, a permis
  à l'attestor de lire `pg_control_system()` tout en confirmant l'absence de
  droits `INSERT` sur `resources` et `UPDATE` sur `scope_authorizations`.
  La même assertion figure dans la suite d'intégration des rôles ; son
  invocation pytest complète reste à effectuer dans l'environnement CI
  (le conftest général importe des dépendances hors du venv minimal de ce lot).
- La vérification complète de la cible par le contrôleur canonique est
  déléguée et testée en isolation ; l'hôte de qualification et ses 253
  fichiers ne sont pas accessibles depuis ce worktree de développement.
  Aucune proposition n'a été exécutée contre la DB publique réelle ; aucun
  reçu final, aucune review et aucune attestation active ne sont revendiqués.

Le typage complet n'est pas revendiqué vert : le venv isolé minimal ne
présente pas les packages locaux comme packages typés à mypy, et son essai
`--follow-imports=silent` signale 25 imports non typés/introuvables. Cette
commande ne constitue pas une validation du typage du lot. Les suites pytest,
Ruff et le contrôle de diff ci-dessus sont les validations locales obtenues.
