# ADR-0066 — Lier la readiness signée à l'inventaire des images publiques

- **Statut** : proposé ; devient accepté après revue du HEAD exact et fusion.
- **Date** : 2026-10-09.
- **S'appuie sur** : ADR-0001, ADR-0036 et la provenance publique V2 du lot 308.
- **Contrat** : `nexus-contracts` 0.22.0 → 0.23.0, extension additive de `ProductionReadinessManifestV2`.

## Fait déclencheur

Le workflow de provenance sait produire un inventaire V2 contenant exactement
`ingestor`, les deux références du même worker et `cockpit`. Le signer de
readiness et le wrapper de déploiement n'en consommaient que la voie V1 à trois
services. Une signature de la seule carte d'images ne désignait pas les octets
de l'inventaire public ni la tentative de run qui les a publiés.

## Décision

1. La voie publique est sélectionnée explicitement par `--public-candidate`.
   Le signer relit le run GitHub Actions réussi sur le commit et l'arbre de
   `main`, télécharge l'artefact V2 distinct, vérifie ses quatre services et
   ses octets JSON canoniques, puis calcule son SHA-256. Aucun digest
   applicatif fourni librement par l'opérateur n'est accepté.
2. La readiness V2 signe ensemble `public_candidate_inventory_digest`,
   `public_candidate_provenance_run_id` et
   `public_candidate_provenance_run_attempt`. Les trois champs sont absents
   ensemble dans la voie historique. Leur présence exige les quatre images
   exactes, leurs dépôts canoniques et une référence worker identique.
3. Le Compose public contient exactement `pgvector`, `ingestor`, `prometheus`,
   `session-redis` et `cockpit`. Les quatre images applicatives sont attestées,
   mais seules `ingestor` et `cockpit` sont des images exécutées par cette pile.
   Le signer compare ce sous-ensemble exact à la provenance et refuse un
   service `writer`, un worker démarré ou tout service additionnel.
4. Le checker confronte l'inventaire vérifié au manifeste signé : protocole,
   dépôt, commit, arbre, run, tentative, digest canonique et carte des quatre
   images. La même confrontation est répétée sur l'inventaire matérialisé dans
   le bundle. Le mode public matérialise les deux fichiers Compose de la pile
   blue-green depuis les objets Git du commit attesté et revérifie leur
   résolution contre le digest signé. Il ne produit qu'un plan : `--execute`
   est refusé même si toutes les preuves passent.
5. Les octets canoniques des manifests V2 existants, sans ces champs,
   restent identiques ; la voie V1 garde son protocole et ses trois services.
   Aucun nouveau type de clé ni aucune signature automatique n'est ajouté.

## Limite et dépendance

La pile publique du lot 309 est requise au commit signé ; un commit sans ses
deux fichiers Compose ne peut pas être matérialisé. Cette décision ne constitue
ni un build d'image, ni une preuve de staging, ni une autorisation de production.
Le cutover blue-green suit un protocole et un gate distincts. Les workers
peuvent être attestés par le même inventaire sans être démarrés dans la pile
de recherche publique.
