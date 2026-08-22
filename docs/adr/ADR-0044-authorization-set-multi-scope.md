# ADR-0044 — AuthorizationSet : autorisation multi-scope gouvernée

- **Statut** : **Proposé** — soumis au HUMAN GATE architecture de la PR
  dédiée qui l'accompagne. Aucune acceptation n'est affirmée ici.
- **Date** : 2026-08-22.
- **Périmètre** : `packages/contracts` (nouveaux protocoles `V2`
  additionnels, aucun protocole `V1` existant modifié en place),
  orchestration `rag-pedago` (`h2b_coverage_report.py`,
  `catalog_republish.py`), signer `rag-engine`
  (`sign_production_readiness_manifest_cli.py`), `promote.yml`. **Ne crée
  aucune autorisation, aucune campagne, aucun secret. N'active aucune
  ingestion.**
- **S'appuie sur** : ADR-0001 (séparation des plans), ADR-0035 (liaison de
  revue scellée par autorisation), ADR-0036 (chaîne de promotion
  gouvernée), ADR-0042 (preuve H2 machine-lisible V1 + registre de
  révocation partagé).
- **Ne réutilise pas ADR-0043** (branche `rag-pedago/tier-a-currentness-byte-identity-20260820`,
  quarantinée le 2026-08-22, jamais mergée). Ce document reste
  `UNREVIEWED_WIP` / `NON_AUTHORITATIVE` / `NOT_REUSED` — le sujet
  d'ADR-0043 (migration H2 V1→V2 pour lier la chaîne Tier A complète)
  est de toute façon distinct du sujet ici (autorisation multi-scope).
- **Ne supersede aucun protocole `V1` existant.** `ScopeAuthorizationArtifactV1`,
  `H2CoverageEvidenceV1`, `NEXUS-PRODUCTION-READINESS-V1` restent
  lisibles et vérifiables tels quels pour toute archive existante.

## 1. Problème réel

Le set authority-required réel (post-currentness, avant toute
autorisation), reproduit deux fois indépendamment et confirmé identique
après merge de PR#127 :

```
CURRENT_AUTHORITY_REQUIRED_COUNT=72
CURRENT_AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
```

couvre au moins 22-23 couples réels distincts (niveau, matière) (le nombre
exact dépend de la méthode de partition — voir
`docs/reports/lot_multi_auth_profile_matrix_20260822.md`, écart non résolu
entre 22 et 23/28 selon qu'on regroupe ou qu'on éclate les couples
multi-matière ambigus). Aucun de ces 72 contenus ne peut aujourd'hui
recevoir d'autorisation réelle sans que la chaîne complète
(`ScopeAuthorizationArtifactV2` → `CorpusCampaignV1` → H2 → readiness →
signer → runtime) traite l'ensemble comme un seul `ResourceScope`, ce qui
serait un scope artificiellement élargi (interdit par AGENTS.md et par les
critères déjà posés lors de l'audit PR#127).

## 2. Inventaire exhaustif des singularités (audit adversarial du
2026-08-22)

Repris intégralement de l'audit read-only mené avant ce document (voir
`docs/reports/lot_multi_auth_contract_surface_audit_20260822.md` pour la
matrice complète FILE/FUNCTION/CARDINALITY/WHY). Résumé des points qui
gouvernent la décision d'architecture :

