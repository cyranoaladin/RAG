# ADR-0067 — Déployer le candidat public signé dans une couleur isolée

- **Statut** : proposé ; accepté seulement après revue du HEAD exact et fusion.
- **Date** : 2026-10-09.
- **S'appuie sur** : ADR-0066, le Compose public du lot 309 et le wrapper atomique existant.
- **Contrat** : aucun changement de `nexus-contracts`.

## Problème

Le lot 310 produit un bundle public V2 privé et vérifié mais refuse toujours
`--execute`. La voie V1 du wrapper exécute `pull`/`up` dans l'ancien projet et
ne peut pas servir de cutover blue-green. Un `compose up` manuel depuis un
checkout rouvrirait la divergence entre la preuve signée et le runtime.

## Décision

La voie publique conserve `plan-only` par défaut. Une exécution demande
simultanément `--execute`, `--final-cutover-go`, la readiness V2 signée et
vérifiée, l'inventaire V2 lié à la signature, le bundle intact, et un passage
frais de `check_go_live_readiness.py --assert-ready` sur un checkout propre au
SHA signé. Le GO est une saisie opérateur après l'autorisation humaine du
cutover ; le drapeau ne constitue pas, seul, une preuve de cette autorisation.

Avant `pull`, le préflight public valide les cinq services exacts, les deux
images applicatives et trois images amont par digest, les matériaux et secrets
hors Git, les montages en lecture seule, le projet/couleur
`nexus-rag-blue|green` et l'absence de toute ressource préexistante dans ce
projet. Le projet renvoyé par le préflight est confronté à la couleur choisie.
Après `pull`, signature, bundle, matériaux, readiness et inventaire du projet
sont revérifiés avant `up -d --no-build --pull never --wait --wait-timeout 300`
sur les cinq services explicites. Aucun worker, writer ou endpoint d'ingestion
n'est ajouté. `--remove-orphans` et le projet historique `infra` sont absents.

Si `up` échoue ou expire, le wrapper lance `down --timeout 10` uniquement pour
la couleur candidate et signale séparément un éventuel échec de rollback. Un
mode rollback explicite relit le bundle et le Compose avant ce même `down`,
sans effacer les volumes. Ce rollback reste accessible même si le garde
readiness devient rouge après le lancement. Aucun routage Nginx ni ancien
projet n'est changé par ce lot : le switch et son rollback sont une opération
de cutover distincte, après preuve de santé et GO final.

La voie V1, ses commandes et son protocole restent inchangés.
