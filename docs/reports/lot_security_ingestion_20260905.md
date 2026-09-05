# RAG v2 — ingestion distante et parseurs, 5 septembre 2026

## Provenance et périmètre

Base canonique : cyranoaladin/RAG, commit `27a4558a1abca304d415240b9ec0c06000cd2db5`, identique au manifeste de la release active. Les 21 modules Python ingestor de cette base correspondent à la release. RAG-backup se présente explicitement comme miroir de sauvegarde, non comme dépôt de développement. Cette branche part de la release utilisée ; elle ne prétend pas intégrer le main distant plus récent.

Le correctif couvre uniquement les trois entrées URL (API historique, endpoint v2, tâche Celery), le contrôle des images et quatre dépendances. Aucune modification du schéma, des collections, du retrieval ou de la gouvernance pédagogique. Les deux images sont dérivées de leurs images exactes respectives : la divergence préexistante du retrieval worker est conservée et doit être vérifiée par empreinte.

## Corrections

- Validation de toutes les adresses DNS, refus des réseaux non publics et des identifiants dans les URLs ; connexion à une IP validée, Host et SNI d'origine, certificats vérifiés.
- Redirections manuelles bornées, nouvelle validation à chaque saut, absence de proxy hérité de l'environnement, taille et temps réseau bornés. Un watchdog ferme la socket pour les en-têtes lents ; lecture partielle avec contrôle du budget et refus des réponses tronquées. Le résolveur système conserve son propre délai : le budget annoncé ne constitue pas une borne murale absolue du DNS.
- Refus des images invalides ou dépassant le nombre maximal de pixels avant OCR ; timeout OCR explicite.
- pypdf 4.2.0 vers 6.14.2 ; Pillow 10.4.0 vers 12.3.0 ; pdfplumber 0.11.4 vers 0.11.9 ; pdfminer.six 20231228 vers 20251230. Les roues CPython 3.11 / Linux sont verrouillées par SHA256 et installées sans résolution de dépendances. Aucune cascade LangChain.

## Vérification

TDD : refus SSRF, bornes images, URL Unicode, corps lent, en-têtes lents et corps tronqué. Seize tests ciblés réussis et Ruff réussi dans l'environnement local. La suite historique ciblée de six fichiers comporte 79 tests : le témoin image original les réussit avec les trois fixtures de collections canoniques ; sans ces fixtures, cinq échecs étaient reproduits aussi sur le témoin.

Les premières images candidates Python 3.11 passent pip check, PDF texte via PyPDFLoader, tableau 2x2 pdfplumber, crop et chemin multimodal PDF, OCR Tesseract réel JPEG/PNG/WEBP, image invalide, borne pixels et refus rapide du PDF inline malformé (boucle bornée à 2 secondes reproduite sous pypdf 4.2.0). Les images finales doivent repasser ces contrôles et la suite historique ; leurs preuves et empreintes sont des artefacts opérationnels distincts du commit, pour éviter une provenance circulaire.

## Limites de sécurité conservées

La version Starlette historique reste exposée conditionnellement aux vulnérabilités de traitement multipart ; la Basic Auth Nginx précède le parseur et des limites de corps existent, sans remplacer une correction compatible. Les chemins LangChain de sérialisation et Unstructured MSG/URL visés par les alertes critiques n'ont pas été identifiés dans les modules actifs examinés. Ce constat borné ne constitue pas une déclaration d'absence de vulnérabilité de toutes les bibliothèques.

Les assertions fonctionnelles utilisent des documents synthétiques et des clients DB/LLM simulés lorsque nécessaire ; aucune ingestion métier en production n'est réalisée par ces tests.

## Déploiement et retour arrière

Préparation seulement. Le futur checkpoint doit détenir le verrou opérationnel commun, vérifier les deux images et les sauvegardes/restaurations récentes, ainsi que l'absence de dérive des montages, réseaux, commandes et environnements (comparaison privée, sans secrets dans les journaux).

L'arrêt gracieux de l'API doit fermer les entrées de tous les producteurs, y compris les clients Docker internes, et attendre les BackgroundTasks Drive. Celery doit terminer les tâches actives/réservées/planifiées et conserver sa file. Un simple compteur Celery vide ne prouve pas le drainage de Drive. Aucun SIGKILL ni recréation si le drainage n'est pas terminé. Un SIGTERM commencé ne peut être annulé : un dépassement de délai exige un état opérationnel explicite, sans prétendre à un rollback immédiat.

Recréation des seuls services ingestor et worker, projet Compose explicite, images immuables, sans down, remove-orphans, pull ou build au checkpoint. Retour aux deux images précédentes et configurations sauvegardées ; aucune restauration DB automatique car aucune migration de données.

Le script manuel deploy-prod.sh historique reste dangereux : projet implicite et remove-orphans. Prévoir une garde serveur durable sauvegardant l'original et refusant cet appel au profit du wrapper verrouillé. Ne pas activer ce mécanisme depuis cette branche sans checkpoint.

## Déclenchements GitHub

À cette base, le seul workflow racine ci.yml s'exécute pour les push main/lot-*/** et les PR vers main ; un push de cette branche fix/security-ingestion-boundaries ne déclenche pas de déploiement. Les workflows imbriqués dans le service ne sont pas des workflows GitHub actifs. Le main distant possède d'autres workflows et n'est pas modifié par ce correctif. Aucun merge ni déclenchement de workflow n'est réalisé ici.
