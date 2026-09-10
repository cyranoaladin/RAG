# Etat de readiness go-live

> **Fichier derive.** Il est regenere par
> `scripts/go_live/check_go_live_readiness.py` depuis
> `go_live_readiness_state.json`. Ne pas l editer a la main : toute
> correction faite ici serait perdue, et pire, ferait croire a une
> seconde source de verite.

`GO_LIVE_READY=false`

`main_head=0c0548ea113ab73c05cc11da5cfda55b8e05b24b`

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
| `root_owned_worktree_residues` | 2 |

## Etat calcule

| Cle | Valeur |
| --- | ---: |
| `main_head` | 0c0548ea113ab73c05cc11da5cfda55b8e05b24b |
| `computed_from_head` | 748aa4cfd90707aa690a55b602855d32e14b9919 |
| `open_prs_total` | 10 |
| `open_prs_blocking` | 6 |
| `open_prs_disposition_unknown` | 0 |
| `worktrees_total` | 3 |
| `obsolete_worktrees_remaining` | 0 |
| `root_owned_worktree_residues` | 2 |
| `pre_release_blockers` | 3 |
| `go_live_qualification_blockers` | 13 |
| `pii_undecided` | 149 |
| `program_incompatible_in_servable_set` | 1 |
| `currentness_policy_applied` | False |
| `non_pdf_servable_total` | 37 |
| `non_pdf_servable_reacquired` | 0 |
| `non_pdf_servable_complete` | False |
| `disk_free_bytes` | 97499566080 |
| `disk_used_percent` | 85 |
| `disk_policy_ok` | True |
| `production_db_writes` | 0 |
| `production_deployments` | 0 |
| `current_switch` | 0 |
| `production_facts_are_declared_not_measured` | True |
| `go_live_ready` | False |

## Ce que ce fichier ne mesure pas

Trois compteurs sont **declares par le lot**, pas mesures :
`production_db_writes`, `production_deployments`, `current_switch`.
Aucune lecture du depot ne prouve qu aucune action n a eu lieu sur la
production. Les presenter comme mesures serait une fausse assurance.
