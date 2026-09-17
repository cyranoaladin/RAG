# Rapport de Lot : Qualification CAS et Couverture de Magasin C6

## Phase

LOT_GO_LIVE_FINAL_BP_QUALIFY_CORPUS_CAS_C6

> **IMPORTANT — RAPPEL DE L'OBJECTIF FINAL DU CHANTIER GO-LIVE NEXUS**
> L'objectif final ne consiste pas uniquement à réduire des compteurs intermédiaires. L'objectif final impératif et non négociable est :
> - `GO_LIVE_READY = true` ;
> - `--assert-ready = 0` (exit code) ;
> - Production ready ;
> - Déploiement complet ;
> - RAG ingéré, interrogeable et fonctionnel ;
> - Rollback production éprouvé ;
> - Manifeste production signé ;
> - Aucune PII non décidée (`pii_undecided = 0`) ;
> - Aucune PR bloquante (`open_prs_blocking = 0`) ;
> - Aucune qualification ouverte (`go_live_qualification_blockers = 0`).
>
> Ce lot BP reste un **lot technique intermédiaire**. Il n'autorise pas la production, ne modifie aucun current switch (`current_switch = 0`), ne prend aucune décision PII unilatérale (`pii_undecided = 149`), ne déploie aucun service en production et ne modifie aucune base de données de production (`production_db_writes = 0`).

---

## État main de départ