| Composant | Cardinalité actuelle | Besoin de changement |
|---|---|---|
| `ScopeAuthorizationArtifactV2` | 1 autorisation = 1 fichier, déjà auto-suffisant | **Aucun** — N fichiers coexistent déjà sans changement |
| `AuthorizationRevocationRegistry` | déjà un ensemble (`revoked_authorization_ids`) | **Aucun** — déjà N-capable |
| `ReviewBindingV1` | 1 binding = 1 `authorization_id` | **Aucun en tant que classe** — la granularité 1:1 est correcte et voulue (ADR-0035) ; seuls ses consommateurs doivent apprendre à en vérifier N |
| `H2CoverageEvidenceV1.authorization_id` + `input_file_digests["authority"]` | exactement 1 identifiant, exactement 1 digest = sha256(un seul fichier) | **Oui, structurel** — le digest actuel est littéralement le hash des octets d'un seul fichier ; le faire porter N autorisations change sa sémantique de vérification, pas seulement sa valeur |
| `catalog_republish.republish_catalog` | 1 fichier d'autorité ↔ égalité stricte avec l'unique `campaign.authorization_id` | **Oui, orchestration** |
| `CorpusCampaignV1.scope`/`.authorization_id` | exactement 1 scope, exactement 1 autorisation, inlinés dans l'identité canonique | **Oui, décision d'architecture — voir §3** |
| `discover_promoted_campaign` | refuse explicitement >1 campagne promue par événement, par choix de conception documenté | Comportement à préserver, pas à contourner |
| `ProductionReadinessManifestV1.authorization_digest` **et** `.review_binding_digest` | exactement 1 chacun | **Oui, les deux champs** — PR#127 n'avait signalé que le premier ; ADR-0035 exige une revue distincte par autorisation, donc N autorisations impliquent structurellement N review bindings, jamais un seul couvrant les N |
| `sign_production_readiness_manifest_cli.py` (cross-checks `h2_evidence.authorization_id == authorization.authorization_id`, `input_file_digests["authority"] == authorization_digest`) | vérifications 1:1 | **Oui, cascade** des points ci-dessus |
| `.github/workflows/promote.yml` (`campaign_id` unique) | 1 run = 1 campagne | Dépend de l'option retenue en §3 |
| `services/rag-engine/.../ingestion_control/scope_authority.py` (table `scope_authorizations`, vérification par ligne) | déjà 1 ligne par `authorization_id`, vérifiée indépendamment | **Aucun** — déjà N-capable, la meilleure nouvelle de cet audit |
| `services/rag-engine/.../governed_publisher_v2.py` (`authorization_ids: Sequence[str]`, `tuple(sorted(set(...)))`) | déjà pluriel, déjà canonique-trié | **Aucun** — précédent directement réutilisable comme modèle de canonicalisation |

## 3. Décision d'architecture — Option B retenue

Deux options structurellement saines existaient, aucune n'étant gratuite :

- **Option A — N campagnes indépendantes** (une par scope) : ne change pas
  `CorpusCampaignV1` en apparence, mais H2 évalue aujourd'hui la
  couverture sur l'**intégralité** du catalogue en un seul passage global
  (`corpus_total_expected`/`corpus_total_actual`, invariant « toute
  autorité requise non couverte est une violation », sans notion de
  scope). Pour que N campagnes indépendantes fonctionnent, H2 devrait
  devenir *relatif au scope* — traiter les 67 autres contenus
  authority-required comme "hors périmètre de cette run" plutôt que "non
  autorisés". C'est un changement plus risqué que celui proposé ici : il
  affaiblirait l'invariant de sécurité central de H2 (« 100% de couverture
  ou échec, jamais un sous-ensemble ») en un contrôle partiel/relatif, et
  N campagnes exigeraient de toute façon un nouveau mécanisme pour
  vérifier après coup que l'union des N campagnes promeut exactement le
  set complet — c'est-à-dire un artefact d'agrégation malgré tout, mais
  ajouté une couche plus haut et avec un invariant H2 plus dangereux à
  affaiblir.
- **Option B — une campagne, un nouvel artefact `AuthorizationSetV1`
  regroupant N autorisations** (retenue) : préserve l'invariant global de
  H2 (un seul passage, une seule preuve honnête de couverture à 100 % du
  set réel), garde chaque revue humaine strictement 1:1 avec son
  autorisation (ADR-0035 intact), et suit un patron déjà existant et
  éprouvé dans ce dépôt (`governed_publisher_v2.py`,
  `authorization_ids: Sequence[str]` canonique-trié).

`ARCHITECTURE_DECISION=Option B`. `CorpusCampaignV1` référence désormais
un `authorization_set_digest` (un seul champ, remplaçant
`authorization_id`), jamais une liste répétée à chaque niveau.

## 4. Nouveau protocole `NEXUS-AUTHORIZATION-SET-V1`

Nouveau fichier `packages/contracts/src/nexus_contracts/authorization_set.py` :

```python
class AuthorizationSetMemberV1(StrictBaseModel):
    authorization_id: StrictStr
    authorization_digest: StrictStr  # sha256(bytes canoniques de CE fichier ScopeAuthorizationArtifactV2)
    review_binding_digest: StrictStr  # sha256(bytes canoniques du ReviewBindingV1 de CETTE autorisation)
    scope_digest: StrictStr  # sha256(JSON canonique des 10 dimensions ResourceScope de CETTE autorisation)
    allowed_content_sha256: tuple[StrictStr, ...]  # copie exacte du contenu de l'autorisation, jamais recalculée depuis autre chose

class AuthorizationSetV1(StrictBaseModel):
    protocol_version: Literal["NEXUS-AUTHORIZATION-SET-V1"]
    manifest_digest: StrictStr  # attendu identique sur CHAQUE membre — vérifié, jamais supposé
    members: tuple[AuthorizationSetMemberV1, ...] = Field(min_length=1)
    authorization_count: int
    authorization_set_digest: StrictStr  # sha256(JSON canonique, membres triés par authorization_id)
    union_content_sha256_digest: StrictStr  # sha256(liste triée dédupliquée de tous les allowed_content_sha256)
    union_content_count: int
```

