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

### L'énoncé du motif

Les deux défauts, et tous ceux que la même campagne a trouvés ensuite, se ramènent à une
seule erreur :

> **On a interrogé le support au lieu d'interroger la propriété.**

« Un contrôle qui affirme plus qu'il n'a vérifié » décrit le symptôme. Cette formulation-ci
nomme le mécanisme, et elle a l'avantage de rendre l'erreur reconnaissable *avant* qu'elle
produise un faux vert. Le support est ce qui est commode à interroger — un fichier, une
commande locale, une table déjà écrite, une variable qu'on croit à jour. La propriété est ce
qu'on veut réellement établir.

Relevé des occurrences observées dans une seule campagne :

| on a interrogé le support… | …au lieu de la propriété |
|---|---|
| les chemins que le filtre énonce | le périmètre que le filtre doit couvrir |
| une table de routes reprise d'un rapport antérieur | les routeurs effectivement montés |
| des sondes sans identifiants | la fermeture **et** l'ouverture |
| l'existence d'un fichier portant un numéro | la réservation de ce numéro, faite en prose |
| une sonde depuis la machine elle-même vers sa propre adresse publique | l'accessibilité depuis l'extérieur — la boucle locale court-circuite le filtre |
| la première ligne d'un nom de chaîne dans un fichier de règles | la politique de la table concernée |
| une liste de noms de fonctions de garde écrite à la main | les fonctions qui refusent effectivement l'accès, dérivées du module de sécurité |
| l'état de `HEAD` supposé inchangé depuis son dernier commit | l'état de `HEAD` mesuré avant d'y toucher |
| un répertoire de recherche commode | l'emplacement réel de l'artefact cherché |

La dernière ligne du tableau est la plus instructive : l'erreur ne frappe pas que le système
vérifié. Elle frappe aussi **l'instrument de vérification** — un outil qui énumère au lieu de
dériver, un contrôle qui s'exempte de son propre balayage. D'où le corollaire :

> Un garde-fou dérive ses critères de la source qui fait autorité, jamais d'une énumération
> écrite à la main ; et il s'applique à lui-même.

## Décision

### 1. Invariants d'exposition (opposables)

- **I-1. La couche proxy échoue fermée.** La surface exposée est une **liste
  blanche explicite** ; tout le reste est refusé par défaut
  (`location / { return 404; }` ou équivalent). Une liste noire de préfixes ne
  satisfait pas I-1 : elle échoue **ouverte**, et son défaut d'entrée devient
  une route exposée que rien ne signale. Trois défauts de causes différentes
  l'ont démontré sur un même filtre — un ancrage de fin de segment manquant, un
  routeur monté sans préfixe, une route ajoutée en amont.
- **I-2. Toute route mutante exposée appelle un contrôle d'authentification
  applicatif, inconditionnellement et avant tout effet.** Le *mécanisme* relève
  de l'architecture — jeton de rôle, identifiant de service, enveloppe signée,
  authentification portée par le proxy. Ce qui est opposable est qu'il existe,
  qu'il soit inconditionnel, et qu'il précède tout effet. La protection du proxy
  ne dispense pas de la protection applicative : c'est la seule couche dont on
  ait constaté qu'elle tenait quand l'autre a cédé.
- **I-3.** L'endpoint de métriques n'est jamais joignable depuis l'extérieur.
- **I-4.** Un endpoint de santé n'est exposé que par **décision explicite et
  documentée**, jamais par défaut. Le publier n'est pas une nécessité technique :
  la sonde de conteneur l'interroge depuis l'intérieur.
