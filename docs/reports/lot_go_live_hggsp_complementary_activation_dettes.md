# Dette préexistante — disponibilité disque du contrôle go-live général

Le 28 septembre 2026, les quatre tests suivants de
`scripts/tests/test_go_live_readiness.py` échouent par présence inattendue de
`disk_policy_ok` dans `blocking_reasons` :

- `test_tout_ferme_donne_go_live_ready` ;
- `test_assert_ready_rend_zero_seulement_si_tout_est_ferme` ;
- `test_le_plan_se_ferme_quand_tout_se_ferme` ;
- `test_fermer_la_gouvernance_ne_rend_pas_le_corpus_interrogeable`.

La même commande ciblée a été relancée dans un worktree jetable au commit
parent exact `2bc65c9386aafb80d66ce25096b50c75eeeb5412` : **les quatre
mêmes tests échouent**, sans aucun changement de ce lot. Le disque local
affichait 97 % d'utilisation et 30 Go libres. Le contrôle go-live conserve
son refus ; ce lot ne modifie ni sa politique ni ses tests.

Commande de comparaison :

```bash
pytest -q scripts/tests/test_go_live_readiness.py -k \
  'tout_ferme_donne_go_live_ready or assert_ready_rend_zero_seulement_si_tout_est_ferme or le_plan_se_ferme_quand_tout_se_ferme or fermer_la_gouvernance_ne_rend_pas_le_corpus_interrogeable'
```

Les tests HGGSP et les autres suites concernées sont distincts de cette dette.