### 4.1 Canonicalisation (anti-permutation)

`authorization_set_digest` est calculé sur les membres **triés par
`authorization_id`** (ordre lexicographique), jamais par ordre d'insertion
— deux ingénieurs construisant le même ensemble dans un ordre différent
obtiennent le même digest. Prouvé par test : permutation de l'ordre
d'entrée → digest de sortie identique.

### 4.2 Anti-overlap (intersection = 0, sauf multiplicité explicitement
autorisée)

Construction du set **refuse** si deux membres revendiquent le même
`content_sha256` dans leurs `allowed_content_sha256` respectifs, sauf si
le contrat autorise explicitement une multiplicité déclarée (non prévue
dans cette version — `V1` du set refuse toute intersection, point final;
une évolution future pourrait l'autoriser explicitement si un cas d'usage
réel apparaît, jamais par défaut).

### 4.3 Couverture exacte

`union_content_sha256_digest` doit être comparé, au moment de la
construction du set ET au moment de la vérification H2, à
`FINAL_AUTHORITY_REQUIRED_SET_SHA256` :

- **aucun SHA supplémentaire** : tout `content_sha256` de l'union absent
  du set authority-required réel est un refus (scope artificiellement
  élargi) ;
- **aucun SHA manquant** : tout `content_sha256` du set authority-required
  réel absent de l'union est une couverture incomplète (H2 continue de
  refuser, comme aujourd'hui pour une autorisation unique incomplète).

### 4.4 Vérifications qui restent strictement par membre, jamais au niveau
de l'ensemble

- **`manifest_digest`** : chaque membre doit individuellement porter le
  même `manifest_digest` que le manifeste scellé réel — une autorisation
  construite contre un ancien manifeste ne peut pas se cacher dans un
  ensemble construit contre le manifeste actuel.
- **Révocation** : chaque `authorization_id` du set est vérifié
  individuellement contre `AuthorizationRevocationRegistry` — un ensemble
  n'est jamais "valide en bloc", chaque membre doit passer seul.
- **Expiration** (`valid_from`/`valid_until`) : idem, par membre.
- **Review binding** : chaque membre doit avoir son propre
  `ReviewBindingV1` vérifié (reviewer distinct de l'auteur, challenge
  cryptographique exact) — **jamais** une seule revue humaine n'approuve
  l'ensemble entier. C'est le point le plus important de cet ADR à ne
  jamais relâcher : cela romprait la garantie non-transférable d'ADR-0035.

## 5. `H2CoverageEvidenceV2`

`H2CoverageEvidenceV1` reste lisible/vérifiable pour les archives — aucun
producteur ni signer de production n'émet plus V1 après ce lot (même
disposition qu'ADR-0042 → V1 pour son propre prédécesseur implicite, mais
ici sans avoir eu de V0 : V1 devient legacy read-only par cet ADR).

`H2CoverageEvidenceV2` remplace :

```
authorization_id: StrictStr            # supprimé
input_file_digests["authority"]        # supprimé
```

par :

```
authorization_set_digest: StrictStr    # référence l'AuthorizationSetV1 complet
authorization_count: int
authority_required_count: int
authority_covered_count: int
authority_required_set_sha256: StrictStr
```

`authority_covered_count == authority_required_count` et
`authority_required_set_sha256 == union_content_sha256_digest` du set
référencé sont les deux invariants qui remplacent l'ancienne égalité 1:1
`authorization_id`. Le calcul reste un seul passage global sur
l'intégralité du catalogue (2584 objets) — aucune notion de "hors scope
pour cette run" n'est introduite, contrairement à ce qu'aurait exigé
l'Option A.

## 6. `CorpusCampaignV2`

```
authorization_id: StrictStr             # supprimé
```
remplacé par :
```
authorization_set_digest: StrictStr     # référence le même AuthorizationSetV1 que H2CoverageEvidenceV2
```

`scope: ResourceScope` (singulier) est **retiré** de l'identité canonique
de la campagne — la campagne représente désormais l'état gouverné du
corpus complet pour une release, pas un scope individuel ; les scopes
individuels vivent dans les membres de l'`AuthorizationSetV1` référencé.
`discover_promoted_campaign` (refus si 0 ou >1 campagne modifiée par
événement de promotion) est **conservé sans modification** — cette
garantie anti-hasard reste valide et nécessaire quel que soit le nombre
d'autorisations sous-jacentes.

## 7. `NEXUS-PRODUCTION-READINESS-V2`

