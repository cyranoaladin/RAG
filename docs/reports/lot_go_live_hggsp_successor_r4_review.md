# Revue humaine des deux autorisations r4 HGGSP successeurs — revue seulement

> **human review only — no authority mutation.**
> Cette PR ne modifie aucun octet des deux autorisations r4, qui sont déjà sur `main`.
> Elle n'a aucun effet à l'exécution. Elle rend explicite le périmètre d'une revue humaine
> que `record-authorization` vérifie **en direct** : une PR fusionnée ou fermée ne vaut plus revue (ADR-0033 § 5).
> **Elle doit rester ouverte jusqu'à l'enregistrement des deux r4 ; elle ne doit pas être fusionnée avant.**

## Pourquoi cette PR existe

Les deux r4 ont été introduites par #270 (activation du complément HGGSP). Le vérificateur canonique
`scripts/github/trusted_human_review_github.py` refuse #270 : `pull_request_not_open`. L'étape
`successor_scope_authorization_registration_r4` exige `SCOPE_REVIEW_PR` et `SCOPE_REVIEW_HEAD` d'une revue
humaine ouverte, approuvée au HEAD exact, distincte de #262. Cette PR en est le support.

## Périmètre exact de la revue : deux fichiers, déjà sur `main`

| | première spécialité | terminale spécialité |
|---|---|---|
| chemin | `governance/authorizations/lot41a-staging-v5-hggsp-premiere-specialite-r4.json` | `governance/authorizations/lot41a-staging-v5-hggsp-terminale-specialite-r4.json` |
| sha256 des octets | `e960288743dc02aa7e4e974f0016652a362e701a1ab14e983ee44bb0d9c2e0ee` | `82ea181de4ac8eb7e421103346c455c071c66559d5c2ededc47fd965b382fa8a` |
| sha1 de blob Git | `42da8803aaaa1a3d4a7d182be18327b21df10e57` | `7eea38e0c57a70f08b6ffe5901e172d4132899a6` |
| `authorization_id` | `lot41a-staging-v5-hggsp-premiere-specialite-r4` | `lot41a-staging-v5-hggsp-terminale-specialite-r4` |
| `profile_id` / collection | `rag_nexus_hggsp_premiere_specialite` | `rag_nexus_hggsp_terminale_specialite` |
| `decision` | `AUTHORIZE_INGESTION_SCOPE` | `AUTHORIZE_INGESTION_SCOPE` |
| validité | 2026-09-28 → 2027-08-31 | 2026-09-28 → 2027-08-31 |

- **Release :** `production-profile-gate-2026-2027-v5-hggsp`
- **Collections :** `rag_nexus_hggsp_premiere_specialite`, `rag_nexus_hggsp_terminale_specialite` (aucune autre).
- **Protocole :** `LOT41A-V2`, profil `profile-gate-v3`, droits `officiel_public`, domaine `eduscol.education.gouv.fr`.
- **Manifeste de release lié :** `manifest_digest` `763c2ad15b935a671725b1a3b829d3326ca65d016129e77cf5a71c5ebbc568b9`.
- **Preuve d'absence de PII :** `pii_evidence.json@sha256:e5f39023d1d58bd911b6e085c1238d1ace1d030048e9df4660c09e331b88563d`.

## Ce que l'approbation couvre

Le HEAD de cette PR contient les deux r4 telles qu'elles sont sur `main` ; `record-authorization` les relit à ce
commit, octet à octet, et recalcule leur digest. Approuver ce HEAD revient à approuver ces deux fichiers, aux
empreintes ci-dessus, et rien d'autre. Toute modification des r4 sur cette branche invalide la revue.

## Usage prévu

1. Revue `APPROVED` de `@abenrhouma` sur le HEAD exact, preuve `NEXUS-TRUSTED-REVIEW-V1` applicable, `trusted-human-review/head-pinned` vert.
2. `SCOPE_REVIEW_PR`/`SCOPE_REVIEW_HEAD` = cette PR et ce HEAD ; `successor_scope_authorization_registration_r4` enregistre exactement deux autorisations.
3. Après l'enregistrement, cette PR peut être fermée ou fusionnée : la revue est alors scellée (ADR-0058).
