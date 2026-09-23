# Lot CW — dettes préexistantes

## Seuil disque du gate de readiness go-live

- Cibles : `go-live-readiness-gate`, `script-tests`
- Tests : `scripts/tests/test_go_live_readiness.py` —
  `test_tout_ferme_donne_go_live_ready`,
  `test_assert_ready_rend_zero_seulement_si_tout_est_ferme`,
  `test_le_plan_se_ferme_quand_tout_se_ferme`,
  `test_fermer_la_gouvernance_ne_rend_pas_le_corpus_interrogeable`
- Cause : `blocking_reasons` contient `disk_policy_ok` ; la machine d'exécution
  a moins de 40 Go libres (19 à 28 Go pendant le run).
- Antériorité : mêmes 4 échecs, même cause, sur le commit parent
  `d7611667daef6af45c62e67afcd1db0fd5b3dc5d` (worktree détaché, le 2026-09-23).
- Portée : environnementale ; ce lot ne touche aucun fichier lu par ce gate.
- Fermeture : libérer de l'espace disque au-delà de 40 Go, puis rejouer.
