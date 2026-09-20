# Lot CH5 — Enregistrer les autorisations LOT41A avant la fusion

- **Lot** : `LOT_GO_LIVE_FINAL_CH5_REGISTER_LOT41A_AUTHORIZATIONS_BEFORE_MERGE`
- **Branche** : `go-live/register-lot41a-authorizations`
- **Base** : `25b88f31` (`main`, après merge de #232 / lot CH4)
- **Date** : 2026-09-20

> **L'approbation de cette PR par abenrhouma ouvre la fenêtre de revue vivante
> qui permet d'enregistrer les onze autorisations LOT41A déjà approuvées au lot
> CH4. Le périmètre métier est inchangé, octet pour octet : cette PR ne
> redéfinit aucune décision, elle rend seulement leur enregistrement possible.**

Aucun enregistrement n'est effectué par la PR elle-même. Aucun job, aucune
ingestion, aucune écriture en base.

---

## 1. Ce qui s'est passé

Le lot CH4 a été fusionné **avant** que les onze autorisations ne soient
enregistrées. `authorize_scope_cli record-authorization` les a alors refusées
toutes les onze, identiquement :

```
AUTHORIZATION_DENIED: PR #232 is not APPROVED at head c70a7cff…
  — reason=pull_request_not_open
```

Ce n'est pas un défaut de l'outil. `evaluate_trusted_review` exige
`pr["state"] == "open"` : une PR fusionnée ne peut plus porter une
autorisation, sans quoi une décision resterait enregistrable indéfiniment
après la disparition de son contexte de revue.

**C'est une erreur d'ordre, pas de contenu.** La séquence correcte est
*enregistrer, puis fusionner* — jamais l'inverse.

## 2. Aucun « rebind » n'est nécessaire

La question se posait : les artefacts pointent-ils vers #232 et son head ? La
réponse est **non**, et elle est vérifiable sur les octets. Les onze artefacts
ne portent que ces champs :

```
allowed_domains, authorization_id, decision, exclusions, manifest_digest,
pii_absence_attested, pii_absence_evidence, profile_fingerprint, profile_id,
profile_version, protocol_version, rights_categories, scope,
valid_from, valid_until
```

Ni `pull_request`, ni `expected_head`, ni relecteur, ni évidence de revue.
C'est une propriété voulue du modèle : *« un artefact ne peut pas contenir la
preuve de sa propre approbation (elle n'existe qu'après le commit qui le
porte) »*. Le dépôt, la PR, le head et le relecteur sont fournis à
l'**enregistrement** et relus en direct.

Les mêmes octets valent donc pour n'importe quelle revue vivante qui les
approuve. **CH5 ne modifie aucun fichier d'autorisation** — un test le vérifie.

## 3. Ce qui est déjà en place et n'est pas rejoué

| Élément | État vérifié |
|---|---|
| 11 artefacts LOT41A sur `origin/main` | **11/11 à l'identique et canoniques** |
| Autorisation SSH de staging | `ssh_staging_authorized: true`, zéro écart |
| Schéma `ingestion_control` | 13 migrations, `SCHEMA_VERIFICATION=OK`, `SCHEMA_HEAD=13` |
| Rôles canoniques | `migrator`, `app`, `authority`, `attestor` créés |
| Séparation des DSN | `ingestion_control_app` ≠ `rag_publisher`, garde canonique passée |
| Cibles | tunnel staging seul ; ni `rag_pgvector`, ni hôte de production |
| `scope_authorizations` | **0 ligne** — rien n'a été écrit de travers |
| Jobs | aucun |
| Production | intacte |

Le schéma et les rôles ne sont **pas** rollbackés : ils sont conformes, et les
reprovisionner ne prouverait rien de plus.

### Une précision sur la forme retenue

Le dépôt ne veut pas une *base* distincte mais un **schéma logique séparé**
dans `ragdb`, avec des rôles distincts — c'est la décision D1
(`get_ingestion_control_dsn` : « schéma logique séparé, jamais de confusion de
connexion par défaut »), et le migrateur canonique vise `PGDATABASE: ragdb`.
Créer une base séparée aurait été une solution ad hoc ; la séparation vient du
**rôle**, et la garde de DSN distincts la vérifie.

## 4. Épreuves — 18, toutes exécutées

`scripts/qualification/tests/test_lot41a_registration_requires_a_live_review.py`

| # | Exigence | Épreuve |
|---|---|---|
| 1, 5 | PR fermée → refus | `test_une_pr_fermee_est_refusee` (`closed`, `merged`), `test_une_autorisation_ne_peut_pas_etre_enregistree_apres_la_fusion` |
| 2 | ouverte non approuvée → refus | `test_une_pr_ouverte_sans_approbation_est_refusee` (3 états), `test_une_pr_ouverte_sans_aucune_revue_est_refusee` |
| 3 | head divergent → refus | `test_une_approbation_sur_un_autre_head_est_refusee`, `test_un_head_de_pr_different_de_la_revue_est_refuse` |
| 4, 6 | ouverte + approuvée + head exact → accepté | `test_une_pr_ouverte_approuvee_sur_le_head_exact_est_acceptee` |
| — | relecteur hors allowlist → refus | `test_un_relecteur_hors_allowlist_est_refuse` |
| 7 | payload identique à CH4 | `test_le_payload_metier_est_identique_a_celui_de_ch4` (comparaison octet à octet contre `25b88f31`) |
| — | aucun rebind nécessaire | `test_les_artefacts_ne_portent_aucune_liaison_de_revue` |
| 8, 9, 10 | onze, ni surplus ni manque | `test_exactement_onze_autorisations`, `test_une_autorisation_par_collection_v2_sans_surplus_ni_manque`, `test_les_trois_collections_decidees_sont_couvertes` |
| 13, 14 | CH5 ne crée ni job ni ingestion | `test_ch5_ne_touche_ni_release_ni_scope_ni_runtime_d_ingestion`, `test_ch5_ne_modifie_aucune_autorisation` |

Les exigences **11, 12 et 15** — `scope_authorizations` vide avant puis égal à
11 après, production intacte — ne sont pas testables en CI : ce sont des faits
d'exécution. Ils seront **mesurés et consignés** au moment de
l'enregistrement, et joints à la preuve `STAGING_EXTERNE`.

## 5. Séquence corrigée, à tenir cette fois

1. CH5 ouverte, CI verte, challenge calculé ;
2. approbation par `abenrhouma` sur le head exact ;
3. `trusted-human-review/head-pinned` vérifié `success` ;
4. **enregistrement des onze autorisations pendant que CH5 est OUVERTE** ;
5. `scope_authorizations = 11`, chaque `authorization_id` vérifié, chaque
   enregistrement lié aux octets canoniques ;
6. **ensuite seulement**, fusion de CH5 ;
7. puis les onze jobs, Worker A, Worker B, publication staging uniquement.

## 6. Ce que cette PR n'autorise pas

Aucun enregistrement, aucun job, aucune ingestion, aucune écriture en base.
`STAGING_EXTERNE` non qualifié, `GO_LIVE_READY` reste `false`. Release V2 ni
modifiée ni promotable ; `promotion_status`, `activation_status` et
`review_status` intacts. Aucun service ni volume sur `nexus-prod`, aucun
`current switch`, aucune exposition publique, aucun Nginx / DNS / certificat.
