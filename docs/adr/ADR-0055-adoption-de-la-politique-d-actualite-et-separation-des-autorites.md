# ADR-0055 — Adoption de la politique d'actualité, et séparation des autorités de servabilité

- Statut : Proposé. Devient Accepté par une review humaine `APPROVED` du Code
  Owner selon ADR-0025, sur le HEAD exact de la PR qui le porte, avec le
  challenge `NEXUS-TRUSTED-REVIEW-V1` sur une ligne autonome.
- Périmètre : gouvernance de la dimension actualité, et propriété des
  décisions de servabilité. Ne produit, ne rescelle, ne promeut et ne
  matérialise aucune release.
- S'appuie sur : ADR-0025, ADR-0049, ADR-0050, ADR-0051, et la politique
  `NEXUS-RAG-CURRENTNESS-POLICY-V1`, versionnée sous
  `services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml`.

## Pourquoi ce numéro, et pas ADR-0052

Un `ls docs/adr/` sur `main` suggère `ADR-0052`. C'est faux, et la vérification
importe autant que la décision :

```text
ADR-0052  revendiqué par les PR #138 et #140 (rescellement de release)
ADR-0053  réservé (autorité eduscol_catalogue_par_scope)
ADR-0054  revendiqué par la PR #139 (posture opérationnelle)
FIRST_FREE_ADR=ADR-0055
```

Le dépôt porte déjà une collision : `ADR-0046` désigne deux décisions sans
rapport, `foyer-unique-predicat-page-pdf` et `manifeste-corpus-servable-nexus`.
Quatre autres collisions attendent dans les PR ouvertes, où `#140` et `#138`
réutilisent `ADR-0048`, `0049`, `0050` et `0051` pour des sujets différents de
ceux fusionnés sur `main`.

## Contexte : deux autorités se contredisaient

La politique d'actualité exigeait, dans sa règle de repli, que **toutes** ces
conditions soient vraies pour accorder la disposition
`OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE` :

```text
OFFICIAL_INSTITUTIONAL_PROVENANCE
CONTENT_SHA_PROVENANCE_MATCH
SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE
PROGRAM_VERSION_COMPATIBLE      <-- décision du gate programme
PII_GATE_PASS                   <-- décision du gate PII
RIGHTS_GATE_PASS                <-- décision du gate droits
CLASSIFICATION_GATE_PASS        <-- décision du gate classification
PLACEMENT_GATE_PASS             <-- décision du gate placement
NO_KNOWN_SUPERSEDING_CONFLICT
```

Cinq de ces neuf conditions appartiennent à d'autres autorités. L'une d'elles
contredit frontalement ADR-0051, qui décide :

```text
PROGRAM_UNKNOWN_SERVABILITY_POLICY=ALLOWED_WITH_OTHER_GATES
PROGRAM_UNKNOWN_BLOCKING_CONTENTS=0
```

Sur la population mesurée, exiger `PROGRAM_VERSION_COMPATIBLE` écarte **2520
contenus sur 2530** : 2440 au verdict inconnu, 79 hors population de mesure, 1
prouvé incompatible. Dix passeraient. ADR-0051 dit zéro bloqué, la politique en
bloquait 2520 : les deux ne peuvent pas être vraies en même temps.

## Ce qui rendait la contradiction difficile à voir

Aucun code ne l'exécutait. La politique est `applied: false` et n'a **aucun
lecteur de production** : seules deux épreuves la lisent. La contradiction
n'était donc visible dans aucun comportement, aucun test rouge, aucune métrique.
Elle attendait le jour de l'adoption pour se manifester — c'est-à-dire le jour
où elle aurait coûté le plus cher.

## Décision

### 1. La politique d'actualité ne produit qu'une disposition d'actualité

```text
CURRENTNESS_POLICY_OWNS_CURRENTNESS_DISPOSITION=true
CURRENTNESS_POLICY_OWNS_PROGRAM_DECISION=false
CURRENTNESS_POLICY_OWNS_PII_DECISION=false
CURRENTNESS_POLICY_OWNS_AUTHORIZATION_DECISION=false
CURRENTNESS_POLICY_OWNS_RIGHTS_DECISION=false
CURRENTNESS_POLICY_OWNS_CLASSIFICATION_DECISION=false
CURRENTNESS_POLICY_OWNS_PLACEMENT_DECISION=false
CURRENTNESS_POLICY_OWNS_SERVABILITY_VERDICT=false
```

Son vocabulaire de sortie reste inchangé : `VERIFIED_CURRENT`,
`OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE`, `NOT_CURRENT_DECLARED_BY_SOURCE`,
`UNKNOWN`.

### 2. Les conditions retirées sont rendues, pas supprimées

```text
PROGRAM_VERSION_COMPATIBLE -> PROGRAM_GATE
PII_GATE_PASS              -> PII_GATE
RIGHTS_GATE_PASS           -> RIGHTS_GATE
CLASSIFICATION_GATE_PASS   -> CLASSIFICATION_GATE
PLACEMENT_GATE_PASS        -> PLACEMENT_GATE
```

