# Plan de reseal d'actualité — préparé, non appliqué

Les valeurs font autorité dans `currentness_reseal_candidate_plan.json`.
Statut : `PREPARED_NOT_APPLIED`. **Aucun fichier de release n'est modifié par
ce lot.**

## Ce que le plan propose

Exclure de la release promue les contenus que la source déclare archivés, et
eux seuls. Tous ont leur PII claire, donc l'opération ne touche aucun contenu
en attente de décision personnelle.

## Pourquoi une identité neuve, et pas une correction

ADR-0050 est explicite : aucune release ne se rescelle en place. Retirer un
contenu d'une release existante en gardant son identité ferait mentir tout ce
qui a été scellé sous cette identité — une release qu'on peut corriger n'est
plus une preuve de ce qui a été servi.

L'exclusion exige donc une **identité neuve**, distincte de
`production-profile-gate-2026-2027-v1` et de toute identité déjà utilisée.

**Ce plan ne nomme pas cette identité.** Nommer une release est une décision de
gouvernance ; un script qui la choisirait déciderait à la place de son
propriétaire.

## L'impact attendu, y compris ce qu'il ne change pas

L'ensemble promu perd trois contenus. Le compteur d'incohérence de release
descend de vingt-six à vingt-trois — les vingt-trois de la PII restent. La
part d'actualité de ce compteur tombe à zéro.

`pii_undecided` ne bouge pas. `GO_LIVE_READY` reste faux.

Ce reseal ferme une raison sur cinq. La qualification, les PR bloquantes et la
revue PII persistent, et le corpus reste sans vecteurs.

## Hors périmètre, explicitement

Les contenus promus bloqués par la PII. Toute décision PII. Tout déploiement,
tout basculement de production, toute écriture en base de production.

## Ce qu'il manque pour l'appliquer

Une autorisation explicite du propriétaire du corpus. Tant qu'elle n'est pas
donnée, ce document décrit une option — pas une intention.
