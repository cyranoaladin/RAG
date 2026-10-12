# Lot 2026-10-12 — preuve C signée au runtime public

## Départ et portée

Base `c046b65e43acea9b095078f1f2ea5e8543372231`, tree
`4b1a1206fd1914cdc97f352e1ef7a2ed04c4fbfb`. Worktree isolé,
environnement Python local au worktree. Le défaut P0 est l'appel de Worker B
au vérificateur C sans preuve live ou signée ; le vérificateur refuse donc
correctement avant toute publication. Aucun déploiement ou accès en écriture à
une base ne fait partie de ce lot.

## Changement

Le contrat staging `PUBLICATION` lie maintenant à la signature l'heure et
l'échéance du rejeu C et la revue exacte LOT42 ; version `nexus-contracts`
`0.29.0`, ADR-0075. Le signataire les tire du verdict live typé. Le lecteur C
accepte la readiness staging signée comme preuve distincte de la readiness V2
de production. Worker B fournit les octets signés et la bonne ancre, vérifie
le digest de staging après le gate et conserve le refus si une preuve manque.

## Vérification

TDD : tests rouges avant implémentation pour les champs staging, le mode C
staging, le signataire et le passage de preuve par Worker B ; verts après
implémentation. Sabotages : champs C absents, échéance dépassée, signature ou
ancre altérée, mauvais pin, enveloppe ou binding LOT42, phase incorrecte,
manifest staging substitué après le gate, chemin production absent. Les suites
et contrôles finaux :

- suites contrats et release-chain, signer et Worker B ciblés : **1 330 tests
  verts** après installation de `setuptools` dans le venv neuf ;
- test ciblé additionnel des octets et de l'ancre production gouvernée : vert ;
- Ruff sur les neuf fichiers Python modifiés : vert ;
- mypy ciblé sur les trois fichiers source modifiés : vert ;
- `git diff --check` : vert.

## Limite d'autorité

Ce changement rend la chaîne C exécutable avec une preuve signée valide. Il
ne démontre ni le rejeu C réel sur la cible, ni les attestations LOT42 live,
ni une publication Worker B achevée. Ces preuves doivent être établies par
l'orchestrateur sur la cible isolée avant toute activation.
