# Lot 1 — Rotation atomique de l'ancre review-binding

## Verdict du lot

`IMPLEMENTED_UNVERIFIED`

La rotation technique, la sauvegarde chiffrée et la restauration sont
effectives. L'ancre ne deviendra une autorité gouvernée utilisable qu'après
merge de la PR sur `main`, précédé d'une trusted-human-review liée au HEAD
exact. Aucune autorisation réelle ni aucun reçu gouverné utilisable en
production n'a été signé dans ce lot.

## Référence

- Base : `3566cafb44138d6a7f00296dc0654257f9bf0ad6`.
- Branche : `ops/review-binding-rotation-20260825`.
- Commit de remplacement :
  `6d19cf93ca199ce718b3c041ead75f5b1f1d08a8`.
- Décision : remplacement atomique, sans période de chevauchement.
- Registre `authorization-revocations-v1.json` : inchangé ; il révoque les
  autorisations de corpus et non les clés de signature.

## Ancre retirée

- Identifiant : `review-binding-v1-2026-08-13`.
- Clé publique historique :
  `bae8268bc4192be5fd382db70d1b1036cfc7fb58b2cfc42b21a64cd6292b0d4f`.
- Statut : `LOST_BEFORE_FIRST_USE`.
- Reçus réels à préserver : zéro.
- Confiance future : aucune.

L'ancienne empreinte n'existe plus dans l'ancre active. Elle est conservée
uniquement comme fait historique dans ADR-0035 et ce rapport.

## Nouvelle ancre

- Identifiant : `review-binding-v1-2026-08-25`.
- Algorithme : `ed25519`.
- Environnement : `production`.
- Clé publique :
  `1f34648789fe7ebdfde6c64197039c0ffa0cd36b98317ce7cad4836a26a058d8`.
- SHA-256 des 32 octets publics :
  `b85fff9e9bbbf9295886e46fb47e53a8c2f7e0e67e3c7900bdfc1952770e6313`.
- Entrées actives dans l'ancre gouvernée : une.

La graine Raw privée a été générée hors dépôt avec création exclusive. Le
répertoire primaire est `0700`, le fichier privé `0600` et l'export public
`0644`. La matière privée n'est ni versionnée, ni passée en argument, ni
installée dans CI, sur le serveur ou dans un artefact de build.

## Sauvegarde et restauration

- Date de l'évidence : `2026-08-25T18:25:02.347723Z`.
- Support : montage distinct du système, sous-répertoire opérateur `0700`.
- Format : GPG symétrique AES-256 avec S2K SHA-512 et phrase saisie dans
  `pinentry` ; aucune phrase dans Git, l'environnement ou les arguments.
- Ciphertext : fichier régulier `0600`, non vide.
- SHA-256 du ciphertext :
  `dde1f2d6d95b095c90e21f289168c350c71da57afdd45e7aa858114ad64068cf`.
- Checksum relu : concordant.
- Objets conservés sur le support : trois — ciphertext, checksum et évidence
  publique assainie.
- Copie privée en clair sur le support : aucune.
- Restauration : GPG vers un répertoire temporaire `0700`, privé restauré
  `0600`.
- Public primaire = public restauré = ancre gouvernée : vrai.
- Nonce signé avec la restauration puis vérifié par l'ancre : vrai.
- Répertoire de restauration et répertoire de travail GPG : supprimés.
- Écritures durables : ciphertext, checksum et évidence relus, `fsync` des
  fichiers puis du répertoire avant succès.

Le script opérateur utilisé est hors Git, en `0700`. Il refuse
`PYTHONOPTIMIZE`, les symlinks, les permissions divergentes, les sorties
préexistantes et les exécutions concurrentes. La publication des trois objets
est sans écrasement et son rollback compare les identités device/inode.

## Tests cryptographiques

1. Le public dérivé du primaire correspond exactement à l'ancre.
2. Un nonce aléatoire a été signé puis vérifié localement ; nonce et signature
   ont été détruits sans être affichés.
3. Le producteur canonique `_issue_binding` a été exécuté une fois avec la
   vraie clé sur une autorisation LOT41A-V2 factice et jetable. Cette exécution
   a créé en mémoire un reçu synthétique au format `production` : il n'a jamais
   été persisté, publié ou lié à une review GitHub réelle. Cette déviation au
   libellé « aucun reçu de production » est explicitement consignée et le test
   futur utilise exclusivement la fixture `environment=test`.
4. Le reçu synthétique a passé `verify_review_binding` en environnement
   `production`, `require_challenge_is_bound` et
   `require_matches_authorization`.
