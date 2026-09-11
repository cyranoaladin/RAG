# Conteneur de revue : inventaire de préservation

Document dérivé. Ne pas éditer à la main :
`scripts/go_live/report_staging_preservation.py` le régénère.

- conteneur : `nexus-drive-staging-v2` (`a7c3a2b0fd3f421e`)
- image : `pgvector/pgvector@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`
- état : **running**, démarré 2026-09-06T21:47:26, 0 redémarrage(s)
- politique de redémarrage : `no`
- santé : NO_HEALTHCHECK
- réseaux : bridge

## Montages

| type | nom | destination | anonyme |
| --- | --- | --- | :---: |
| volume | `e4eb093913421bb0…` | `/var/lib/postgresql/data` | **oui** |

## Risque

- volumes anonymes : **1**
- sans politique de redémarrage : **oui**

un volume anonyme est supprimé par un élagage de volumes sans qu'aucun nom ne le rattache à ce travail.

Aucun secret n'est publié dans ce document : toute variable dont le nom
évoque un secret est masquée, quelle que soit sa valeur.
