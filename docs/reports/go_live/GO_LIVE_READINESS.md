# Etat de readiness go-live

> **Fichier derive.** Il est regenere par
> `scripts/go_live/check_go_live_readiness.py` depuis
> `go_live_readiness_state.json`. Ne pas l editer a la main : toute
> correction faite ici serait perdue, et pire, ferait croire a une
> seconde source de verite.

`GO_LIVE_READY=false`

`main_head=c0ee319299c570d5b110c1543ddf1f1c7ca1c891`

## Ce qui empeche le go-live

| Raison | Valeur |
| --- | ---: |
| `go_live_qualification_blockers` | 4 |
| `release_promoted_refused_contents` | 4 |

## Etat calcule

| Cle | Valeur |
| --- | ---: |
| `state_freshness_kind` | COMMITTED_SNAPSHOT |
| `snapshot_contains_self_commit` | False |
| `snapshot_is_operational_current` | False |
| `snapshot_freshness_note` | Instantane derive. Genere AVANT le commit qui le contient, il ne peut donc jamais etre l etat operatoire de ce commit. Pour une decision de deploiement, relancer le script en direct. |
| `main_head` | c0ee319299c570d5b110c1543ddf1f1c7ca1c891 |
| `origin_main_at_generation` | c0ee319299c570d5b110c1543ddf1f1c7ca1c891 |
| `evaluated_ref` | go-live/import-approved-pii-currentness-decisions |
| `evaluated_head` | c0ee319299c570d5b110c1543ddf1f1c7ca1c891 |
| `input_digests` | {'docs/reports/handoff/servability_matrix_v1.json': '5dc4c8983ec8feb4f7ce1a76babba4b75ff2840af00b4de880d4120c19d14f9c', 'docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json': 'c2fb30dd39a347a82c7e9bed96933610444ce784719ddd73b478694010896018', 'docs/reports/go_live/non_pdf_retention_policy.json': '1b400ecc48f72c9b2ec6d6b1f6ec68d82f22dbcbd726a5ef69c5379c3fe41017', 'services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml': '4226aba5cd13d60558d049df73d4df06554bc1a6d603111d02de166f1db17c29', 'docs/reports/go_live/open_pr_dispositions.json': '223f4824bf25dfea729e73fa22fce159119214528899b79ce94b53a20c3d84f5', 'docs/reports/go_live/qualification_blockers.json': 'e7bb2d8f50e08b3a9abfb894583493cf9bc3a584ad017e2c4557d875ba23f99b', 'docs/reports/go_live/rag_searchability_gap.json': 'f045f2e68ddd5430953da3f46ef9586b2fcbdf371cdd3e6ed49d3f65072d2264', 'docs/reports/go_live/expected_worktrees.json': '5f04ffa232cf84f4a0246c958ee984b7525b50bfc172e0a1ab6f898848662dcc'} |
| `open_prs_total` | 10 |
| `open_prs_blocking` | 0 |
| `open_prs_disposition_unknown` | 0 |
| `worktrees_total` | 3 |
| `obsolete_worktrees_remaining` | 0 |
| `root_owned_worktree_residues` | 0 |
| `pre_release_blockers` | 0 |
| `go_live_qualification_blockers` | 4 |
| `servable_candidate_count` | 2286 |
| `pii_undecided` | 0 |
| `program_incompatible_in_servable_set` | 0 |
| `program_incompatible_total` | 1 |
| `program_incompatible_refused_by_matrix` | 1 |
| `promoted_content_set_source` | scripts/qualification/compute_promoted_content_set.py |
| `promoted_content_set_sha256` | d06d6051e7037372acf4dca4675a1c999c198129433d68491221a9d03bb821cd |
| `promoted_content_set_size` | 319 |
| `promoted_release_authority_mechanism` | REGISTRY_FILE |
| `promoted_release_registry_source` | DEFAULT |
| `currentness_policy_applied` | True |
| `release_promoted_refused_contents` | 4 |
| `release_promoted_refused_by_verdict` | {'BLOCKED_NOT_CURRENT_BY_SOURCE': 4} |
| `release_promoted_refused_by_currentness` | 4 |
| `release_reseal_required` | True |
| `release_promoted_unmatched_in_matrix` | 0 |
| `release_impact_measurable` | True |
| `rag_searchable` | True |
| `staging_vectors_present` | 55251 |
| `target_scope_searchable` | True |
| `production_searchable` | False |
| `retrieval_contract_validated` | True |
| `rag_searchability_blocker` | False |
| `non_pdf_servable_total` | 37 |
| `non_pdf_servable_reacquired` | 37 |
| `non_pdf_servable_complete` | True |
| `non_pdf_retention_policy_versioned` | True |
| `non_pdf_retention_reason` | MEASURED |
| `non_pdf_retention_store_named` | True |
| `disk_free_bytes` | 163063017472 |
| `disk_used_percent` | 78 |
| `disk_policy_ok` | True |
| `production_db_writes` | 0 |
| `production_deployments` | 0 |
| `current_switch` | 0 |
| `production_facts_are_declared_not_measured` | True |
| `go_live_ready` | False |

## Ce fichier n autorise aucun deploiement

L autorite operatoire est le script, **relance en direct**. Ce fichier
est un instantane : genere avant le commit qui le contient, il ne peut
pas etre l etat operatoire de ce commit.

Trois modes, et un seul est un garde :

| Mode | Code de retour | Role |
| --- | --- | --- |
| `--check-only` | 0 des que le calcul s execute | diagnostic |
| `--verify-snapshot` | 0 si concordant | concordance |
| `--assert-ready` | 0 seulement si pret, 1 sinon, 2 si entree manquante | **garde** |

**Seul `--assert-ready` peut conditionner un deploiement.**
`--check-only` rend 0 meme quand rien n est pret : c est un faux vert
si on s en sert comme garde. Et un instantane, perime ou non,
n autorise rien : il ne fait que concorder.

```
python3 scripts/go_live/check_go_live_readiness.py --assert-ready
```

## Ce que ce fichier ne mesure pas

Trois compteurs sont **declares par le lot**, pas mesures :
`production_db_writes`, `production_deployments`, `current_switch`.
Aucune lecture du depot ne prouve qu aucune action n a eu lieu sur la
production. Les presenter comme mesures serait une fausse assurance.
