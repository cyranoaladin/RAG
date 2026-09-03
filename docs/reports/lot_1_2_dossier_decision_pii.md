# LOT 1.2 — Dossier de décision : contenus à détection PII dans le périmètre 488/320

*2026-09-02. Établi après mesure complète, avant toute production. Aucune donnée
personnelle brute n'est reproduite ici : empreintes, classes de motifs et comptes
seulement.*

## 1. Ce qui bloque

Le producteur corrigé par Codex écrit honnêtement `status=DETECTED_RECORDED,
pii_detected=true` pour tout contenu où le scanner trouve une correspondance. Le
worker d'ingestion (`VerifiedPIIEvidenceRegistry.verify_content_clearance`) n'accepte
que `status=CLEARED, pii_detected=false`. La chaîne producteur → preuve → worker n'a
donc pas de contrat pour un contenu détecté : la production 488/320 s'arrête avant
d'écrire une release.

## 2. Contenus concernés — mesure du 2026-09-01

Trois autorités concordent membre à membre sur **23 contenus** parmi les 320 visés :

| Autorité | Date | Politique / scanner | Résultat sur le périmètre |
|---|---|---|---|
| `content_ledger_20260814.jsonl` | 14/08 | `pii_gate_policy_h2b_v5` | 24 `QUARANTINED` sur les 319 servis |
| `scan_pii_corpus_20260829.json` (branche 319) | 29/08 | v5, scanner `8ec8af55…` | 23 refusés = les 24 moins `b81201b8…` |
| Rescan lecture seule de la reprise | 01/09 | v5, scanner à prédicat structurel `8cfe48e2…`, pypdf 6.14.2, 320 SHA vérifiés | **23 détectés / 320**, mêmes 23 ; `8848f073…` : 0 détection |

`b81201b8…` doit sa quarantaine du 14/08 à une campagne antérieure (08/08, politique
`h2b_v1`, une correspondance `postal_address` de 801 caractères) que la politique v5 ne
reproduit pas ; il est clair sous l'autorité actuelle.

Les 23 : 49 correspondances au total (1 à 6 par document), 33 placements
(NSI terminale 11, NSI première 7, SVT terminale 5, HLP première 3, SVT première 3,
HLP terminale 2, SES première 1, DGEMC 1), 13 contenus mono-placés et 10 bi-placés.
Inventaire par contenu (sans donnée brute) : `inventaire_detectes.json` du scratchpad
de la reprise, à verser dans `evidence-index` si la décision l'exige.

Classes de motifs par document : `postal_address` 12, `phone_french` 9,
`student_name_pattern` 4, `email_address` 2, `french_ssn` 1 (`703cbd75…`, quatre
chaînes NIR toutes invalides au contrôle de clé selon le triage du 29/08).

## 3. Nature des détections — ce qu'établit le triage existant

Le triage du 29/08 (commits `e631ea8`, `ed2bc03`, branche 319) a classé des
**chaînes**, pas des documents : 99 chaînes distinctes examinées sur 214 résiduelles,
précision mesurée 2/20 puis confirmée sur 80 de plus ; zéro NIR valide ; aucune
coordonnée de personne privée ; les seuls vrais positifs sont institutionnels ou
professionnels publiés par l'État (adresse d'un lycée dans une liste de commission,
courriel d'une autrice adulte). Les rapports détaillés ont été retirés du suivi
(`ea9bdf9`) pour motif de divulgation ; leur valeur est agrégée dans les messages de
commit et dans `triage_pii_categories_20260829.json`.

Projeté sur les 23 : 3 documents entièrement en `prenom_enonce` ou `institutionnel`
(`39c50431…`, `62d9ac28…`, `96e887c3…`), 2 mixtes, **18 en `RESIDU`** — c'est-à-dire
jamais revus individuellement.

Nature vraisemblable des correspondances, d'après les titres des documents : en-têtes
d'établissement, adresses d'éditeurs, exemples pédagogiques de formats (NSI :
architecture, types construits, tables, entiers, sécurisation des communications).
**Cette vraisemblance n'est pas une revue.** C'est la revue qui peut l'établir, pas
le code qui veut atteindre 488.

## 4. Preuves et décisions existantes

| Objet | Existe ? | Ce qu'il vaut |
|---|---|---|
| Politique scellée `pii_gate_policy_h2b_v5` (`d09cbfd2…`) | oui | `pii_detected → QUARANTINE`, `human_review_required: true` |
| Verrou `pii_absence_required: true` (`transition_authorization.yml`) | oui | sur tous les cas d'autorisation |
| « Décision opérateur du 29/08 » | commentaire de code + messages de commit | non scellée, non signée, non versionnée dans la politique |
| Preuve servie `pii_evidence.json` (lignée B) | oui | 486 × `CLEARED/false` sous `policy_sha256` = v5 : contredit sa propre politique |
| Décision humaine par contenu | **non** | aucun artefact |
| Contrats de décision humaine réutilisables | oui | `rights_evidence_registry.yml` (décisions organisationnelles scellées par manifeste), ADR-0025 (revue GitHub `@abenrhouma`), ADR-0035 (reçus Ed25519 de liaison de revue) |

