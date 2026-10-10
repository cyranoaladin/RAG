# Lot — liaison des droits des 253 dérivés textuels

Base : `origin/main` `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`.

Le vérificateur pur `scripts/go_live/derivative_rights_bridge.py` rapproche
exactement les 253 identités de la feuille approuvée #300, du manifeste des
dérivés, des reçus CAS, du registre de droits #312, des octets privés et des
citations. Il vérifie les SHA de l'autorité Éduscol–Etalab, de la feuille et du
manifeste contre le reçu #300, puis refuse les PDF, images, OCR graphique,
licences ou dates manquantes, divergences de source et citations incomplètes.
Le registre de zones des PDF historiques n'est pas une entrée de ce contrôle.

Le reçu #300 n'est pas auto-authentifiant : l'appelant doit exécuter
`check_pr300_authority` contre GitHub avant ce vérificateur. Ce lot ne branche
pas encore le vérificateur au chemin de promotion, n'accorde aucun scope,
n'active aucune release et ne modifie ni staging ni production. Les contrôles
de source, droits tiers, PII, actualité et révocation des 315 PDF restent ceux
du gate délégué #300 et doivent être rejoués au moment de la promotion.

Vérification dans un environnement Python isolé alimenté seulement par les
paquets éditables de **ce** worktree :

```sh
python -m pytest -q scripts/tests/test_derivative_rights_bridge.py
# 10 passed, dont le rejeu des 253 octets privés quand le CAS est disponible
ruff check scripts/go_live/derivative_rights_bridge.py scripts/tests/test_derivative_rights_bridge.py
# All checks passed
git diff --check
# exit 0
```