Chacune garde son effet bloquant. Elle s'exerce depuis son autorité, une seule
fois. Une politique d'actualité qui refuse un document pour une raison de PII
n'a pas renforcé la PII : elle a créé un second endroit où la PII se décide, et
deux endroits finissent toujours par diverger.

### 3. La servabilité est composée, jamais possédée

Le gate de servabilité compose les dimensions. Aucune dimension ne rend un
verdict de servabilité pour son propre compte. La table des statuts de source ne
porte donc plus de champ `servable`, mais un `currentness_disposition`.

### 4. Ce que la politique ne falsifie jamais

Ces quatre interdits sont conservés mot pour mot, et éprouvés :

```text
403 n'est pas une preuve d'obsolescence
NETWORK_UNVERIFIABLE n'est jamais VERIFIED_CURRENT
une archive déclarée par la source n'est pas ressuscitée par un repli
un instantané officiel n'est pas une vérification réseau
```

L'override d'une archive reste possible, mais seulement par une autorité métier
explicitement documentée — jamais implicite.

### 5. Les 59 contenus sans provenance d'URL

La matrice en compte 59 bloqués par `BLOCKED_NO_URL_PROVENANCE`, sur 79 sans
preuve d'URL, les 20 autres étant déjà écartés comme non indexables par rôle.

Leur disposition d'actualité est `UNKNOWN`. Elle le reste. Cette ADR
**n'autorise ni la fabrication d'une URL, ni l'invention d'une preuve, ni le
repli sur une URL de navigation** pour les faire passer. Un contenu sans
provenance d'URL établie n'obtient pas la disposition de repli, qui exige
`OFFICIAL_INSTITUTIONAL_PROVENANCE` et `CONTENT_SHA_PROVENANCE_MATCH`.

Ils restent comptabilisés dans les 2530, en `GOVERNED_NOT_SERVABLE`. Les
retirer du dénominateur serait la seule manière de les faire disparaître, et
c'est précisément ce qu'il ne faut pas faire.

## Portée de l'adoption

```text
CURRENTNESS_POLICY_AUTHORITY_COUNT=1
CURRENTNESS_POLICY_APPLIED=false
```

`applied` reste `false` tant que cette ADR n'est pas Acceptée **et** qu'aucun
consommateur de production ne lit la politique. L'adoption d'une politique et
son câblage dans le runtime sont deux actes distincts ; les confondre ferait
d'une review de texte un changement de comportement.

## Conséquences

Aucun code de production n'est modifié par cette ADR. Aucun gate n'est relâché :
les cinq conditions retirées bloquent toujours, depuis leur autorité. Aucun
contenu ne devient servable.

Ce qui change est vérifiable : la politique cesse de contredire ADR-0051, et
cesse de pouvoir décider à la place de quatre autres autorités.

## Amendement — le câblage, et le défaut qu'il a révélé

*Ajouté par la PR qui câble la politique. L'ADR passe d'Proposé à Accepté par
l'approbation de cette PR, selon le mécanisme fixé en tête de document.*

### Le câblage change la portée ci-dessus

```text
CURRENTNESS_POLICY_AUTHORITY_COUNT=1
CURRENTNESS_POLICY_APPLIED=true
```

Le texte précédent disait : « l'adoption d'une politique et son câblage dans le
runtime sont deux actes distincts ; les confondre ferait d'une review de texte
un changement de comportement. » Cela reste vrai, et c'est pourquoi le câblage
fait l'objet d'une PR distincte, avec son propre comportement vérifiable.

### Le défaut

En câblant, on a constaté que la matrice de servabilité calculait une colonne
`currentness` que son verdict **ne consultait jamais**. Quarante contenus
déclarés archivés par la source ressortaient candidats servables — dont trois
déjà dans la release promue, l'un rangé sous `90_ARCHIVE_CATALOGUE/`.

Le défaut n'était donc pas une politique manquante : la politique existait,
interdisait explicitement de « ressusciter un document déclaré archive par la
source », et n'était appliquée nulle part. Une dimension calculée mais non
consommée est pire qu'une dimension absente, parce qu'elle donne l'apparence
d'un contrôle.

### Ce que l'application produit

- la politique produit une disposition d'actualité, et rien d'autre ;
- `SERVABILITY_GATE` compose les autorités et nomme celle qui refuse ;
- l'ordre décidé antérieurement est préservé : une incompatibilité de programme
  prouvée prime, la PII vient ensuite, puis l'actualité ;
- 37 contenus passent de candidat servable à refusé par le gate d'actualité ;
- les candidats servables passent de 2301 à 2264.

`applied: true` n'est pas une déclaration : le constructeur de la matrice charge
la politique et refuse de se construire si elle ne s'applique pas. Le drapeau et
le comportement ne peuvent pas diverger.

### Ce que cette ADR ne décide toujours pas

Trois contenus déjà promus sont désormais refusés. Les retirer de la release
exigerait une nouvelle identité de release, ce qui relève d'ADR-0050 et du
propriétaire du corpus. **Aucune release n'est modifiée ici.** Les trois sont
nommés, avec empreinte et chemin, dans
`docs/reports/go_live/currentness_archive_gate_impact.json`.