Conséquence : les 23 contenus sont **servis aujourd'hui** sous une preuve `CLEARED` qui
ne dit pas la vérité de la mesure. La production actuelle porte cette dette, quel que
soit le choix ci-dessous.

## 5. Les deux options

### PII-1 — conserver le garde fail-closed tel quel

- Le worker reste `CLEARED + false` seulement. Le producteur émet `DETECTED_RECORDED`
  pour les 23 ; la release les exclut de l'ingestion (ou ne les produit pas).
- Périmètre admissible : **297 contenus / 455 placements** (320 − 23 ; 488 − 33).
- Risque : perte de 23 ressources officielles (dont 15 placements NSI, matière la plus
  active) très vraisemblablement sans donnée d'élève ; et **régression par rapport à la
  base servie**, qui devra retirer 33 placements existants pour rester cohérente avec sa
  preuve. La cible 488/320 n'est pas atteignable.
- Coût : nul en contrat ; une production et une comparaison read-only.

### PII-2 — admettre un contenu détecté après décision humaine par contenu

Contrat minimal nécessaire (à écrire avant tout code du worker) :

1. un registre versionné `pii_review_decisions` (schéma nommé, ex.
   `NEXUS-PII-REVIEW-DECISIONS-V1`) portant, par `content_sha256` : `policy_sha256`,
   `scanner_sha256`, `page_policy_sha256`, classes et nombre de signaux revus,
   décision `APPROVED_FALSE_POSITIVE` / `APPROVED_PUBLIC_INSTITUTIONAL` / `REJECTED`,
   décideur, date, motif court sans donnée brute ;
2. scellement opposable du registre : digest dans `authority_bindings`, et liaison de
   revue humaine selon ADR-0025/ADR-0035 (review `APPROVED` du Code Owner sur le HEAD
   exact, reçu de liaison), comme pour les autorisations de scope ;
3. statut de preuve explicite `DETECTED_REVIEWED_ACCEPTED` émis par le producteur
   uniquement quand une décision `APPROVED_*` existe pour le SHA exact, la même
   politique et le même scanner ; sinon `DETECTED_RECORDED` ;
4. worker modifié au minimum : accepte `CLEARED/false` ou
   `DETECTED_REVIEWED_ACCEPTED/true` **avec** vérification du registre scellé ; refuse
   tout le reste. Jamais de règle globale `DETECTED_RECORDED = acceptable` ;
5. sabotages obligatoires : détection sans revue → refus ; revue `REJECTED` → refus ;
   revue absente → refus ; registre mal scellé/signé → refus ; revue d'un autre SHA →
   refus ; revue liée à une autre politique/scanner → refus ; revue `APPROVED` pour le
   bon SHA → accepté.

- Périmètre atteignable : 320/488 **si** les 23 reçoivent chacun une décision
  `APPROVED_*` ; sinon, exactement 297 + (contenus approuvés) et 455 + (leurs
  placements).
- Risque : servir une vraie donnée personnelle si une revue est bâclée ; le contrat
  le borne à un contenu nommé, à une décision nommée, à un décideur nommé.
- Coût : un contrat, un ADR, une campagne de revue humaine de 23 documents (49
  correspondances à relire, extraits disponibles hors dépôt), un cycle TDD worker.

## 6. Recommandation technique

**PII-2, avec l'ordre imposé par la passation (§16) : contrat et décisions avant
tout code du worker.** Motifs : la politique scellée prévoit déjà la revue humaine
(`human_review_required: true`) — PII-2 l'exécute au lieu de la contourner ; le
triage existant rend la campagne courte et probablement favorable ; PII-1 obligerait
à retirer 33 placements servis sans que la mesure ait jamais montré une donnée
d'élève.

Dans les deux cas, la dette actuelle doit être nommée dans la prochaine release :
`pii_evidence.json` de la lignée B affirme `CLEARED` sur 23 contenus détectés.

## 7. Ce que le commanditaire doit trancher

1. PII-1 ou PII-2.
2. Si PII-2 : qui décide (Code Owner `@abenrhouma` selon ADR-0025 est le seul modèle
   existant), et si les extraits hors dépôt (`~/Documents/NEXUS_RAG_H2_EVIDENCE`,
   scans du 29/08) suffisent comme support de revue.
3. La rectification en place du registre `content_ledger_20260814.jsonl` (deux lignes
   annotées `RECTIFICATION`, non consignées dans `audit.md` par Codex) : admise comme
   rectification datée, ou à réémettre dans un fichier versionné.
