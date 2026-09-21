# Cérémonie — clé de readiness de répétition (ADR-0057)

> **Exécutée par le propriétaire du dépôt, hors dépôt et hors hôte.**
> Aucun agent automatique n'exécute les étapes 1 et 2. La clé privée n'entre
> jamais dans ce dépôt, ni sur `nexus-prod`, ni dans un journal, ni dans un
> message.

La chaîne `NEXUS-STAGING-READINESS-V1` existe et refuse tout tant que cette
cérémonie n'a pas eu lieu. C'est le comportement attendu d'une chaîne sans
autorité — pas un dysfonctionnement à contourner.

## Ce que la cérémonie produit

| Artefact | Qui le produit | Où il vit |
|---|---|---|
| Graine Ed25519 (clé privée) | le propriétaire | **hors dépôt, hors hôte**, sauvegardée hors ligne |
| Clé publique (hex) | dérivée de la graine | dans l'ancre, versionnée |
| `key_id` | choisi par le propriétaire | dans l'ancre et dans le manifeste |
| Ancre de répétition | commitée après transmission de la clé publique | `governance/trust-anchors/rehearsal-readiness-v1.json` |
| Manifeste signé | le propriétaire | déposé sur le staging, **jamais commité** |

## Étape 1 — générer la paire, hors dépôt

Dans un répertoire qui n'est **pas** un checkout de ce dépôt :

```bash
umask 077
python3 -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
print(Ed25519PrivateKey.generate().private_bytes_raw().hex())
" > ~/nexus-rehearsal-readiness.seed
chmod 600 ~/nexus-rehearsal-readiness.seed
```

Sauvegarder ce fichier hors ligne. Il ne doit jamais être copié sur
`nexus-prod`, ni collé dans une conversation, ni placé dans une variable
d'environnement — elle apparaîtrait dans `/proc/<pid>/environ`.

## Étape 2 — lire la clé publique

```bash
python3 services/rag-engine/scripts/sign_staging_readiness_manifest_cli.py \
  --show-public-key ~/nexus-rehearsal-readiness.seed
```

L'outil affiche **uniquement** la clé publique. Il ne génère aucune clé et
n'écrit rien.

Choisir un `key_id` daté, par exemple `rehearsal-readiness-v1-2026-09-20`.
Il ne peut contenir ni `ephemeral`, ni `fixture`, ni `sample`, ni `dummy`,
ni `example` : le contrat refuserait l'ancre.

## Étape 3 — publier l'ancre (transmettre la clé publique)

Transmettre **la clé publique et le `key_id`**, jamais la graine. L'ancre
prend alors cette forme, à `governance/trust-anchors/rehearsal-readiness-v1.json` :

```json
{
  "protocol_version": "NEXUS-STAGING-READINESS-V1",
  "keys": [
    {
      "key_id": "rehearsal-readiness-v1-2026-09-20",
      "algorithm": "ed25519",
      "public_key": "<64 hex>",
      "environment": "rehearsal",
      "comment": "Cle de repetition, generee hors depot par le proprietaire ; cle privee conservee hors ligne, hors depot et hors hote."
    }
  ]
}
```

Elle est ajoutée par une PR à revue humaine épinglée, comme toute décision de
gouvernance.

## Étape 4 — signer le manifeste

> **`--merge-sha` est le commit dont l'image a été CONSTRUITE**, pas celui de
> l'amendement qui l'autorise. C'est ce que le contrat déclare — « le commit
> de `main` dont l'image worker a été construite » — et c'est ce qui évite une
> boucle : si le manifeste devait nommer le commit d'autorisation, chaque PR
> documentaire autorisant une image imposerait de la reconstruire pour que le
> manifeste redevienne vrai. Le digest de l'image et son commit de build sont
> lus ensemble dans l'inventaire `NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1` du run
> qui l'a produite.
>
> Une première signature a nommé le commit d'autorisation : le manifeste
> désignait alors un code que l'image ne portait pas, et rien ne le vérifiait.

```bash
python3 services/rag-engine/scripts/sign_staging_readiness_manifest_cli.py \
  --merge-sha <source_commit_sha de l'inventaire de build de l'image> \
  --worker-image ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:<digest> \
  --allowed-release-id production-profile-gate-2026-2027-v2 \
  --release-manifest-file services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json \
  --key-id rehearsal-readiness-v1-2026-09-20 \
  --private-key-file ~/nexus-rehearsal-readiness.seed \
  --trust-anchor-file governance/trust-anchors/rehearsal-readiness-v1.json \
  --valid-days 30 \
  --output ~/staging-readiness-manifest.json
```

