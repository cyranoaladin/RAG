# La release promue contient 26 contenus que le gate refuse

Les valeurs font autorité dans `release_promoted_refused_contents_plan.json`.

## Pourquoi ce nombre ne doit pas être réduit à trois

Le câblage de la politique d'actualité a rendu visibles trois contenus
archivés. Il serait tentant de ne retenir qu'eux : ce sont les nouveaux, ceux
qu'aucun gate ne retenait auparavant.

Ce serait une erreur de compte. **Vingt-trois autres contenus promus sont
refusés** parce que leur revue PII n'est pas tranchée. Ils l'étaient déjà, et
le blocage `pii_undecided` les retenait — mais ils sont, tout autant que les
trois autres, des contenus qu'une release promue porte alors que le gate les
refuse.

Le compteur dit vingt-six. Le réduire à trois ferait disparaître les
vingt-trois derrière une raison qui n'est pas la leur.

## Deux chantiers, pas un

### A — Reseal minimal d'actualité

Il porte **uniquement** sur les contenus archivés. Tous ont leur PII claire :
aucun d'eux n'est retenu par la revue PII, et les traiter ne touche donc aucun
contenu PII.

Ce qu'il faut voir avant de le lancer : après ce reseal, il restera des
contenus promus refusés — ceux de la PII — et `pii_undecided` n'aura pas bougé.
Ce chantier ferme une raison sur cinq. Le présenter comme « la release est
assainie » serait faux.

### B — Résolution PII de la release

Les contenus bloqués par la PII ne doivent être ni retirés, ni blanchis, ni
maintenus sans décision humaine. Les trois options engagent la même personne,
et aucune ne se prend par défaut : ne rien décider, c'est décider de les
laisser dans la release.

Ce chantier vient après ou avec la revue des paquets PII, jamais à sa place.

## Trois raisons qui ne se confondent pas

| Raison | Ce qu'elle dit |
|---|---|
| PII | une décision humaine est due sur des données personnelles |
| Actualité | la source déclare le document archivé |
| Impact de release | une release promue porte un contenu désormais refusé |

Un contenu peut relever des trois à la fois. Les fondre ferait croire qu'en
traiter une les traite toutes.

## Ce que ce lot n'a pas fait

Aucune release modifiée, aucune identité de release changée, aucun contenu
retiré, aucune décision PII prise. Chaque ligne porte l'action requise et
l'effet attendu de chaque option — pour que la décision soit prise en
connaissance de cause, pas pour la prendre.
