# Dossier d'Arbitrage Humain — Pull Requests #138 et #140

**Date** : 16 septembre 2026
**Lot** : `LOT_GO_LIVE_FINAL_BN_CLOSE_BLOCKING_PRS_AND_PRODUCTION_QUALIFICATION_PATH`
**Statut actuel** : `HUMAN_DECISION_REQUIRED` (Maintenu tant que la fermeture effective n'est pas actée par l'opérateur humain)

---

## 1. Synthèse Exécutive

Dans le cadre de l'assainissement des Pull Requests bloquantes pour le Go-Live de la plateforme Nexus RAG, deux PRs historiques de grand volume ou d'architecture divergente demeurent ouvertes.
Ce document fournit l'analyse technique contradictoire, l'évaluation des risques et les commandes recommandées pour l'arbitrage humain.

| PR # | Titre | Volume / Base | Conflit Architectural Majeur | Recommandation |
|:---|:---|:---|:---|:---:|
| **#138** | `Rescellement de la release production et seconde émission des scopes (ADR-0051, ADR-0052)` | 53 fichiers<br>Base non-main | Viole le gel de release ADR-0050 ; tente de resceller une ancienne release v2 avec des scopes incompatibles avec l'architecture actuelle (ADR-0055, ADR-0057). | **Fermeture sans merge (`CLOSE_REJECTED`)** |
| **#140** | `nexus: integration trunk (lots 28-40) and cockpit cutover (D-1bis, D-10, D-20, D-21, D-23)` | 343 fichiers<br>Base obsolète | Trunk d'intégration massif d'août 2026 dont les composants ont déjà été intégrés par morceaux sur `main` ; viole l'autorité unique et casse les contrats SemVer actuels. | **Fermeture sans merge (`CLOSE_SUPERSEDED`)** |

---

## 2. Analyse Approfondie — Pull Request #138

### Contexte
- **Branche** : `lot/release-reseal-scopes-v2-20260828`
- **Head commit** : `11fa847ef669be6d5400d0d93fd342013283fa3e`
- **Objet initial** : Tentative fin août 2026 de resceller les autorisations de release de production et de produire une seconde émission des scopes sous ADR-0051 et ADR-0052.

### Incompatibilités et Obstacles Techniques
1. **Violation d'ADR-0050 (Gel de Release)** : ADR-0050 stipule qu'aucune dérive de release ne peut être introduite sans validation formelle et audit préalable. La PR #138 tente une réécriture rétrospective de l'autorité de release.
2. **Conflit d'autorité avec ADR-0055 et ADR-0057** : La gestion de l'actualité et la composition de la matrice de servabilité (`servability_matrix_v1.json`) ont été totalement refondues et scellées par ADR-0055 et ADR-0057. Le rescellement porté par #138 repose sur une structure de scopes périmée.
3. **Conflits de merge insolubles** : Plus de 100 collisions de fichiers avec le `main` actuel, notamment sur les packages de contrats, la chaîne de release et les données de release de rentrée.

### Risques d'un Merge Forcé
- Rupture immédiate de l'unicité des autorités (`scripts/check-authority-uniqueness.sh`).
- Invalidation de l'inventaire du corpus servable (`SERVABLE_CANDIDATE_SET`) et régression du searchability gap.
- Corruption de l'intégrité cryptographique scellée sur `main`.

### Recommandation & Commande Proposée
Il est recommandé à l'opérateur humain de clôturer la PR #138 sans fusion.

**Commande suggérée pour l'arbitre humain :**
```bash
gh pr close 138 --comment "PR fermée sans merge suite à arbitrage formel (dossier docs/reports/go_live/HUMAN_DECISIONS_PR_138_140.md) : le rescellement de release proposé est caduc, en conflit majeur avec l'architecture ADR-0055/ADR-0057 et violerait ADR-0050."
```

---

## 3. Analyse Approfondie — Pull Request #140

### Contexte
- **Branche** : `lot/cockpit-cutover-20260829`
- **Head commit** : `864c882b7f3f689a8e6b4939540f5086e9b6551d`
- **Volume** : 343 fichiers modifiés, +11 400 lignes / -4 200 lignes.
- **Objet initial** : « Trunk d'intégration des lots 28 à 40 et cutover cockpit ».

### Incompatibilités et Obstacles Techniques
1. **Contenu déjà absorbé ou supersédé** : Entre le 29 août et le 16 septembre 2026, l'ensemble des fonctionnalités nécessaires ont été intégrées via des PRs unitaires propres (Lots 41, 44, ADR-0055, Lots 190 à 205). Le cockpit a déjà été découplé pour ne parler qu'au contrat `nexus-contracts` via l'API retrieval de `rag-engine` (conformément à l'ADR-0001).
2. **Écrasement des contrats actuels** : La PR #140 contient des versions anciennes de contrats TypeScript et Python qui réintroduiraient des régressions de schéma et casseraient les golden queries.
3. **Conflit avec les garde-fous d'autorité** : Réintroduction de lecteurs directs de la matrice ou de modules dépréciés.

### Risques d'un Merge Forcé
- Échec immédiat de la CI sur `services/cockpit`, `packages/contracts` et `scripts/qualification`.
- Bris des 18 verrous de gouvernance.
- Perte de la traçabilité granulaire des lots de production.

### Recommandation & Commande Proposée
Il est recommandé à l'opérateur humain de clôturer la PR #140 sans fusion.

**Commande suggérée pour l'arbitre humain :**
```bash
gh pr close 140 --comment "PR fermée sans merge suite à arbitrage formel (dossier docs/reports/go_live/HUMAN_DECISIONS_PR_138_140.md) : trunk d'intégration obsolète de 343 fichiers dont les apports ont été intégrés unitairement lors des lots ultérieurs. Son merge réintroduirait des régressions massives sur les contrats actuels."
```

---

## 4. Statut dans le Modèle de Readiness

Conformément au mandat de gouvernance :
- **Ces PRs ne sont pas fermées unilatéralement** par le script ou l'agent.
- Le statut des PRs #138 et #140 reste **`HUMAN_DECISION_REQUIRED`** dans `scripts/go_live/reconcile_open_prs.py`.
- Elles demeurent comptabilisées dans `open_prs_blocking = 2` jusqu'à l'exécution effective de la décision humaine sur GitHub.