`ProductionReadinessManifestV1` reste lisible pour les manifestes déjà
signés. `V2` remplace :

```
authorization_digest: StrictStr         # supprimé
review_binding_digest: StrictStr        # supprimé
```

par :

```
authorization_set_digest: StrictStr     # même valeur que CorpusCampaignV2/H2CoverageEvidenceV2 pour cette release — cohérence croisée vérifiée par le signer
```

Un seul champ, pas deux listes parallèles à maintenir synchronisées — le
détail par-membre (digest d'autorisation + digest de review binding par
membre) vit dans l'`AuthorizationSetV1` lui-même (§4), adressé par ce
digest unique. Ceci évite explicitement l'anti-pattern "N champs qui
doivent rester synchronisés partout".

## 8. Signer (`sign_production_readiness_manifest_cli.py`)

Les vérifications croisées existantes (H2 ↔ autorisation ↔ review
binding) deviennent :

- `h2_evidence.authorization_set_digest == readiness.authorization_set_digest` ;
- pour **chaque** membre de l'`AuthorizationSetV1` référencé :
  révocation, expiration, review binding, `manifest_digest` — tous
  vérifiés individuellement (jamais une seule fois pour l'ensemble) ;
- `h2_evidence.authority_required_set_sha256 == FINAL_AUTHORITY_REQUIRED_SET_SHA256`
  attendu (paramètre `--expected-authority-required-set-sha256`, nouveau,
  refus explicite si absent en production — même discipline que
  `--expected-manifest-sha256` existant).

Le signer continue de ne jamais lire ni manipuler de clé privée readiness
— aucun changement à cette garantie déjà testée
(`test_never_signs_and_never_touches_a_private_key`).

## 9. Deploy verifier / gate de démarrage / runtime

`deploy_verified_release_cli.py` et le readiness gate au démarrage
(`services/rag-engine/src/ingestor/ingestion_profiles/readiness_gate.py`)
vérifient déjà un manifeste readiness par digest — leur traitement se
limite à accepter `NEXUS-PRODUCTION-READINESS-V2` en plus de `V1`
(dispatch par `protocol_version`, refus explicite de tout mélange).

**Le runtime `scope_authority` (`services/rag-engine/.../ingestion_control/scope_authority.py`,
table `ingestion_control.scope_authorizations`) ne change pas** — c'est la
conclusion positive centrale de l'audit du 2026-08-22 : ce composant
vérifie déjà chaque `authorization_id` individuellement, par ligne, contre
GitHub en direct. N autorisations signifient simplement N lignes, jamais
un changement de ce module. Idem pour
`governed_publisher_v2.py`/`revocation_registry.py`/les CLIs de job
(`authorize_scope_cli.py`, `issue_review_binding_cli.py`,
`create_job_cli.py`, `runner.py`) : tous déjà conçus par entité, jamais
par supposition qu'il n'existe qu'une seule autorité.

## 10. `promote.yml`

Le seul point qui dépendait réellement du choix d'architecture (§3) :
avec l'Option B, `promote.yml` continue de prendre exactement un
`campaign_id` par run — inchangé, puisqu'une campagne référence désormais
un ensemble d'autorisations plutôt qu'une seule, sans multiplier les runs
de promotion.

## 11. Migration et compatibilité V1/V2

- Aucun fichier `V1` existant n'est modifié en place. Les parseurs `V1`
  restent disponibles pour relire les archives (même discipline
  qu'ADR-0043 avait proposée pour un sujet différent — H2 seul — mais
  jamais réutilisée ici comme source, seulement comme précédent de
  méthode générale déjà établi par ADR-0042/`ScopeAuthorizationArtifactV1`→`V2`).
- Après ce lot, aucun producteur ni signer de production n'émet plus `V1`
  pour `H2CoverageEvidenceV1`/`ProductionReadinessManifestV1`/`CorpusCampaignV1` —
  seul `V2` est signable.
- **Rollback** : si un défaut réel est découvert après merge mais avant
  toute autorisation réelle construite, revert de la PR contractuelle
  seule (aucune autorisation/campagne réelle n'existe encore à ce
  stade — rollback sans perte de données de gouvernance, puisqu'aucune
  n'a encore été créée).

## 12. Ce que cet ADR ne fait pas

- Ne crée aucune `ScopeAuthorizationArtifactV2` réelle.
- Ne crée aucun `AuthorizationSetV1` réel.
- Ne crée aucune `CorpusCampaignV2` réelle.
- Ne signe aucun manifeste readiness.
- Ne modifie aucun verrou de gouvernance (`pedago_interface_contract.yml`,
  `transition_authorization.yml`).
- Ne provisionne aucun GitHub Environment.