5. `NEXUS_REVIEW_BINDING_SIGNING_KEY` a été supprimée du processus en
   `finally`.

Résultats :

- `PRIMARY_ANCHOR_PUBLIC_MATCH=true` ;
- `NONCE_SIGNATURE_VERIFIED=true` ;
- `FAKE_PRODUCER_ROUNDTRIP_VERIFIED=true` ;
- `FAKE_AUTHORIZATION_BINDING_VERIFIED=true` ;
- `SIGNING_ENV_CLEARED=true` ;
- round-trip producteur de remplacement avec fixture
  `environment=test` : `1 passed` ;
- `BACKUP_CHECKSUM_VERIFIED=true` ;
- `RESTORE_REHEARSAL_PASS=true`.

Aucune autorisation réelle, aucun review-binding gouverné persistant et aucune
recette de production n'ont été signés. La signature synthétique ne constitue
aucune autorité, mais son émission ponctuelle ne doit pas être répétée.

## TDD et contrôles

- Rouge : le nouveau test de l'ancre gouvernée échoue contre l'ancien
  `key_id` — `1 failed`, échec attendu.
- Vert ciblé : `1 passed`.
- Suite contrat review-binding : `37 passed`.
- Contrat + producteur après commit : `64 passed`.
- Ruff ciblé : succès.
- Mypy producteur depuis `services/rag-engine` : succès.
- Mypy contrat : une erreur de typage `Literal['ed25519']` préexistante,
  reproduite à l'identique sur le SHA de base ; aucune régression de ce lot.
- Verrous de gouvernance : 18/18 conformes.
- Hygiène repository : succès.
- `git diff --check` : succès.
- Gitleaks différentiel depuis la base : aucun constat.
- Gitleaks dépôt complet : 190 constats préexistants au SHA de base ; ce scan
  n'est pas présenté comme vert.

## Contrôle exact de matière privée

La graine est comparée en mémoire sous forme Raw et hexadécimale, sans être
affichée, aux fichiers suivis, au diff, aux blobs des commits du lot, aux
non-suivis, aux artefacts ignorés hors dépendances/caches, aux historiques et
logs de session accessibles et aux arguments/environnements `/proc`
accessibles du même UID.

Le système interdit la lecture de sept environnements de processus du même
UID : session systemd, `sd-pam`, `ssh-agent`, sandbox/app desktop et
`gpg-agent`. Leur contenu n'est pas classé artificiellement comme sûr : il est
non vérifiable avec les permissions disponibles. Cette limite est publiée,
pas masquée ; aucun contournement de permission n'a été tenté.

Compteurs avant commit documentaire, à rejouer sur le HEAD final :

- `TRACKED_PRIVATE_MATCHES=0` ;
- `UNTRACKED_PRIVATE_MATCHES=0` ;
- `DIFF_PRIVATE_MATCHES=0` ;
- `GIT_HISTORY_PRIVATE_MATCHES=0` ;
- `IGNORED_ARTIFACT_PRIVATE_MATCHES=0` ;
- artefacts de dépendances/caches exclus : 151 fichiers, 31 440 762 octets ;
- `LOCAL_LOG_PRIVATE_MATCHES=0` ;
- `PROCESS_ARG_PRIVATE_MATCHES=0` ;
- `PROCESS_ENV_PRIVATE_MATCHES=0` ;
- `PROCESS_UNREADABLE=7` — limite de couverture, aucun verdict sur leur
  contenu ;
- `SIGNING_ENV_PRESENT_AFTER_TEST=false` ;
- artefacts opérateur hors dépôt explicitement scannés : cinq ;
- `LOCAL_OPERATOR_PRIVATE_MATCHES=0`.

## Revues et gate restant

- Revues pré-documentaires de conformité et de qualité du code : `APPROVED`.
- Revue du script local de backup/restauration : `APPROVED` après correction
  des contrôles optimisables, écritures courtes, concurrence, rollback et
  durabilité.
- Revues finales du diff incluant ce rapport et le plan : `PENDING` jusqu'au
  commit documentaire exact.

Gate restant : CI GitHub verte puis trusted-human-review par l'identité
autorisée sur le HEAD exact de la PR. Tout nouveau push invalide cette revue.

## Rollback

Avant merge, abandonner la PR conserve l'ancre actuellement sur `main`. Après
merge et avant toute émission de reçu, une nouvelle PR gouvernée peut retirer
la nouvelle entrée ; aucun retour de confiance vers l'ancre perdue n'est
autorisé. La clé privée et son backup restent sous contrôle opérateur et ne sont
jamais supprimés automatiquement par Git.
