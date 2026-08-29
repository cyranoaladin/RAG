# ADR-0054 — Posture opérationnelle : invariants d'exposition et vérification à deux faces

- **Statut** : **Accepté**
- **Date** : 2026-08-29
- **Décideur** : Nexus Réussite (opérateur)
- **Portée** : plan de données exposé (reverse proxy + API d'ingestion), méthode de vérification
- **Note de divulgation** : cet ADR est volontairement expurgé. Il consigne des
  invariants et une méthode, **jamais** l'inventaire des routes, la configuration
  du proxy, la chronologie d'un incident ni un nom d'hôte. Voir §5.

## Contexte

### Le fait nouveau que cet ADR établit

Une revue d'exposition a mis au jour deux défauts qui ont la même forme, et cette
forme est la contribution durable de ce travail.

**Premier défaut.** Un filtre de protection écrit sur le proxy couvrait les
chemins qu'il énonçait, et la vérification qui l'a suivi a sondé ces mêmes
chemins. Elle était verte. Une route d'écriture n'était pas couverte, parce que
l'inventaire de référence contre lequel la vérification aurait dû s'exercer était
lui-même incomplet : un routeur monté sans préfixe échappe à toute lecture par
préfixe, et les routes qu'il porte n'apparaissent dans aucune énumération fondée
sur les préfixes connus.

**Second défaut.** Le fichier d'identifiants du proxy était lisible par le seul
compte propriétaire, non par le compte sous lequel tournent les processus de
service. Une requête *sans* identifiants reçoit son refus **sans que le fichier
soit jamais ouvert** : toutes les sondes négatives étaient vertes sur une porte
qui n'aurait ouvert pour personne. Le service aurait été fermé à ses usages
légitimes, avec une vérification entièrement verte pour le confirmer.

Les deux défauts sont invisibles à une vérification qui n'exerce qu'une seule
face de la propriété.

### Ce que la mesure a établi par ailleurs

L'authentification applicative est appelée **dans le corps de chaque gestionnaire**,
et non imposée par le cadre (ni dépendance de routeur, ni intergiciel). C'est une
adhésion par route : chaque route doit penser à l'appeler, et une route qui
l'omet est ouverte sans que rien ne le signale. L'analyse statique exhaustive du
code monté a montré qu'aucune route d'écriture ne l'omet aujourd'hui — mais rien
dans l'architecture ne garantit qu'une route ajoutée demain l'appellera.

## Décision

### 1. Invariants d'exposition (opposables)

- **I-1.** Toute route mutante (POST, PUT, PATCH, DELETE) est placée derrière une
  authentification au niveau du proxy. Aucune exception.
- **I-2.** Toute route mutante appelle en outre un contrôle d'authentification
  applicatif, **inconditionnellement et avant tout effet**. La protection du
  proxy ne dispense pas de la protection applicative : c'est une défense en
  profondeur, et la seule couche dont on ait constaté qu'elle tenait quand
  l'autre a cédé.
- **I-3.** L'endpoint de métriques n'est jamais joignable depuis l'extérieur.
- **I-4.** Les endpoints de santé sont publics **par décision explicite**, et
  sont les seules routes non authentifiées admises.
- **I-5.** Une route dont l'authentification est appelée sous condition
  (`if <jeton configuré>`, drapeau d'environnement, mode développement) n'est pas
  réputée protégée tant qu'un second contrôle inconditionnel n'échoue pas en
  fermeture quand la condition n'est pas remplie.

### 2. Règle de vérification (opposable)

- **V-1 — Deux faces.** Une fermeture se vérifie sur ses deux faces : *refuse
  sans identifiants*, **et** *laisse passer avec*. Une campagne de sondes toutes
  négatives ne prouve pas une fermeture ; elle est compatible avec une porte
  murée. Le versant positif doit exercer le chemin applicatif jusqu'au bout — y
  compris les mises à niveau de protocole, qu'une authentification peut casser
  sans que rien d'autre ne le montre.
- **V-2 — Périmètre reconstruit, jamais repris.** L'inventaire contre lequel une
  fermeture se vérifie est **reconstruit depuis les routeurs effectivement
  montés**, jamais repris d'une table antérieure, jamais dérivé des préfixes que
  le filtre lui-même énonce. *Une consigne de vérification porte le domaine de
  l'inventaire qui la fonde.*
- **V-3 — Sonder le périmètre dû, pas le périmètre écrit.** Vérifier les chemins
  que l'on vient de protéger ne mesure rien. La sonde s'exerce ligne à ligne sur
  l'inventaire complet.
- **V-4 — Distinguer l'origine du refus.** Un refus émis par le proxy et un refus
  émis par l'application ne prouvent pas la même chose. La sonde doit les
  distinguer par un signal non ambigu, faute de quoi une couche masque la
  défaillance de l'autre.
- **V-5 — Corps valide.** Lorsque la validation du format précède l'appel
  d'authentification, une sonde à corps invalide mesure la validation, pas
  l'authentification. Le versant applicatif se vérifie avec un corps bien formé.
- **V-6 — Domaine porté par la synthèse.** Une phrase de synthèse porte le
  domaine de la mesure qui la fonde. C'est dans le résumé, non dans le corps du
  rapport, que les domaines se perdent — et c'est le résumé qu'on cite.

### 3. Corrections structurelles à porter

Ces trois points ne sont pas des dettes à tracer : ce sont des conditions de
déploiement de la version courante.

- **C-1.** Le volume de données applicatives de l'ingestor est monté en lecture
  seule. La base de catalogue documentaire n'a donc jamais pu être créée, et les
  routes d'administration du catalogue échouent en 500 depuis la mise en service.
  Conséquence de gouvernance : **il n'existe aucune trace persistante
  d'ingestion**, ce qui prive toute enquête ultérieure de sa source la plus
  directe. À corriger dans la définition de composition **avant** bascule, sans
  quoi le même montage reproduira le même défaut.
- **C-2.** Les métriques applicatives ne sont pas fusionnées entre les processus
  de service (chaque processus tient son propre registre). Toute supervision
  sous-compte d'un facteur égal au nombre de processus et affiche de fausses
  remises à zéro. À corriger dans le même passage, puisque c'est sur ces
  tableaux que la production sera jugée après bascule.
- **C-3.** Le format de journalisation du proxy ne portait pas le nom d'hôte
  virtuel. Sur un serveur qui en héberge une quinzaine écrivant dans un fichier
  commun, aucune requête n'était attribuable à un service. **Corrigé.** Invariant
  associé : tout format de journal d'un service exposé porte le nom d'hôte
  virtuel et conserve la ligne de requête complète, chaîne de requête comprise.

### 4. Traçabilité des identifiants

Un identifiant partagé entre plusieurs personnes ne permet aucune attribution.
Lorsqu'un même identifiant déverrouille à la fois une interface de consultation
et une surface d'écriture, la question n'est pas hypothétique. Invariant : dès
que l'accès concerne plus d'une personne, un compte par personne, et rotation à
la sortie de toute phase de mise au point.

### 5. Divulgation : la posture opérationnelle est une quatrième catégorie

Notre grille de divulgation retenait trois catégories à ne jamais verser au dépôt
public : **secrets**, **données personnelles**, **identifiants d'accès**. Nous en
ajoutons une quatrième : **la posture opérationnelle**.

L'inventaire des routes d'un service, sa topologie de proxy, l'emplacement de ses
défenses et l'historique de ses faiblesses ne sont ni un secret, ni une donnée
personnelle, ni un identifiant. Publiés dans un dépôt public à côté d'un nom
d'hôte joignable, ce sont une carte.

Règle : le rapport d'exposition complet va à l'opérateur, **hors dépôt**. Ce qui
entre au dépôt est l'enregistrement de décision — invariants, méthode,
corrections structurelles — sans inventaire de routes, sans configuration de
proxy, sans chronologie d'incident, sans nom d'hôte.

*La mémoire institutionnelle est dans les invariants, pas dans la carte.*

## Conséquences

**Positives.**

- Les invariants I-1 à I-5 et les règles V-1 à V-6 sont opposables en revue : une
  fermeture livrée avec des sondes d'une seule face, ou vérifiée contre un
  inventaire repris plutôt que reconstruit, est refusable sans discussion.
- La quatrième catégorie de divulgation donne une réponse stable à une question
  qui se reposera à chaque rapport d'infrastructure.
- C-1 explique rétroactivement l'absence de trace d'ingestion, et transforme un
  constat d'enquête en condition de déploiement.

**Coûts et limites.**

- I-2 reste une adhésion par route tant que le contrôle est appelé dans le corps
  des gestionnaires. Cet ADR ne l'impose pas par construction ; il en fait un
  invariant vérifiable. Le porter au niveau du cadre (dépendance de routeur ou
  intergiciel avec liste blanche explicite des routes publiques) est la suite
  logique, et n'est pas décidé ici.
- V-2 coûte une reconstruction d'inventaire à chaque vérification. C'est le prix
  de la seule étape qui a trouvé les routes manquantes.
- La rétention des journaux du proxy et des conteneurs reste inférieure à la
  durée pendant laquelle une exposition peut passer inaperçue. Les compteurs
  applicatifs cumulatifs y échappent tant que le processus ne redémarre pas —
  c'est une propriété fragile, sur laquelle on ne fonde pas une politique de
  conservation.

## Alternatives écartées

- **Supprimer les copies de configuration inactives** plutôt que les aligner sur
  la posture de sécurité des fichiers actifs. Écarté : la suppression casserait
  un usage futur inconnu, tandis que l'alignement est inerte aujourd'hui et sûr
  demain. Une mine désamorcée vaut mieux qu'une mine déplacée.
- **Déposer le rapport d'exposition complet expurgé de ses seuls identifiants.**
  Écarté : voir §5. L'expurgation des identifiants ne retire pas la carte.
- **Se satisfaire de l'inventaire de routes existant.** Écarté : c'est
  exactement ce qui avait laissé passer les routes non couvertes.
