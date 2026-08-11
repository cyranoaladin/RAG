# ADR-0037 — Transition gouvernée vers le corpus public institutionnel

- **Statut** : Proposed
- **Date** : 2026-08-11
- **Décideurs** : @abenrhouma (approbation humaine requise, distincte de l'auteur)
- **Remplace** : rien
- **Lié à** : ADR-0025 (revue humaine de confiance), ADR-0035 (liaison de revue scellée),
  ADR-0036 (chaîne de promotion gouvernée)

## Contexte

La plateforme refuse aujourd'hui tout corpus réel. Trois verrous le
garantissent, et `scripts/transition_authorization_audit.py` impose que
chaque cas d'autorisation les porte à `false` :

```
real_corpus_authorized: false
real_file_authorized:   false
pipeline_authorized:    false
```

Ce refus global a rempli son office : il a permis de construire la chaîne
de preuves sans qu'aucun document réel puisse entrer par inadvertance.
Mais il est désormais le dernier obstacle à un corpus dont chaque maillon
est prouvé — acquisition recoupée, manifeste scellé, archive canonique,
publication adressée par contenu, résolution par digest, catalogue lié,
vue de revue, gate H2, preuve `NEXUS-H2-EVIDENCE-V1`.

La question n'est donc plus *si* un corpus réel peut entrer, mais **par
quelle porte**, et à quelles conditions cette porte ne peut pas servir à
autre chose.

## Décision

Nous introduisons une décision d'autorisation nommée :

```
authorize_governed_public_corpus
```

Elle constitue l'**unique** exception à `REQUIRED_FALSE_SAFETY_FIELDS`, et
cette exception est conditionnelle, nominative et vérifiée par l'audit.

### Ce que l'exception ne fait pas

Elle ne retire aucun champ de `REQUIRED_FALSE_SAFETY_FIELDS`. Un champ
retiré cesserait d'être exigé pour *toutes* les décisions, y compris
celles qui n'ont rien à voir avec un corpus — ce serait autoriser par
effet de bord précisément ce que l'ADR entend encadrer.

Elle ne couvre qu'un seul champ. `real_file_authorized` désignerait un
fichier arbitraire choisi par un opérateur, et `pipeline_authorized` un
pipeline sans campagne : aucun digest ne peut rendre l'un ou l'autre sûr,
puisque ce qu'ils autorisent n'est pas identifiable à l'avance. Ils
restent faux en toutes circonstances, y compris sur cette décision.

Elle ne s'étend à aucune décision antérieure. Un cas portant
`authorize_metadata_only_preparation` qui tenterait de lever le verrou est
refusé exactement comme avant.

### Ce que l'exception exige

Un cas d'autorisation ne peut porter `real_corpus_authorized: true` que
s'il satisfait **toutes** les conditions suivantes. Un manquement unique
refuse la transition ; il ne la laisse jamais passer amoindrie.

| Condition | Ce qu'elle empêche |
|---|---|
| `decision = authorize_governed_public_corpus` | qu'une décision existante hérite du privilège |
| `decision_reason = governed_public_institutional_corpus_authorized` | qu'un motif libre masque la nature de la décision |
| `adr_reference` nommant un ADR | qu'une autorisation existe sans trace délibérative |
| `campaign_id` + `campaign_sha256` | que l'autorisation désigne « le corpus » plutôt qu'*un* corpus |
| `corpus_oci_digest` en `sha256:<64 hex>` | qu'un tag mutable soit repointé après approbation |
| `corpus_manifest_sha256`, `corpus_tree_digest` | que l'archive et l'arbre matérialisé divergent |
| `catalog_sha256`, `review_view_sha256` | que ce qui a été relu diffère de ce qui sera publié |
| `h2_evidence_sha256` | qu'un corpus entre sans que le gate ait conclu |
| `corpus_classification = PUBLIC_INSTITUTIONAL` | qu'un corpus privé emprunte cette voie |
| `private_corpus_included = false` | qu'un corpus mixte passe sous une étiquette publique |
| tous les `REQUIRED_TRUE_SAFETY_FIELDS` inchangés | que la nouvelle voie remplace les garanties au lieu de s'y ajouter |

Les digests doivent être en hexadécimal minuscule sur 64 caractères ; le
digest OCI doit porter son algorithme. Une forme abrégée est ambiguë et
ne peut pas épingler un objet immuable.

### Reconnue, mais pas exigée

L'audit distingue désormais deux ensembles. `MANDATORY_AUTHORIZATION_DECISIONS`
contient les quatre décisions que la configuration doit déclarer — les en
retirer reviendrait à les autoriser implicitement.
`ALLOWED_AUTHORIZATION_DECISIONS` est un sur-ensemble qui ajoute
`authorize_governed_public_corpus` : l'audit sait l'évaluer, et la contrôle
intégralement dès qu'elle apparaît, mais ne l'exige pas.

Cette distinction est délibérée. Exiger sa déclaration obligerait à écrire
aujourd'hui, dans le dépôt, le cas d'autorisation qu'un humain doit décider
demain — c'est-à-dire à préempter la décision que cet ADR existe pour
encadrer.

## Ce qui reste fermé

Cet ADR **n'active rien**. À la date de sa rédaction :

- aucun cas d'autorisation du dépôt ne porte `real_corpus_authorized: true` ;
- `real_documents_allowed` et `curated_ingestion_allowed` restent `false`
  dans `configs/pedago_interface_contract.yml` ;
- `answer_generation_allowed` reste `false` et relève d'une transition
  distincte, qui devra prouver le grounding, les citations obligatoires, le
  refus sans source et la résistance aux instructions présentes dans les
  documents ;
- `scripts/governance-locks.baseline` est inchangé.

L'activation réelle suppose quatre actes humains, dans cet ordre :

1. accepter cet ADR (statut `Accepted`) ;
2. publier le corpus sur GHCR et relever le digest effectivement rendu ;
3. approuver le descripteur de campagne portant ce digest, en exact-head ;
4. ajouter le cas d'autorisation correspondant, avec les huit digests.

## Conséquences

**Positives.** La porte est unique, nommée et étroite. Une autorisation ne
peut plus dire « les documents réels sont permis » : elle dit « *ce*
corpus-ci, dont voici les huit digests, classé public institutionnel, est
autorisé ». Un corpus différent — fût-il d'un octet — ne satisfait plus
l'autorisation.

**Négatives.** Chaque nouvelle campagne exige un nouveau cas d'autorisation
et donc une nouvelle approbation humaine. C'est le coût assumé : une
autorisation qui survivrait au changement de corpus ne prouverait plus rien
sur ce qui est publié.

**Risque résiduel.** L'audit vérifie la *forme* des digests, pas leur
correspondance avec un artefact réel — c'est le rôle du gate H2 et de la
promotion. Un cas d'autorisation syntaxiquement parfait mais portant des
digests inventés passerait l'audit et échouerait à la promotion. Le refus
arrive donc, mais plus tard qu'il ne pourrait ; le rapprochement précoce
entre autorisation et preuve H2 reste à faire.

## Vérification

`services/rag-pedago/tests/test_governed_public_corpus_transition.py`
couvre 35 cas, dont l'intégralité des refus. Cinq preuves de mutation ont
été exécutées : élargir l'exemption aux trois champs, ne pas vérifier ses
conditions, accepter une classification privée, laisser une décision
quelconque l'emprunter, et accepter un tag mutable comme digest. Chacune
fait passer au rouge les tests qui la concernent.
