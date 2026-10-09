# Lot 310 — liaison de provenance publique à la readiness signée

## Base et périmètre

- Date : 2026-10-09.
- **LIVE** au fetch du 2026-10-09 : `origin/main`
  `59da01c9821cbbff8b12194394d232dc33ecf149`, arbre
  `5579d74cb69831bf660fd8ef99a0909b2e5d57d5` ; #309 y est fusionnée.
- **SEALED** : les trois commits du lot ont été rejoués sans conflit dans un
  nouveau worktree propre depuis cette base. Venv Python 3.12 neuf ;
  `nexus-contracts` installé depuis ce checkout en mode non éditable
  (`.venv/site-packages`).
- Aucun accès en écriture à staging/production ; aucune clé opérateur utilisée,
  aucune image construite/poussée et aucune signature opérateur émise.

## Résultat technique

Le contrat `nexus-contracts` 0.23.0 ajoute à la readiness V2 trois champs
optionnels indivisibles : digest SHA-256 des octets JSON canoniques de
l'inventaire public, identifiant et tentative du run de provenance. Leur
présence impose exactement les quatre images applicatives, dont Cockpit, leurs
dépôts canoniques et une référence worker identique. Leur absence conserve les
octets et signatures historiques V2. Le protocole V1 reste inchangé.

Le signer opt-in `--public-candidate` dérive la carte d'images et le digest
uniquement de l'artefact V2 validé par le vérificateur canonique du lot 308.
Le checker du bundle confronte le manifeste signé à l'inventaire vérifié puis
aux octets matérialisés. Le signer exige exactement les cinq
services publics (`pgvector`, `ingestor`, `prometheus`, `session-redis`,
`cockpit`), compare les deux images exécutées (`ingestor`, `cockpit`) et garde
les quatre images dans la readiness signée. Un writer ou worker actif est
refusé. Les chemins historiques à trois services restent le défaut. Le chemin
public matérialise uniquement un plan ; `--execute` y est refusé.

## Raccord au Compose public fusionné

- `--public-candidate` du signer résout exclusivement
  `docker-compose.v2.yml` avec `docker-compose.public-blue-green.yml` depuis
  les objets Git du commit attesté. La voie V1 conserve ses trois fichiers.
- Le vérificateur prend l'inventaire V2 canonique des quatre images, impose
  exactement les cinq services publics et confronte seulement les deux images
  exécutées (`ingestor`, `cockpit`) au Compose. Le wrapper matérialise ces
  deux sources et les octets canoniques exacts de l'inventaire V2, puis relit le Compose effectif
  avant de rendre un plan. Un manifeste V2 historique sans digest public est
  refusé dans le plan public et avant écriture du bundle.
- Le bundle public porte explicitement son mode et sa liste exacte de deux
  fichiers ; l'exécution est toujours refusée. Son résultat plan-only n'émet
  aucune commande `pull`/`up` copiable et la sortie JSON porte
  `mutation_allowed=false`, `cutover_gate_required=true`. Aucun `pull`, `up`
  ou accès à la production n'a été lancé. Le préflight public du lot 309 reste la
  preuve de topologie, de matériaux et de secrets host-local ; ce lot lie
  la signature, la provenance et le bundle.
- Le bundle est créé à `0700` sous un parent préexistant, de confiance et
  sans symlink ; ses sous-dossiers sont à `0700`, tous ses fichiers à `0600`
  par écriture atomique privée. La voie V1 reçoit la même protection sans
  changement de ses octets ni de son protocole. Un parent absent ou ouvert en
  écriture groupe/monde est refusé avant écriture ; l'opérateur doit préparer
  le parent privé. Les copies `.env` et `resolved-compose.json` peuvent
  contenir des secrets de session et d'identité.

## Qualification locale sur la base fusionnée

- **SEALED** sur le HEAD de code candidat `e92065ad2601ebaa5e1669520fba022b9acb1a57` :
  `pytest -q` sur le contrat readiness et les six suites
  `rag-engine` ciblées (inventaire, vérificateur, signer, wrapper,
  préflight public, plan signé) et l'export de schéma : **418 passed**.
- `ruff check` sur les douze fichiers Python touchés : **0 erreur** ;
  `git diff --check` : **0 erreur**.
- La recette officielle `make typecheck` (sans réinstallation, via
  `make -o install-dev typecheck`) : **5 erreurs identiques sur 149 fichiers**
  sur la base et ce lot. `mypy` 1.11.2 ciblé sur les quatre scripts de
  gouvernance : **41 erreurs identiques** sur la base et ce lot après
  normalisation des lignes. Aucun contrôle mypy n'est déclaré vert ;
  antériorité et diagnostics dans
  [lot_310_typecheck_dettes.md](lot_310_typecheck_dettes.md).
- Tests unitaires et intégration synthétique : signature V2, provenance V2
  canonique à quatre images, bundle et relecture à deux fichiers, plan-only,
  refus `execute=True`, ancien V2, divergence du Compose effectif, du mode de
  bundle et des octets de l'inventaire même si le bundle est rehashé ; tests
  de permissions sous umask `000`, destination symlink et parent dangereux. Les
  chemins V1 restent couverts par leurs tests existants.
- `docker compose config` réel (Compose 5.6.0) depuis les objets Git du HEAD
  candidat `e92065ad2601ebaa5e1669520fba022b9acb1a57`, avec variables
  et matériaux fictifs isolés : cinq services exacts, aucun `build` pour
  l'API ou le Cockpit. Aucun conteneur n'a été démarré.
- Les tests du préflight public #309 contre le Compose réel sont passés dans
  la suite ciblée. Les preuves ci-dessus ne décrivent ni le staging final,
  ni la cible production, ni une signature opérateur.

Le passage aux preuves live demandera un inventaire V2 réellement publié pour
le SHA final, une signature opérateur hors ligne, la revue humaine du HEAD de
la PR et la qualification staging/production distincte. Aucun verdict
`GO_LIVE_READY` ni digest final n'est produit ici.
