# LOT 1.2 — Procédure de revue humaine PII (campagne `pii-review-2026-09-02-lot-1-2`)

*Prête à être traitée. Rien dans le dépôt ne décide à la place du reviewer ;
rien dans cette procédure ne peut être exécuté par un agent à sa place.*

## Ce qui est prêt

| Objet | Où | Empreinte |
|---|---|---|
| 23 paquets de revue (`NEXUS-PII-REVIEW-BUNDLE-V1`), matière brute | `~/nexus-pii-review-20260902/<content_sha256>/` (hors dépôt, 22 Mo) | chacun : `manifest.json` |
| Index des paquets, sans matière brute | `docs/reports/evidence-index/pii_review_index_20260902.json` | épinglé par l'ensemble de décisions (`review_index_sha256`) |
| Mesure fondatrice (320 contenus, 23 détectés) | `docs/reports/evidence-index/pii_rescan_policy_v5_20260902.json` | voir `content_ledger_20260902.provenance.json` |
| Instruments | politique `pii_gate_policy_h2b_v5`, scanner, foyer `NEXUS-PDF-PAGE-POLICY-V1`, pypdf 6.14.2 | digests dans l'index |
| Contrat | `nexus_contracts.pii_review_decisions` (0.15.0), ADR-0047 | — |

Vérifier l'intégrité des paquets à tout moment (sans secret) :

```bash
cd services/rag-pedago
python scripts/preparer_paquets_revue_pii.py --verifier \
  --output-root ~/nexus-pii-review-20260902 \
  --index ../../docs/reports/evidence-index/pii_review_index_20260902.json
```

## Qui décide

- **Reviewer** : le Code Owner désigné par ADR-0025, `.github/CODEOWNERS` et
  `scripts/github/trusted-reviewers.json` — `abenrhouma`. Aucun autre compte.
- **Auteur de la PR** : distinct du reviewer (login GitHub). Le commanditaire ne
  se substitue pas au Code Owner.
- **Opérateur détenteur de la clé** `review-binding-v1-2026-08-25`
  (`governance/trust-anchors/review-binding-v1.json`) : émet le reçu ADR-0035.
  La clé privée n'entre jamais dans le dépôt (`NEXUS_REVIEW_BINDING_SIGNING_KEY`).

Limite héritée : la séparation auteur/reviewer est vérifiée sur des logins, pas
sur des identités physiques.

## Étape 1 — Décider, contenu par contenu (reviewer)

1. Générer le brouillon (hors dépôt) :

   ```bash
   cd services/rag-pedago
   python scripts/sceller_decisions_pii.py brouillon \
     --index ../../docs/reports/evidence-index/pii_review_index_20260902.json \
     --decision-set-id pii-review-2026-09-02-lot-1-2 \
     --corpus-manifest-sha256 d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e \
     --reviewer-login abenrhouma \
     --sortie ~/nexus-pii-review-20260902/decisions.draft.json
   ```

2. Pour chacun des 23 paquets : lire `manifest.json` (chaque correspondance
   avec page, longueur, contexte, texte), les pages concernées
   (`pages/page-NNNN.txt`) et, si le contexte ne suffit pas, `document.pdf`.
   Remplir dans le brouillon : `decision` (`APPROVED` ou `REJECTED`),
   `decided_at` (ISO 8601 avec fuseau), `justification.category` et
   `justification.statement` (20 à 1000 caractères, sans citer la matière).

   Règles du contrat : un `APPROVED` ne peut pas porter
   `PERSONAL_DATA_PRESENT` ; une justification ne cite jamais la donnée ;
   chaque décision est individuelle — aucune décision « en bloc ».

3. Sceller structurellement (l'outil refuse tout brouillon incomplet ou qui
   tenterait de lier une décision à un autre paquet) :

   ```bash
   python scripts/sceller_decisions_pii.py sceller \
     --draft ~/nexus-pii-review-20260902/decisions.draft.json \
     --index ../../docs/reports/evidence-index/pii_review_index_20260902.json \
     --sortie ../../governance/pii-review-decisions/pii-review-2026-09-02-lot-1-2.json
   ```

4. Ouvrir une PR dédiée vers `main` contenant uniquement ce fichier (forme
   canonique, jamais retouchée à la main).

## Étape 2 — Review humaine (reviewer, sur GitHub)

1. Calculer le challenge attendu sur le HEAD exact de la PR :

   ```bash
   python scripts/github/trusted_human_review_github.py \
     --repository cyranoaladin/RAG --pull-request <N> --expected-head <HEAD_SHA> --check
   ```

2. Soumettre une review GitHub `APPROVED` sur ce HEAD, avec la ligne
   `NEXUS-TRUSTED-REVIEW-V1:<digest>` seule sur une ligne du corps.
   Tout push ultérieur invalide la review (protection `main`).

## Étape 3 — Reçu de liaison (opérateur, clé en main)

```bash
cd services/rag-engine
export NEXUS_REVIEW_BINDING_SIGNING_KEY=<graine hex, hors dépôt>
python -m ingestor.ingestion_worker.issue_review_binding_cli issue \
  --repository cyranoaladin/RAG --pull-request <N> --expected-head <HEAD_SHA> \
  --decision-set-id pii-review-2026-09-02-lot-1-2 \
  --key-id review-binding-v1-2026-08-25 \
  > ../../governance/pii-review-bindings/pii-review-2026-09-02-lot-1-2.json
unset NEXUS_REVIEW_BINDING_SIGNING_KEY
```

L'émetteur relit l'ensemble de décisions AU HEAD approuvé, recalcule le
challenge et s'auto-vérifie avant de signer ; il n'écrit rien en cas de refus.

## Étape 4 — Vérification hors ligne (n'importe qui, sans secret)

```bash
cd services/rag-pedago
python scripts/sceller_decisions_pii.py verifier-recu \
  --recu ../../governance/pii-review-bindings/pii-review-2026-09-02-lot-1-2.json \
  --decision-set ../../governance/pii-review-decisions/pii-review-2026-09-02-lot-1-2.json
```

Le verdict imprime les contenus `APPROVED` et `REJECTED`. Toute modification
de l'ensemble après émission du reçu rend la vérification rouge.

## Ce qui se passe ensuite (agent, après réception)

1. Recalcul du périmètre admissible DEPUIS les décisions :
   `297 + |APPROVED|` contenus, `455 + Σ placements(APPROVED)`.
2. Tests RED du worker (détection sans revue, revue absente, `REJECTED`,
   autre SHA, autre politique, autre scanner, paquet modifié, décision non
   scellée, reviewer non autorisé, reçu expiré → refus ; `APPROVED` exact →
   admis), puis modification minimale du worker et du producteur
   (`DETECTED_REVIEWED_ACCEPTED`).
3. Mise en cohérence de la matrice, des manifests et des `expected_counts`
   avec la réalité autorisée ; production fraîche non activée ; comparaison
   read-only contre la base 486/319.

Aucune décision n'est fabriquée par l'agent. Si les 23 sont `APPROVED`, la
cardinalité retrouvée devrait être 320 / 488 ; ce nombre n'est qu'une
vérification.