Ce que l'outil fait de lui-même, sans le demander :

- il **recalcule** le sha256 du manifeste de release — il n'accepte pas un
  digest saisi ;
- il **vérifie** que `--merge-sha` est un commit réel de ce dépôt ;
- il **refuse** une image nommée par tag ;
- il **revérifie** le manifeste signé contre l'ancre publique avant de
  l'écrire. Un manifeste dont la propre vérification échoue n'atteint jamais
  le disque.

Il affiche le `manifest_sha256` : c'est la valeur de
`NEXUS_READINESS_MANIFEST_SHA256`.

## Étape 5 — déposer le manifeste sur le staging

Le manifeste signé n'est **pas** commité : il est déposé sur l'hôte, dans le
périmètre staging uniquement.

```bash
scp ~/staging-readiness-manifest.json nexus-prod:/srv/nexus-staging/secrets/
ssh nexus-prod 'chmod 600 /srv/nexus-staging/secrets/staging-readiness-manifest.json'
```

Puis, dans le secret staging **et nulle part ailleurs** :

```
NEXUS_ENVIRONMENT=rehearsal
NEXUS_EXPECTED_READINESS_PROTOCOL=NEXUS-STAGING-READINESS-V1
NEXUS_READINESS_MANIFEST_PATH=/srv/nexus-staging/secrets/staging-readiness-manifest.json
NEXUS_READINESS_MANIFEST_SHA256=<valeur affichee a l'etape 4>
NEXUS_STAGING_READINESS_TRUST_ANCHOR=/srv/nexus-staging/repo/governance/trust-anchors/rehearsal-readiness-v1.json
```

Aucune de ces variables ne va en production : le protocole y est sans
autorité, et le type l'interdit.

## Étape 6 — prouver l'identité de l'image, sur l'hôte, avant d'exécuter

Le manifeste **nomme** une image. Tant que rien ne vérifie laquelle tourne
réellement, la signature couvre une intention, pas un fait : un conteneur
lancé depuis une autre image passerait le gate sans être détecté.

Un processus ne peut pas lire de façon fiable le digest de l'image dont il
est issu — `/proc` ne le porte pas, et le lui demander reviendrait à
demander au suspect de décliner son identité. L'inspection se fait donc
**sur l'hôte**, et son résultat est injecté :

```bash
IMAGE_SIGNEE=$(python3 -c "
import json,sys
print(json.load(open('/srv/nexus-staging/readiness/staging-readiness-manifest.json'))['manifest']['worker_image'])
")

# L'identité REELLEMENT presente sur l'hote, telle que Docker la rapporte.
IMAGE_REELLE=$(docker inspect --format '{{index .RepoDigests 0}}' "$IMAGE_SIGNEE")

echo "signee : $IMAGE_SIGNEE"
echo "reelle : $IMAGE_REELLE"
```

Les deux doivent être identiques, caractère pour caractère. Si `docker
inspect` échoue, l'image n'est pas présente : la tirer **par digest**, jamais
par tag.

Puis injecter l'identité constatée au lancement, et jamais une valeur écrite
à la main :

```bash
docker run --rm \
  --env-file /srv/nexus-staging/secrets/readiness.env \
  -e NEXUS_ACTUAL_WORKER_IMAGE="$IMAGE_REELLE" \
  …
```

Le point d'entrée refuse si la variable est absente, vide, sans digest, ou
différente de `worker_image` — **avant** d'ouvrir la moindre connexion.

`NEXUS_ACTUAL_WORKER_IMAGE` n'a pas sa place dans `readiness.env` : ce
fichier porte des faits stables, celle-ci est une constatation faite juste
avant l'exécution. L'écrire dans le fichier reviendrait à la figer, donc à
la rendre fausse dès le prochain changement d'image.

## Renouvellement

Le manifeste expire (`--valid-days`). À l'expiration, le gate refuse — c'est
voulu. Refaire l'étape 4 ; la clé et l'ancre ne changent pas.

En cas de compromission de la graine : retirer la clé de l'ancre par une PR,
ce qui invalide immédiatement tout manifeste signé avec elle, puis reprendre
la cérémonie à l'étape 1 avec un nouveau `key_id`.