- **I-5.** Une route dont l'authentification est appelée sous condition
  (`if <jeton configuré>`, drapeau d'environnement, mode développement) n'est pas
  réputée protégée tant qu'un second contrôle inconditionnel n'échoue pas en
  fermeture quand la condition n'est pas remplie. Meilleure forme : faire de la
  condition une **précondition du processus** — un service dont les autorités ne
  sont pas configurées ne sert pas 503 à chaque requête, il ne démarre pas.

> **Ces invariants ont été éprouvés contre un second système.** La première
> rédaction de I-1 exigeait « une authentification au niveau du proxy », et de
> I-4 que les endpoints de santé soient publics. Confrontée à l'architecture
> cible — dont le proxy est une liste blanche stricte et dont l'authentification
> est un identifiant de service vérifié dans l'application —, cette rédaction
> déclarait non conforme un dispositif **plus strict** que celui qu'elle
> décrivait. Un invariant qui prescrit un mécanisme au lieu d'une propriété se
> retourne contre la meilleure implémentation : c'est encore le support pris pour
> la propriété, cette fois dans la règle elle-même.

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
- **V-7 — Un audit produit des faits, pas des exigences.** L'audit d'un système
  en fonctionnement établit des faits **sur ce système**. Il ne produit aucune
  condition pour son successeur. Tout constat doit être **re-dérivé contre la
  cible** avant de devenir une exigence : le système observé et le système visé
  ne se ressemblent que par accident.

  Éprouvé : une liste de huit « conditions de bascule » issue de l'audit d'un
  service en production s'est révélée, re-dérivée contre le code du dépôt, sans
  objet sur six points, déjà satisfaite sur un, et **activement nuisible sur le
  dernier** — elle demandait de configurer un registre de métriques multi-processus
  pour une cible qui avait délibérément choisi un worker canonique, motif écrit
  dans sa définition de composition. L'exigence aurait défait la décision.

- **V-8 — Un fragment cité est un support.** Une phrase reprise d'un rapport, un
  extrait de sortie de recherche, un nom de fichier dans une liste : ce sont des
  supports, pas des propriétés. Ils se vérifient dans leur document d'origine
  avant de fonder un raisonnement. Une citation tronquée a fait qualifier de
  « décision opposable dont le texte n'existe nulle part » un ADR qui était en
  réalité en quarantaine délibérée, correctement signalée aux quatre endroits où
  son numéro apparaît.

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

### 6. L'espace des numéros d'ADR est un registre, pas une convention

Cet ADR a failli être écrit sous un numéro déjà réservé — réservé par deux artefacts **en
prose**, une phrase de rapport et un champ d'attestation, sans qu'aucun fichier ne porte ce
nom. Aucune recherche de fichier ne pouvait le voir. C'est le motif de la §*L'énoncé du
motif* appliqué à la gouvernance elle-même : on interroge l'existence d'un fichier quand la
propriété est la réservation.

Décision : la réservation devient une chose que l'outillage connaît.

- `docs/adr/RESERVATIONS.md` porte un bloc délimité, seul lu par le contrôle. La prose du
  registre — numéros cités en provenance ou en exemple — ne réserve rien.
- `scripts/check-adr-numbering.sh`, appelé par `scripts/ci-local.sh`, échoue si : deux
  fichiers portent le même numéro ; un numéro est référencé dans le dépôt sans fichier ni
  entrée au registre ; une entrée subsiste alors que le fichier existe.
- Le garde-fou est balayé **comme les autres fichiers** : il ne contient donc aucun numéro
  littéral, qui vaudrait réservation. Un contrôle qui s'exempte de son propre périmètre est
  le défaut qu'il cherche.

Le balayage a signalé trois numéros sans fichier sur la ref courante, de trois natures
distinctes — une réservation en cours, une sentinelle de test, et un ADR **vivant sur une
branche non fusionnée**, au statut Proposé, que quatre documents citent en le déclarant
partout `UNREVIEWED_WIP` et `NON_AUTHORITATIVE`. Ce dernier cas n'est pas un défaut : c'est
une quarantaine délibérée, correctement signalée. Il enseigne en revanche la limite du
contrôle — il ne balaie que la ref courante — et c'est pourquoi le registre porte une
catégorie qui dit *où* le fichier vit, plutôt que d'étendre le balayage à toutes les refs et
de se coupler à l'état de `fetch`.

La première rédaction de ce paragraphe qualifiait ce cas de « lacune : un ADR déclaré accepté
dont le fichier n'existe pas ». C'était faux, et faux de la manière que cet ADR décrit :
la phrase citée avait été lue tronquée, dans une sortie de recherche, au lieu d'être lue
dans son document.

## Conséquences

**Positives.**

- Les invariants I-1 à I-5 et les règles V-1 à V-8 sont opposables en revue : une
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
