# Politique de divulgation — ce qui ne se versionne pas

## La règle

> **Les rapports opérationnels et de diagnostic décrivent une machine et une
> personne, pas un système. Sur un dépôt public, ils ne se versionnent pas
> nommément.**

Ce dépôt est **public** (`github.com/cyranoaladin/RAG`). Tout ce qui y entre est
lisible par quiconque, indexable, et reste atteignable par SHA après réécriture
d'historique.

## Trois catégories, pas une

Un contrôle anti-secret ne couvre qu'un tiers du risque.

| # | Catégorie | Exemples | Pourquoi |
|---|---|---|---|
| 1 | **Secrets** | clés privées, jetons, mots de passe | catégorie classique, généralement couverte |
| 2 | **Donnée personnelle** | SSID, **BSSID / MAC**, IP publiques, adresses d'overlay, e-mails nominatifs, chemins `/home/<nom>` | décrit *cette personne* ou *cette machine* |
| 3 | **Identifiants d'accès** | identifiant de dossier Drive, URL de partage, identifiant de bucket | ni secret ni donnée personnelle — **et pourtant un accès** |

### Ce qui a motivé cette politique

Le 28/08/2026, un contrôle anti-secret est passé vert sur une branche poussée
vers ce dépôt public. Elle exposait :

- cinq **SSID Wi-Fi** de la machine opérateur ;
- une **adresse e-mail nominative** ;
- un **identifiant de dossier Google Drive** ouvrant le corpus complet **en
  écriture** à quiconque disposait du lien.

Le contrôle avait raison sur son domaine — aucun secret — et ce domaine n'était
pas celui du risque. C'est le défaut que ce dépôt rencontre à répétition : **un
contrôle qui affirme plus qu'il n'a vérifié.**

Priorité au sein de la catégorie 2 : un **BSSID** est plus grave qu'un SSID. Les
bases publiques de géolocalisation les indexent avec une précision bien
supérieure, et un BSSID ne change pas quand on renomme son réseau.

## Le contrôle

```bash
python3 scripts/check_disclosure_patterns.py --base origin/main   # diff
python3 scripts/check_disclosure_patterns.py --all                # arbre entier
```

Intégré à `scripts/ci-local.sh` sous la cible `disclosure-patterns`.

### Un vert ne signifie pas « rien à signaler »

Le contrôle cherche des **motifs connus**. Un résultat vert établit qu'aucun
motif de sa grille n'a été détecté — **jamais** que le diff est exempt de
divulgation. Une grille de motifs est un **plancher, pas une preuve**.

Cette phrase est imprimée à chaque exécution, y compris verte. Sans elle, le
contrôle deviendrait le prochain qui affirme plus qu'il n'a vérifié.

Une divulgation d'une forme non anticipée y échappera. La relecture humaine reste
requise sur la question : *ce paragraphe décrit-il un système, ou une machine et
une personne ?*

### Faux positifs : un contrôle qui crie au loup cesse de protéger

La première version du motif Drive attrapait tout SHA-1 git commençant par `1` :
**22 faux positifs pour un vrai constat**. Un contrôle bruyant se fait ignorer,
puis désactiver. Le motif exige désormais la marque du base64url — une majuscule,
un `-` ou un `_` — ce qui distingue un identifiant Drive d'une empreinte
hexadécimale.

Tout ajout de motif doit être éprouvé **dans les deux sens** : sur des cas qui
doivent être détectés, et sur des cas bénins qui doivent être ignorés.

## Anonymiser sans affaiblir

Un raisonnement ne perd rien à l'anonymisation.

| Au lieu de | Écrire |
|---|---|
| `` `Tenda_E6CDE0`, `Flybox-8A8BE6`, … `` | « cinq box grand public de fournisseurs d'accès » |
| `dossier Drive 1OEwXePZors4rl…` | « dossier Drive du corpus, identifiant hors dépôt » |
| `propriétaire prenom.nom@domaine` | « le compte propriétaire du corpus » |
| `/home/<nom>/rag-model-artifacts/…` | `$RAG_EMBEDDING_MODEL_ARTIFACT_DIR` |

La dette n°9 continue de nommer `192.168.0.1` et `192.168.1.1` comme passerelles
capturées par un bridge Docker : **c'est l'argument, et il est intact**. Les noms
des box n'y ajoutaient rien.

Ce qui décrit le **système** reste : plages RFC1918, noms de périphériques
(`nvme0n1p3`), architectures, empreintes, versions. Ce qui décrit **cette
machine-ci** ou **cette personne-ci** sort.

## Chemins de machine personnelle — un motif, pas trois incidents

Trois défauts de code pointaient une machine personnelle, dans trois scripts :

```
--cache-dir            /tmp/nexus_corpus_pdf_cache
NEXUS_SEALED_CORPUS_ROOT   ~/Téléchargements/NEXUS_RAG_GDRIVE_READY
--model-path           /home/<nom>/rag-model-artifacts/…
```

Trois symptômes du même défaut. **Un défaut est une décision** : celle de deviner
un chemin plutôt que de le demander.

**Correctif uniforme** : lire la configuration, défaut neutre ou absent, **échec
explicite** si non configuré. Ne jamais deviner — un chemin deviné fait dépendre
une opération gouvernée d'un poste précis, et échoue tard, dans un contexte où le
symptôme ne désigne pas la cause.

`AGENTS.md` l'exige déjà pour les chemins absolus. La règle s'étend aux
**emplacements volatils** (`/tmp`) et aux **dossiers utilisateur localisés**
(`~/Téléchargements` n'existe pas sur un système en anglais).

## Si une divulgation est constatée après poussée

1. **Réécrire** la branche — anonymiser, puis `push --force-with-lease`.
2. **Savoir ce que cela n'efface pas** : les anciens objets restent atteignables
   par SHA sur GitHub. Non référencés n'est pas supprimé, et le délai de collecte
   n'est pas contractuel. Une purge réelle exige une demande au support GitHub
   citant les SHA.
3. **Traiter la cause hors dépôt** si l'élément était un accès : réécrire
   l'historique ne referme pas un partage Drive ouvert. La réécriture réduit
   l'exposition future ; elle ne défait pas l'exposition passée.
4. **Une seule réécriture**, couvrant tout : une seconde poussée forcée pour une
   seconde trouvaille est pire que la première. Auditer d'abord, corriger ensuite.
