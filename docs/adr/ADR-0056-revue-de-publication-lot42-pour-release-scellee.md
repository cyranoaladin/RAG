# ADR-0056 — Revue de publication LOT42 pour une release scellée

- **Statut** : Proposé — HUMAN GATE requis sur la PR
- **Date** : 2026-09-20
- **Décideur attendu** : reviewer humain habilité, lié au HEAD exact de la PR
- **S'appuie sur** : ADR-0032 (autorisation de scope LOT41A), **ADR-0033**
  (chaîne d'attestations LOT42), ADR-0045, ADR-0052, ADR-0053

> Cette ADR **ne publie rien**, n'attend aucun contenu, ne qualifie pas
> `STAGING_EXTERNE` et n'enregistre aucune attestation. Elle définit un
> protocole et ses refus.

## Contexte — pourquoi

Worker B refuse de publier sans attestation LOT42 :

> *« Phase A s'arrête donc sur `NEEDS_REVIEW`, et ce module reprend la
> ressource **après** qu'une attestation valide existe. »*

Le protocole `LOT42-V1` (ADR-0033) lie une revue humaine à **une** ressource :

```python
class PublicationReviewArtifact(StrictBaseModel):
    protocol_version: Literal["LOT42-V1"]
    resource_id: StrictStr      # un seul
    artifact_id: StrictStr      # un seul
    content_sha256: StrictStr
    canonical_url: StrictStr = Field(min_length=1)   # obligatoire
```

`collect_publication_facts(conn, *, resource_id, artifact_id)` est unitaire, et
`attest_publication_cli` n'offre aucun mode groupé.

C'est **exact** pour le pipeline de découverte : chaque ressource est trouvée à
son URL, relue pour elle-même, et son URL canonique est le fait qui l'identifie.

Appliqué à la release scellée `production-profile-gate-2026-2027-v2`, ce même
protocole impose deux choses qu'on ne peut pas honorer sans fabriquer :

| Grandeur | Valeur |
|---|---|
| Artefacts uniques | 315 |
| Placements | 479 |
| Pages `source_url` distinctes | **19** |
| `canonical_url` documentaire par artefact | **inexistante** |

1. **315 revues humaines**, pour un corpus déjà relu au scellement — chaque
   placement y déclare déjà `review_status=reviewed`, `placement_status=active`,
   `currentness=current`.
2. **Un `canonical_url` par artefact**, alors que la release ne connaît qu'une
   `source_url` de provenance, partagée par plusieurs artefacts. Promouvoir une
   URL de page en URL canonique de document affirmerait une identité que
   personne n'a établie.

## Décision — quoi

### 1. `LOT42-V1` est inchangé, et reste obligatoire

Aucun champ n'est retiré, aucune contrainte relâchée. `resource_pipeline`
continue d'exiger `canonical_url` et une revue par ressource. Ce protocole
n'est ni élargi ni déprécié : il décrit correctement le cas qu'il décrit.

### 2. Un protocole distinct : `LOT42-RELEASE-BATCH-V1`

Une revue humaine **unique** peut couvrir un ensemble **si et seulement si cet
ensemble est déterminé par une release immuable**, dont chaque digest est
vérifiable. Ce n'est pas « une revue pour un lot de documents » : c'est une
revue pour un ensemble que personne ne peut modifier après coup sans que la
revue cesse de s'appliquer.

L'artefact `ReleaseBatchPublicationReviewArtifact` lie la décision à :

| Champ | Ce qu'il fixe |
|---|---|
| `release_id`, `release_manifest_sha256` | la release exacte |
| `artifacts_release_sha256` | l'ensemble des 315 artefacts et leurs chunks |
| `candidate_inventory_sha256` | la provenance déclarée |
| `artifact_transfer_manifest_sha256` | le corpus effectivement transféré et vérifié |
| `expected_counts` | 11 / 315 / 479 / 8268 |
| `collections` | les onze, triées, sans doublon |
| `placement_evidence` | `reviewed` / `active` / `current`, exigés **partout** |
| `scope_authorization_ids` | les autorisations LOT41A qui couvrent ces collections |

### 3. Pas de `canonical_url`, et le protocole le dit

Le nouveau protocole **ne porte aucun `canonical_url`**. Le lien aux artefacts
se fait exclusivement par digests — `content_sha256`, `artifact_id`,
`placement_id` — jamais par URL.

La provenance documentaire est conservée pour ce qu'elle est : `source_url`
reste dans `candidate_inventory.json`, et l'artefact en déclare seulement le
nombre (`provenance_source_url_count`) accompagné d'une note explicite. **Une
URL canonique par artefact n'existe pas dans cette release ; le protocole
l'énonce au lieu de la fabriquer.**

### 4. Ce que le validateur refuse

`require_release_batch_review_matches_release` est une fonction **pure** : elle
ne lit aucun fichier et compare la revue aux faits que l'appelant a mesurés.
Elle refuse — jamais n'avertit — sur :

- un `release_id` ou l'un des quatre digests qui diverge ;
- une collection manquante **ou** en surplus ;
- l'un des quatre `expected_counts` qui diverge ;
- un placement dont `review_status`, `placement_status` ou `currentness` n'est
  pas uniformément celui que la revue exige ;
- un nombre d'URL de provenance qui diverge.

Le modèle refuse en outre un `collections` non trié ou avec doublons, une
fenêtre de validité inversée, et un nombre de collections différent de
`expected_counts.subjects` — ces deux-là sont le même fait, les laisser
diverger permettrait d'annoncer onze subjects en n'en couvrant que huit.

### 5. La chaîne humaine est inchangée

L'attestation reste soumise à `evaluate_trusted_review` : approbation par un
relecteur habilité, sur le **head exact**, **pendant que la PR est ouverte**.
Le lot CH5 a établi cette contrainte d'ordre à ses dépens ; elle vaut
identiquement ici.

## Conséquences

- le passage de 315 revues humaines à **une** est justifié par l'immuabilité de
  l'ensemble, pas par une tolérance ;
- `LOT42-V1` et `LOT42-RELEASE-BATCH-V1` coexistent sans se recouvrir : le
  premier pour ce qu'on découvre, le second pour ce qui est scellé ;
- `nexus-contracts` passe en 0.19.0 — évolution **additive**, aucun contrat
  existant modifié ni retiré ;
- aucune attestation n'est produite par cette ADR : la PR opérationnelle qui
  suivra devra faire approuver l'artefact effectif, puis l'enregistrer **avant**
  sa fusion.

## Ce que cette ADR n'autorise pas

Aucune publication, aucune attestation enregistrée, aucune ingestion, aucune
écriture en base staging ou production. `STAGING_EXTERNE` n'est pas qualifié,
`GO_LIVE_READY` reste `false`. La release V2 n'est ni modifiée ni rendue
promotable ; `promotion_status`, `activation_status` et `review_status` sont
intacts. Aucun `current switch`, aucun déploiement production.
