# LOT_GO_LIVE_FINAL_CR_REHEARSAL_READINESS_ANCHOR

- **Branche** : `go-live/cr-rehearsal-readiness-anchor`
- **Base** : `fd2fc240` (#238, chaîne de readiness de répétition)
- **ADR** : ADR-0057
- **Runbook** : `docs/runbooks/ceremonie_cle_readiness_repetition.md`, étape 3

> Cette PR **n'exécute rien** et **n'autorise rien à elle seule**. Elle publie
> une clé publique. Sans manifeste signé, le gate refuse toujours — un test
> le prouve.

## Ce qui a eu lieu avant cette PR

Le propriétaire du dépôt a généré une paire Ed25519 **hors dépôt et hors
hôte**, a conservé la graine hors ligne, et n'a transmis que deux valeurs :

```
key_id         = nexus-rehearsal-readiness-20260920-01
public_key_hex = 075908951258f6a96f209dbae8f33161daebbdd33a1d5aefb9a8793ec77cd715
```

Aucune graine, aucun fichier secret, aucun chemin de clé privée n'a été
demandé, affiché, copié dans le dépôt ni déposé sur `nexus-prod`.

## Ce que la PR ajoute

Un seul fichier de gouvernance :
`governance/trust-anchors/rehearsal-readiness-v1.json`, sha256
`3604f0526c78500ea69eab0cf770a94f46abfe6d357b6e8191e321f91fcb1cf7`.

Vérifications faites sur la valeur transmise, avant de l'écrire :

| Contrôle | Résultat |
|---|---|
| 64 caractères hexadécimaux minuscules | OK |
| point Ed25519 réellement chargeable | OK — soixante-quatre hex ne font pas une clé |
| distincte de la clé de production | OK (`0759…` ≠ `9a42…`) |
| `key_id` conforme au motif canonique | OK, 37 caractères |
| `key_id` sans marqueur non autoritaire | aucun (`ephemeral`, `fixture`, `sample`, `dummy`, `example`) |

## Preuves

### L'ancre ne porte que la clé publique

- `protocol_version` et `keys`, rien d'autre au premier niveau ; cinq champs
  exactement par clé ;
- aucune occurrence de `private`, `secret`, `seed`, `graine`, `password`,
  `token`, `-----begin`, `ssh-rsa` ;
- **un seul bloc de 64 hex dans tout le fichier**, et c'est la clé publique.
  Une graine aurait exactement la même forme : on les compte plutôt que de
  les reconnaître ;
- aucun placeholder : ni `0`×64, ni `f`×64, ni `todo`, `fixme`,
  `placeholder`, `xxxx`, `a_remplir`, `tbd`.

### L'ancre est distincte de la production — dans les deux sens

- l'ancre de répétition **n'est pas acceptée** comme ancre de production ;
- l'ancre de production **n'est pas acceptée** comme ancre de répétition ;
- les deux ne partagent ni clé publique, ni `key_id` ;
- protocoles distincts, `environment: "rehearsal"` littéral sur chaque clé ;
- le nom de fichier diffère de celui de l'ancre gouvernée — le gate refuse
  nommément un chemin qui porterait ce nom-là.

### La chaîne de production est intacte

Les trois empreintes épinglées par le lot CQ sont revérifiées ici : ajouter
une ancre de répétition ne déplace rien de la chaîne de production. L'ancre
de production porte toujours sa clé unique, `environment: "production"`, et
la mention de sa conservation hors ligne.

### L'ancre seule n'autorise rien

Un test configure le gate avec cette ancre, sans manifeste, et vérifie qu'il
refuse :

```
STAGING_READINESS_GATE_FAILED: NEXUS_READINESS_MANIFEST_PATH is not configured
```

Fusionner cette PR ne débloque donc aucune exécution.

Cette preuve-là vit dans `services/rag-engine/tests/test_staging_readiness_gate.py`,
pas dans les épreuves de qualification : elle importe le gate, donc `psycopg`,
que le job `scripts/qualification` n'installe pas. Une première rédaction l'y
avait placée et la CI l'a refusée — `ModuleNotFoundError: No module named
'psycopg'`. La déplacer est la seule réponse juste ; la marquer `skip` l'aurait
rendue muette sans rien prouver ailleurs.

```
pytest scripts/qualification/tests -q          284 passed, 2 skipped
  (rejoué dans un venv propre, sans psycopg, comme le job de CI)
pytest tests/test_staging_readiness_gate.py    52 passed
ruff check                                     All checks passed!
```

## Les cinq verrous avant toute exécution staging

| # | Verrou | État |
|---|---|---|
| 1 | ancre fusionnée sur `main` | cette PR |
| 2 | manifeste readiness rehearsal signé | **à vous** — étape 4 du runbook |
| 3 | variables `NEXUS_READINESS_*` côté staging uniquement | après 2 |
| 4 | image worker tirée par digest | autorisée par CH6 (#237) |
| 5 | readiness rehearsal vérifiée | après 3 et 4 |

Le point d'entrée ne sera pas exécuté avant que les cinq soient satisfaits.
Worker B ne tournera pas avant l'attestation LOT42 batch.
