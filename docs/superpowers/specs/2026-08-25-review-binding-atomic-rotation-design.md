# Rotation atomique de l'ancre review-binding — conception

## Statut et décision

Cette conception applique la décision opérateur du 2026-08-25. La clé
`review-binding-v1-2026-08-13` est classée `LOST_BEFORE_FIRST_USE` : aucun
reçu réel n'a été émis, aucune compatibilité de reçu n'est à préserver et
l'ancienne ancre ne doit plus pouvoir valider une preuve future.

La rotation est atomique vers `review-binding-v1-2026-08-25`, sans période de
chevauchement. Le registre `NEXUS-AUTHORIZATION-REVOCATIONS-V1` reste inchangé,
car il révoque des autorisations et non des clés de signature.

## Options examinées

1. **Remplacement atomique — retenu.** Une seule clé de production demeure
   dans l'ancre. C'est l'option la plus simple et la seule cohérente avec
   l'absence de reçus historiques.
2. **Chevauchement ancien/nouveau — rejeté.** Il maintiendrait une confiance
   future dans une clé perdue sans apporter de compatibilité utile.
3. **Révocation via le registre des autorisations — rejeté.** Le protocole et
   son schéma ne représentent pas une révocation de clé.

## Matériel privé hors dépôt

La clé est générée localement avec `cryptography` sous la forme attendue par
le producteur : graine Ed25519 Raw de 32 octets encodée en 64 caractères
hexadécimaux minuscules.

Le répertoire primaire est
`~/.local/share/nexus-rag/operator-keys/review-binding-v1-2026-08-25/` :

- répertoire `0700` ;
- fichier privé `0600` ;
- fichier public `0644` au maximum ;
- aucun passage de la graine en argument de processus ;
- aucune copie dans Git, les artefacts de build ou les journaux.

La racine du support est fournie par `NEXUS_REVIEW_BINDING_BACKUP_ROOT`, avec
`NEXUS_REVIEW_BINDING_BACKUP_ROOT=/mnt/sauvegardes` comme valeur par défaut.
Lors de cette rotation, cette valeur par défaut désignait un système ext4 monté
en clair. La sauvegarde est donc un
fichier GPG symétrique chiffré, créé sous
`${NEXUS_REVIEW_BINDING_BACKUP_ROOT:-/mnt/sauvegardes}/nexus-rag/operator-keys/`.
La phrase secrète est saisie par l'opérateur dans une invite locale masquée,
jamais dans la conversation ni une variable d'environnement. La sauvegarde est
produite directement depuis le fichier primaire vers le ciphertext : aucun
plaintext temporaire n'est écrit sous `NEXUS_REVIEW_BINDING_BACKUP_ROOT`. Seul
le checksum du ciphertext est publié ; aucun hash de la graine privée ne l'est.
Le fichier chiffré conserve des permissions restrictives.
Le helper opérateur local durci consomme la même variable ; l'exécution probante
du présent lot a utilisé sa valeur par défaut.

Une restauration est écrite uniquement dans un répertoire temporaire `0700`,
puis détruite. Elle doit établir l'invariant exact :

```text
PUBLIC_DERIVED_FROM_PRIMARY
  == PUBLIC_DERIVED_FROM_RESTORE
  == governance/trust-anchors/review-binding-v1.json
       [key_id=review-binding-v1-2026-08-25].public_key
```

## Changement gouverné

`governance/trust-anchors/review-binding-v1.json` conservera le protocole
`NEXUS-REVIEW-BINDING-V1` et exactement une entrée de production : la nouvelle
clé publique, le nouvel identifiant et un commentaire public entièrement
remplacé, non sensible et factuel. L'ancienne clé, son identifiant et le
commentaire historique erroné seront absents de l'ancre active.

L'ADR-0035 sera amendée pour fixer la sémantique `LOST_BEFORE_FIRST_USE`, le
remplacement atomique, l'absence de chevauchement et la séparation avec le
registre de révocation des autorisations. L'ADR et le rapport du lot
conserveront l'ancien identifiant et l'ancienne empreinte publique complète à
titre d'audit uniquement, explicitement hors de toute confiance active.

L'amendement corrigera également les assertions historiques devenues fausses :

- la clé privée est détenue par l'opérateur et injectée transitoirement pour une
  signature locale ; ce n'est pas un secret CI ;
- elle n'est jamais provisionnée en CI, sur le serveur ou dans un artefact de
  build ;
- la nouvelle ancre publique est provisionnée après la rotation ;
- l'état `Provisioning ready` est atteint seulement après sauvegarde chiffrée et
  restauration vérifiée ;
- la rotation n'est plus « non traitée » et la signature réelle reste un gate
  opérateur hors ligne.

Le contrat n'a pas besoin d'un nouveau protocole ni d'une migration :
`TrustAnchor` sait déjà représenter une liste non vide de clés uniques et
refuse un `key_id` absent. Les tests mesureront toutefois l'état gouverné réel,
pas seulement une fixture.

## Preuves

Le lot doit produire les preuves locales suivantes avant PR :

- test rouge puis vert affirmant que l'ancre gouvernée contient uniquement le
  nouvel identifiant et refuse l'ancien ;
- nonce aléatoire signé par la clé primaire, puis vérifié avec la clé publique
  chargée depuis l'ancre canonique ;
- round-trip factice et jetable du producteur avec une graine de fixture, une
  ancre `environment="test"`, sérialisation canonique et contrôles de liaison
  aux octets de l'autorisation factice ; la vraie clé ne signe que le nonce et
  la preuve de restauration ;
- suppression du reçu et de l'autorisation temporaires après le test, sans
  commit ;
- sauvegarde GPG créée, checksum vérifié, restauration testée et clé publique
  dérivée identique à la clé primaire et à l'ancre ;
- tests ciblés des contrats et du producteur ;
- lint, typecheck et contrôles de gouvernance pertinents ;
- scans de secrets sur le diff et l'historique de la branche ;
- preuve que le privé est absent des fichiers suivis, du diff, des artefacts et
  des arguments de processus.

Déviation historique non reproductible : durant l'exécution initiale, un reçu
synthétique production-format a été créé en mémoire avec la vraie clé avant la
correction de cette conception. Il n'a jamais été persisté, publié ou lié à une
review/autorisation réelle. Aucun reçu gouverné utilisable en production n'a
été signé. La fusion restera soumise à une trusted-human-review conforme sur le
HEAD exact de la PR.

## Livrables Git et gates

Le lot utilise exclusivement la branche
`ops/review-binding-rotation-20260825` et son worktree dédié. Il produit le
rapport `docs/reports/lot_1_review_binding_rotation_20260825.md`, des commits
scopés, un push et une PR unique. La PR doit obtenir une CI verte puis une
trusted-human-review conforme au HEAD exact. Aucun merge automatique n'est
autorisé.

## Rollback

Avant fusion, le rollback consiste à fermer la PR : l'ancre active sur `main`
reste inchangée. Après fusion mais avant émission du premier reçu, un rollback
ne peut pas rétablir la clé perdue ; il doit procéder par une nouvelle rotation
gouvernée vers une troisième clé maîtrisée. La sauvegarde chiffrée de la
nouvelle clé est donc un prérequis, et non une mesure postérieure.