| Élément | Résultat |
|---|---|
| Commit parent de base | `84a235aeb2c7d188ccdf56226a0d0ab73fc8ee0a` (post PR #207) |
| Branche de lot | `go-live/qualify-corpus-cas-c6` |
| Pré-requis PRs bloquantes | `open_prs_blocking = 0`, `open_prs_disposition_unknown = 0` |
| Bloqueurs C4 et C5 | Déjà clos avec attestations scellées (BM et BO) |
| Autorités et verrous | 18 verrous intacts (`check-governance-locks.sh` OK, autorité unique R1 validée) |
| Statut initial readiness | `GO_LIVE_READY = false`, `--assert-ready = 1`, `go_live_qualification_blockers = 9` (C6 ouvert) |

---

## Qualification C6 : Qualification CAS et Couverture de Magasin

Le bloqueur C6 impose que le Content-Addressable Store (CAS) du corpus fasse l'objet d'une qualification formelle, intégrale et scellée, garantissant que :
1. La racine du CAS est explicitement nommée et configurée.
2. Le manifeste CAS existe, est intègre et conforme au schéma canonique gouverné `NEXUS-CORPUS-CAS-MANIFEST-V1`.
3. Les objets sont intégralement relus depuis le disque, leurs empreintes SHA-256 recalculées sur les octets réels, et leurs tailles comparées à l'octet près.
4. Aucun objet déclaré n'est manquant, aucun objet silencieux hors manifeste n'existe, aucun locator ne sort de la racine CAS, et aucun lien symbolique n'est admis.
5. Le digest et le décompte de l'ensemble d'éligibilité gouverné `SERVABLE_CANDIDATE_SET` correspondent strictement à l'autorité d'écart de recherche (2 264 contenus indexables, 266 refusés par le gate de servabilité, digest exact `227617d4c4364dda1267b15bb30005a26a329414bc151f3c3e5f4c5362a1fbdd`).
6. Zéro contenu refusé par le gate de servabilité n'est admis (266 contenus exclus).
7. Zéro contenu issu de la revue PII (`pii_undecided = 149`) n'est promu dans le scope indexable.
8. Zéro contenu à l'actualité obsolète/refusée n'est réintroduit.
9. L'attestation est scellée par SHA-256 et vérifiée lors de la construction des bloqueurs de qualification.

---

## Les 17 Contrôles et Épreuves Adversariales C6

Le harnais de qualification formel et adversarial a été implémenté dans `scripts/qualification/verify_corpus_cas_c6.py` et s'appuie sur `scripts/qualification/verify_corpus_cas.py` :

| Identifiant | Règle / Épreuve de Qualification | Résultat |
|---|---|---|
| `CAS_ROOT_EXPLICITLY_NAMED` | La racine du CAS est explicitement nommée et accessible | **PASS** (`true`) |
| `CAS_MANIFEST_EXISTS` | Le manifeste CAS est présent à la racine | **PASS** (`true`) |
| `CAS_MANIFEST_SCHEMA_CONFORMANT` | Le schéma du manifeste est strictement `NEXUS-CORPUS-CAS-MANIFEST-V1` | **PASS** (`true`) |
| `ALL_OBJECTS_READ_FROM_DISK` | L'ensemble des objets est relu depuis le disque physique | **PASS** (`true`) |
| `OBJECT_SHA256_MATCHES_BYTES` | L'empreinte SHA-256 recalculée sur les octets correspond au hash déclaré | **PASS** (`true`) |
| `DECLARED_SIZE_MATCHES_DISK_BYTES` | La taille déclarée correspond exactement au décompte d'octets disque | **PASS** (`true`) |
| `NO_MISSING_OBJECTS_DETECTED` | Épreuve adversariale : un objet manquant est immédiatement détecté et refusé | **PASS** (`true`) |
| `NO_EXTRA_OBJECTS_SILENTLY_IGNORED` | Épreuve adversariale : un fichier non indexé dans le CAS est détecté | **PASS** (`true`) |
| `NO_OUT_OF_ROOT_LOCATORS` | Épreuve adversariale : une traversée de chemin (`../../etc/passwd`) est refusée | **PASS** (`true`) |
| `NO_SYMLINK_TRAVERSAL` | Épreuve adversariale : un lien symbolique vers l'extérieur est refusé | **PASS** (`true`) |
| `CONTENT_SET_DIGEST_MATCHES_EXPECTED_AUTHORITY` | Le digest de l'ensemble correspond au digest canonique d'autorité (`227617d4...`) | **PASS** (`true`) |
| `EXPECTED_COUNT_MATCHES_EXACTLY` | Le décompte correspond exactement aux 2 264 candidats servables | **PASS** (`true`) |
| `COVERAGE_ON_GOVERNED_SCOPE` | La couverture s'exerce exactement sur le périmètre `SERVABLE_CANDIDATE_SET` | **PASS** (`true`) |
| `NO_MATRIX_REFUSED_CONTENT_ADMITTED` | 0 contenu refusé par le gate de servabilité (266) n'est admis | **PASS** (`true`) |
| `NO_PII_UNDECIDED_CONTENT_PROMOTED` | 0 contenu en revue PII (149) n'est promu dans le scope indexable | **PASS** (`true`) |
| `NO_CURRENTNESS_REFUSED_CONTENT_REINTRODUCED` | 0 contenu rejeté pour cause d'actualité n'est réintroduit | **PASS** (`true`) |
| `ATTESTATION_SEALED_BY_SHA256` | L'attestation est scellée par son fichier d'empreinte `.sha256` | **PASS** (`true`) |

---

## Scellement Cryptographique et Non-Fermetures Explicites

- **Attestation formelle** : `docs/reports/evidence/corpus_cas_c6_proof.json`
- **Empreinte SHA-256 scellée** : `docs/reports/evidence/corpus_cas_c6_proof.sha256`
- **Contrat de non-fermeture (`does_not_close`)** :
  Le harnais C6 et le producteur de bloqueurs (`scripts/go_live/build_qualification_blockers.py`) enregistrent impérativement :
  ```python
  does_not_close=[
      "C1",
      "C2",
      "C3",
      "COCKPIT_E2E",
      "STAGING_EXTERNE",
      "CONCURRENCE",
      "SYNC_INCREMENTALE",
      "MANIFESTE_PRODUCTION",
      "PII_UNDECIDED",
      "RELEASE_PROMOTED_REFUSED_CONTENTS",
      "GO_LIVE_READY",
  ]
  ```

---

## État des 13 Bloqueurs de Qualification post-BP

| Blocker | État | Preuve / Justification |
|---|---|---|
| **C1** (Autorité de release et couverture promue) | **OUVERT** | 26 contenus refusés promus dans la baseline release. |
| **C2** (Ingestion multilevel réelle bout en bout) | **OUVERT** | Session H2-C externe requise. |
| **C3** (Worker CLI multilevel bout en bout) | **OUVERT** | Session H2-C externe requise. |
| **C4** (Contrat de retrieval sur corpus servable) | **CLOS** | Acquis lot BM : 8 conditions searchability tenues, 2 264 contenus couverts, 55 251 vecteurs staging. |
| **C5** (Autorité d'accès et portées) | **CLOS** | Acquis lot BO : 15 épreuves adversariales de refus validées, attestation scellée. |
| **C6** (Qualification CAS et couverture magasin) | **CLOS** | **Dérivé à `closed: true` au lot BP** : 17 contrôles validés, 2 264 contenus servables vérifiés, 266 refusés exclus, 149 PII exclus, attestation scellée. |
| **COCKPIT_E2E** (Cockpit bout en bout API retrieval) | **OUVERT** | Validation e2e cockpit requise. |
| **STAGING_EXTERNE** (Staging externe qualifié) | **OUVERT** | Staging externe non ingéré. |
| **CONCURRENCE** (Concurrence et charge nominale) | **OUVERT** | Test de charge non exécuté. |
| **SYNC_INCREMENTALE** (Synchronisation incrémentale) | **OUVERT** | Test d'ingestion incrémentale non qualifié. |
| **MANIFESTE_PRODUCTION** (Manifeste production signé) | **OUVERT** | Manifeste non signé. |
| **PII_UNDECIDED** (Décision PII humaine) | **OUVERT** | 149 contenus restent non décidés. |
| **RELEASE_PROMOTED_REFUSED_CONTENTS** (Refusés promus) | **OUVERT** | 26 contenus refusés dans la baseline release. |

**Total des bloqueurs de qualification ouverts** : **8** (contre 9 avant le lot BP, et 10 avant le lot BO).

---

## Vérifications d'Hygiène, Gouvernance et Tests

1. **Gardes de gouvernance** :
   ```bash
   bash scripts/check-governance-locks.sh
   # OK: all governance locks match baseline (18 keys verified).
   bash scripts/tests/test-governance-locks.sh
   # 16 passed, 0 failed, 16 total.
   ```

2. **Unicité d'autorité (Règle R1)** :
   ```bash
   bash scripts/check-authority-uniqueness.sh
   # NEXUS-AUTHORITY-UNIQUENESS-V1: PASS
   bash scripts/tests/test-authority-uniqueness.sh
   # test-authority-uniqueness: PASS
   ```

3. **Hygiène du dépôt et linting** :
   ```bash
   bash scripts/tests/test-repository-hygiene.sh
   # All checks passed!
   ruff check scripts/
   # All checks passed!
   git diff --check
   # 0 erreur
   ```

4. **Tests automatisés** :
   - Suite unitaire C6 et constructeur de blocages : `59 passed in 0.18s`
   - Suite hermétique qualification : `83 passed, 2 skipped in 8.27s`
   - Suite globale tests scripts : `430 passed, 7 skipped`
   - Suite services/rag-pedago/tests : `3 498 passed, 4 skipped`
   - Suite services/rag-engine/tests : `100% passed (hors integration DB)`

5. **Readiness Gate** :
   ```bash
   python3 scripts/go_live/check_go_live_readiness.py --check-only
   # GO_LIVE_READY=false, go_live_qualification_blockers=8, open_prs_blocking=0, exit code 0
   python3 scripts/go_live/check_go_live_readiness.py --assert-ready
   # ASSERT_READY=failed, exit code 1 (attendu tant que la qualification n'est pas complète)
   ```

---

## Décision

**`GO_LIVE_BP_PR_OPEN`**
- La qualification CAS C6 est formellement démontrée, intègre et scellée.
- Le nombre de bloqueurs de qualification ouverts passe rigoureusement de 9 à 8.
- La PR est prête à être soumise pour revue humaine trusted.
