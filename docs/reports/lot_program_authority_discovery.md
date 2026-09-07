# Découverte d'autorité de programme — et deux pièges évités

## 1. Les 18 profils de programme courant

```
CURRENT_PROGRAM_PROFILES=18
CURRENT_PROGRAM_PROFILE_DUPLICATES=0
CURRENT_PROGRAM_PROFILE_CONFLICTS=0
SCHOOL_YEARS={2026-2027: 18}
PROGRAMMES_COURANTS_DISTINCTS=6
```

Aucun scope `(niveau, matière)` ne reçoit deux versions différentes. L'autorité
est cohérente là où elle existe — elle couvre 18 scopes, pas le corpus.

## 2. Liaisons document→programme trouvées

Autorités examinées : `production_profile_resolution_records_20260825.json`
(`schema_version`, `primary_evidence_sha256`, `source_tree_commit`) et
`tier_a_set_algebra_reconciliation_20260822.json`
(`protocol_version=NEXUS-TIER-A-SET-ALGEBRA-V1`, `manifest_sha256`). Toutes deux
consommées par des scripts de production, donc gouvernées.

```
EXACT_ARTIFACT_PROGRAM_BINDING=10
PROGRAM_COMPATIBILITY_PROVEN=10
PROGRAM_INCOMPATIBILITY_PROVEN=0
PROGRAM_COMPATIBILITY_UNKNOWN=2441
                                        somme = 2451, ensembles disjoints

PROVEN_SET_SHA256=2caa5baf09142b8438fe29eb2791afb9e8090dbb921797cd009b65d91330bdf6
UNKNOWN_SET_SHA256=723454413764d0d9d870601e3b93fbb5335cb76013af2a9097db99b44f17a714
```

Les 10 sont liés à `BOEN_special_1_2019-01-22` (7),
`BOEN_special_8_2019-07-25` (2) et
`BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A` (1) — toutes dans
l'autorité courante.

## 3. Premier piège : un mauvais glob, un mauvais zéro

Ma première passe cherchait les liaisons uniquement sous
`services/rag-pedago/data/releases/**` et rendait **0**. Une passe plus large
en trouvait **148**. Deux chiffres contradictoires produits par moi, dont un
faux : les autorités portant ces liaisons vivent sous `docs/reports/`, pas dans
les releases.

## 4. Second piège, plus grave : `programme_version` qui n'en est pas une

Les 148 se répartissaient en 10 + **138**. Ces 138 portent
`programme_version = "2026-2027"` — une **année scolaire** sous une clé qui
annonce une version de programme.

Les compter aurait donné `PROGRAM_INCOMPATIBILITY_PROVEN=138` : 138 documents
déclarés incompatibles avec le programme courant, alors que rien n'établit
quel programme ils servent. C'est exactement l'inverse de la vérité — une
absence d'information transformée en preuve négative.

La liaison exige donc désormais que la **valeur** soit une référence de texte
officiel (`BOEN_…`), pas seulement que la clé porte le bon nom. Le nom d'un
champ n'est pas son contenu.

```
REJECTED_VALUES_NOT_A_PROGRAMME_VERSION = {"2026-2027" [tier_a_…]: 138}
```

Ces 138 restent `UNKNOWN`, ce qu'ils sont.

## 5. Rendement mesuré par famille d'autorité

```
docs_reports        66 fichiers   158 candidats   10 explicites   148 rejetés
release_manifests   70 fichiers   486 candidats    0 explicites   486 rejetés
engine_configs       1 fichier      0 candidats    0 explicites     0 rejetés
pedago_configs       2 fichiers     0 candidats    0 explicites     0 rejetés
```

Une seule famille produit des liaisons. Les manifestes de release portent
486 candidats dont **aucun** n'est une référence de programme : leur valeur
dominante est `EDUSCOL_CORPUS_20260808`, un identifiant de corpus.

C'est le chiffre qui dit où ne PAS investir.

## 6. Un faux négatif de ma part, corrigé

Dix valeurs étaient des **listes** contenant une référence valide
(`['BOEN_special_1_2019-01-22']`). Mon contrôle de forme exigeait une chaîne et
les rejetait. Un faux négatif est moins visible qu'un faux positif, et tout
aussi faux.

Les listes sont désormais admises, chaque élément validé. Elles corroborent les
mêmes 10 documents depuis une seconde autorité — elles n'en ajoutent aucun.

## 7. Partition scellée par ensembles

```
PROGRAM_COMPATIBLE_SHA_SET_SHA256=2caa5baf09142b8438fe29eb2791afb9e8090dbb921797cd009b65d91330bdf6
PROGRAM_INCOMPATIBLE_SHA_SET_SHA256=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b
PROGRAM_UNKNOWN_SHA_SET_SHA256=723454413764d0d9d870601e3b93fbb5335cb76013af2a9097db99b44f17a714

PROGRAM_PARTITION_INTERSECTION_COUNT=0
PROGRAM_PARTITION_UNION_COUNT=2451
PROGRAM_PARTITION_UNACCOUNTED=0
```

## 8. Les dix liaisons, auditables une par une

Toutes portent `binding_basis=GOVERNED_MANIFEST`, champ `programme_version`,
preuve `production_profile_resolution_records_20260825.json`
(`sha256=f22f3aad371e…`), et sont compatibles avec l'autorité courante :
`BOEN_special_1_2019-01-22` (7), `BOEN_special_8_2019-07-25` (2),
`BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A` (1).

```
ARTIFACT_PROGRAM_BINDINGS_TOTAL=10
BINDINGS_WITH_MISSING_EVIDENCE=0
BINDINGS_WITH_INVALID_PROGRAM_REFERENCE=0
BINDINGS_WITH_SCOPE_CONFLICT=0
```

Aucune ne se réclame de `INFERRED_FROM_FILENAME`, `PUBLICATION_YEAR`,
`FOLDER_PROXIMITY` ni `LEXICAL_SIMILARITY` — une épreuve vérifie que ces bases
n'appartiennent pas à l'enum admissible.

## 9. Ce que la découverte change

Le résidu passe de 2451 à **2441**. La découverte structurée a résolu 10
contenus — peu, mais elle a surtout établi que les autorités disponibles ne
portent presque aucune liaison document→programme.

C'est le résultat utile : une revue humaine de 2441 contenus n'est pas
l'option raisonnable, et l'effort doit porter sur l'**extension de
`ArtifactProgramBindingV1`** — pas sur la classification manuelle.

Les 123 du croisement `(niveau, matière)` restent un **signal de découverte**.
Aucun n'est devenu compatible par ce seul croisement.

## 6. Rien n'est appliqué

```
CURRENTNESS_POLICY_APPLIED=false
ARTIFACT_PROGRAM_BINDING_APPLIED=false
```
