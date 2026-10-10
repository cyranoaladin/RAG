# Lot — préflight de la cible d'inférence dédiée

## Périmètre et origine

Base fraîche `origin/main=b08c4def985af1a5d471402f80537387a661106d`, tree
`cdfa4f3dbebfb42196558ff49ac57276a8680fbe`, vérifiés le
2026-10-10 UTC. Le profil CUDA de la PR #317 est déjà fusionné. Il exige un
GPU NVIDIA dans Compose et refuse au démarrage un repli CPU des modèles ; il ne
qualifie pas une machine distante à lui seul.

Le présent lot ajoute un seul préflight SSH en lecture seule :
`scripts/qualification/preflight_dedicated_inference_target.py`. Il compare
l'identité de l'hôte et l'empreinte des octets exacts de `/etc/machine-id` à
des valeurs **obtenues indépendamment**, refuse l'hôte de production
historique, relève CPU/RAM, GPU/VRAM/pilote, la présence de
`nvidia-container-cli` et du runtime Docker `nvidia`. Le code ne lance aucun
conteneur, ne construit aucune image, ne contacte aucune base et n'affiche
aucun secret. Un inventaire incomplet est refusé.

Commande à exécuter une fois la nouvelle cible identifiée et son empreinte
connue par une source indépendante de cette sonde :

```bash
python3 scripts/qualification/preflight_dedicated_inference_target.py \
  --ssh-alias ALIAS_GPU_DEDIE \
  --expected-hostname NOM_HOTE_ATTENDU \
  --expected-machine-id-sha256 EMPREINTE_SHA256_DEJA_PINNEE \
  --production-hostname korrigo
```

Un résultat `HOST_GPU_PREFLIGHT_PASS=true` atteste seulement un inventaire
apparent. La réservation GPU réelle du conteneur, le préchargement E5 et
reranker, le health, la qualité retrieval, le warmup et C0 restent des
preuves distinctes à obtenir sur le candidat final. `LOAD_PASS` reste
toujours `false` dans cette sonde.

## Preuves exécutées

- TDD : le test du parseur de décision a d'abord échoué car le module était
  absent ; le sabotage `docker_runtimes=null` a ensuite reproduit un défaut
  de fermeture ; le test d'empreinte a reproduit la divergence entre le hash
  du fichier brut et celui du texte dépouillé. Les correctifs minimaux ont
  suivi ces échecs. La revue de la PR a ensuite relevé l'alias SSH traité
  comme option ; deux tests rouges ont précédé l'ajout du terminateur `--`
  et du refus d'un alias commençant par `-`.
- Venv neuf local au worktree, sans installation éditable. Neuf tests
  `unittest` passent, `ruff check` et `git diff --check` passent.
- Probe live read-only le 2026-10-10T21:14:41Z via l'alias existant
  `nexus-prod-direct` : `hostname=korrigo`, 12 CPU, 65 752 848 KiB RAM,
  aucun GPU détecté, aucun runtime Docker `nvidia`, aucun
  `nvidia-container-cli`. L'empreinte `/etc/machine-id` brute concordait
  avec la valeur de référence obtenue séparément. Verdict :
  `HOST_GPU_PREFLIGHT_PASS=false` avec motifs
  `not_dedicated_from_production`, `nvidia_gpu_unavailable`,
  `nvidia_container_runtime_unavailable`. Le code de sortie était 1.

## Gate restant

L'accès SSH à une machine d'inférence **distincte** de `korrigo`, son nom
attendu et une empreinte machine indépendante ne sont pas connus dans les
accès disponibles. Aucun quota CPU/RAM, digest CUDA final, preuve de
préchargement ni mesure C0 ne peut être fixé ou déclaré vert à partir de cet
hôte historique. Le budget C0 versionné reste inchangé : 8 clients,
240 requêtes, p50 ≤ 3 000 ms, p95 ≤ 6 000 ms, p99 ≤ 7 500 ms, zéro erreur
et timeout, au plus 10 connexions DB.

Ce lot n'a modifié ni staging ni production et ne vaut pas une autorisation
de déploiement.
