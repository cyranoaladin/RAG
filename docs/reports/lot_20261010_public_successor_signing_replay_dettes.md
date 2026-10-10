# Dette préexistante de typage — signer production V2

La base importée de la PR #325, commit `e8323959acaf605e539b6717ab8173bd40e785ba`, présente **17 erreurs mypy** sur `services/rag-engine/scripts/sign_production_readiness_manifest_cli.py`. Commande de constat : `git show e8323959:services/rag-engine/scripts/sign_production_readiness_manifest_cli.py > /tmp/rag_sign_production_e832.py` puis `.venv/bin/mypy /tmp/rag_sign_production_e832.py --follow-imports=silent --ignore-missing-imports`. Le contrôle rapporte `Found 17 errors in 1 file` ; les erreurs proviennent des alias dynamiques `V2ReleaseMaterial` et `VerifiedV2ReleaseMaterial` et de leurs attributs non inférés.

Sur ce lot, la même commande mypy appliquée au fichier modifié rapporte également **17 erreurs**, aucune nouvelle. Le pont `public_successor_signing_replay.py` et le signer staging passent mypy sans erreur. La dette de typage préexistante n'est pas corrigée dans ce sous-lot de signature.
