# Etat de readiness go-live

> **Fichier derive.** Il est regenere par
> `scripts/go_live/check_go_live_readiness.py` depuis
> `go_live_readiness_state.json`. Ne pas l editer a la main : toute
> correction faite ici serait perdue, et pire, ferait croire a une
> seconde source de verite.

`GO_LIVE_READY=false`

`main_head=cc5f95eb61637026829ae7c984b6e8bca71b23ee`

## Ce qui empeche le go-live

| Raison | Valeur |
| --- | ---: |
| `pre_release_blockers` | 3 |
| `go_live_qualification_blockers` | 13 |
| `pii_undecided` | 149 |
| `program_incompatible_in_servable_set` | 1 |
| `currentness_policy_applied` | False |
| `non_pdf_servable_reacquired` | 0 |
| `open_prs_blocking` | 6 |

## Etat calcule

| Cle | Valeur |
| --- | ---: |
| `state_freshness_kind` | COMMITTED_SNAPSHOT |
| `snapshot_contains_self_commit` | False |
| `snapshot_is_operational_current` | False |
| `snapshot_freshness_note` | Instantane derive. Genere AVANT le commit qui le contient, il ne peut donc jamais etre l etat operatoire de ce commit. Pour une decision de deploiement, relancer le script en direct. |
| `main_head` | cc5f95eb61637026829ae7c984b6e8bca71b23ee |
| `origin_main_at_generation` | cc5f95eb61637026829ae7c984b6e8bca71b23ee |
| `evaluated_ref` | go-live/readiness-freshness |
| `evaluated_head` | cc5f95eb61637026829ae7c984b6e8bca71b23ee |
| `open_prs_total` | 10 |
| `open_prs_blocking` | 6 |
| `open_prs_disposition_unknown` | 0 |
| `worktrees_total` | 3 |
| `obsolete_worktrees_remaining` | 0 |
| `root_owned_worktree_residues` | 0 |
| `pre_release_blockers` | 3 |
| `go_live_qualification_blockers` | 13 |
| `pii_undecided` | 149 |
| `program_incompatible_in_servable_set` | 1 |
| `currentness_policy_applied` | False |
| `non_pdf_servable_total` | 37 |
| `non_pdf_servable_reacquired` | 0 |
| `non_pdf_servable_complete` | False |
| `disk_free_bytes` | 97753276416 |
| `disk_used_percent` | 85 |
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

Pour une decision de deploiement :

```
python3 scripts/go_live/check_go_live_readiness.py --check-only
python3 scripts/go_live/check_go_live_readiness.py \
    --verify-snapshot docs/reports/go_live/go_live_readiness_state.json
```

Un instantane perime n autorise rien, et un instantane a jour non plus :
il ne fait que concorder.

## Ce que ce fichier ne mesure pas

Trois compteurs sont **declares par le lot**, pas mesures :
`production_db_writes`, `production_deployments`, `current_switch`.
Aucune lecture du depot ne prouve qu aucune action n a eu lieu sur la
production. Les presenter comme mesures serait une fausse assurance.
