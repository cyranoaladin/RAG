# Processus ouverts autour de la base de revue

Les valeurs font autorité dans `staging_preservation_open_processes.json`.

## Pourquoi ce document existe

Un shell laissé en vie sans explication est un angle mort : personne ne sait
s'il écrit, s'il attend, ou s'il va détruire quelque chose. Sur ce poste, la
question n'est pas théorique — la base qui rend la revue PII réamorçable vit
dans un conteneur au volume **anonyme**. Rien ne le nomme, donc rien ne le
protège d'un élagage.

## Règles

Le conteneur `nexus-drive-staging-v2` n'est jamais arrêté ni supprimé, et
aucun élagage global de conteneurs ou de volumes n'est lancé sur ce poste.

Une sauvegarde ou une restauration en cours n'est jamais interrompue sans
preuve qu'elle est terminée : une archive tronquée a l'apparence d'une
sauvegarde.

Tout shell résiduel est soit fermé, soit justifié — PID, commande, rôle,
sortie attendue, risque. Un conteneur créé pour établir une preuve est
supprimé après usage ; la base protégée ne l'est jamais.

## Constat

Le seul shell résiduel observé pendant la préservation était un observateur de
CI, en lecture seule via l'API GitHub, sans effet sur le dépôt ni sur les
conteneurs. Il s'est terminé de lui-même à la fin de la CI. Le conteneur de
preuve de restauration a été supprimé après usage ; la base protégée est
intacte.
