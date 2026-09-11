# La release promue contient des contenus désormais refusés

Les valeurs font autorité dans `currentness_release_impact.json`.

## Pourquoi ce document ne pouvait pas rester un constat

Appliquer la politique d'actualité a fermé un drapeau — `currentness_policy_applied`
est passé à `true` — et, du même mouvement, a révélé que la release promue
contient des contenus que le gate refuse désormais.

Si le second fait n'était porté que par un rapport, fermer le premier ferait
disparaître le risque au moment même où on le découvre. Un blocage explicite
existe donc maintenant dans le readiness : `release_promoted_refused_contents`.
Tant qu'il est non nul, `GO_LIVE_READY` reste faux et la raison est nommée.

## Ce que le blocage PII ne couvre pas

Sur les contenus promus que le gate refuse, la majorité l'est pour une PII non
tranchée : ceux-là étaient déjà retenus par `pii_undecided`, qui bloque.

**Trois ne le sont pas.** Ils portent tous `PII_CLEARED_OR_NOT_SCANNED` : aucun
blocage antérieur ne les retenait. Ils sont refusés parce que la source les
déclare archivés, et rien d'autre ne le disait. La preuve est ligne à ligne
dans `rows`, avec le statut PII de chacun.

Affirmer que « la PII suffit » aurait donc été faux, et vérifiablement faux.

## Trois dimensions qui ne disent pas la même chose

| Dimension | Ce qu'elle dit |
|---|---|
| PII | une décision humaine est due sur des données personnelles |
| Actualité | la source déclare le document archivé |
| Impact de release | une release promue contient un contenu désormais refusé |

Les fondre ferait disparaître la troisième derrière les deux autres. Le
readiness les compte séparément, et le rapport les sépare aussi.

## Ce qui n'a pas été fait

**Aucune release n'a été modifiée. Aucune identité de release n'a changé.
Aucun contenu n'a été retiré.**

Les actions possibles sont nommées pour chaque ligne — exclure et resceller
sous une identité neuve, déroger par une autorité explicite, ou maintenir le
blocage jusqu'à la revue PII et la revue de release. Choisir appartient au
propriétaire du corpus. Un script qui trancherait cela retirerait du contenu
d'une release sans que personne ne l'ait décidé.

## Ce qui ne peut pas être mesuré en silence

Un contenu promu que la matrice ne recense pas ne peut pas être croisé. Le
compter comme candidat serait un zéro non mesuré présenté comme un zéro mesuré.
Le readiness le dit — `release_impact_measurable` — et bloque tant qu'il ne
peut pas conclure.
