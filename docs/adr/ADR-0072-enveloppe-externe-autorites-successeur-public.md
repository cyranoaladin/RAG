# ADR-0072 — Séparer le contenu public immuable de ses autorités d'activation

- **Statut** : proposé ; aucune activation autorisée par cette ADR.
- **Date** : 2026-10-10.
- **Portée** : successeur textuel étudiant ; complète ADR-0064 et corrige le graphe de scellement prévu par ADR-0070.

## Problème

Le schéma `public_successor` d'ADR-0070 exige les 21 SHA d'autorité dans le manifeste agrégé **et dans chaque subject**. Or la revue batch `LOT42-RELEASE-BATCH-V1` contient `release_manifest_sha256`, et le manifeste contiendrait `publication_batch_review_receipt_sha256`. Sa construction demanderait `SHA(manifeste) → SHA(revue) → SHA(manifeste)`. De même, un scope qui lie le SHA du subject final et dont le SHA figure dans ce subject demanderait `SHA(subject) → SHA(scope) → SHA(subject)`. Il n'existe pas d'ordre de scellement fini vérifiable pour ces dépendances. Remplir les champs avec des SHA de substitution ou les omettre serait une fausse autorité.

## Décision

La chaîne de release publique doit être un graphe acyclique à trois étages :

1. **A — contenu immuable.** Le manifeste, l'index, l'inventaire, les onze subjects, les profils, le registre d'artefacts et leurs octets restent ceux du paquet préparatoire #323, ou d'un **nouveau** paquet de contenu re-scéllé si une exclusion modifie la population. L'ancrage `NEXUS_PUBLIC_SUCCESSOR_CONTENT_ANCHOR_V1` nomme leurs SHA et leurs comptes. Il porte `CONTENT_ONLY_NOT_ACTIVABLE` et `activation_allowed=false`. Son SHA est l'identité de contenu à revoir ; il ne contient aucun digest de revue future.
2. **B — autorités externes.** Les scopes V3 émis doivent avoir `source_sha256` égal au SHA du subject de A pour leur collection, avec politique `roles=[student]`, visibilité `public` et dérivés `public_allowed`. La revue exacte des scopes, les onze autorisations LOT41A, la revue batch LOT42, les preuves droits/PII/actualité, le transfert observé et les révocations lient A ou ses composants déjà scellés. Le `release_manifest_sha256` de LOT42 désigne le manifeste de contenu A. Aucun de ces reçus ne doit exiger le SHA de l'enveloppe C ou d'un subject réécrit après revue.
3. **C — enveloppe d'autorité.** Une fois B disponible, une enveloppe distincte référence le SHA de A et les 21 SHA de preuve. Elle ne réécrit aucun document de A. Le constructeur actuel ne vérifie que l'existence et les empreintes des octets : sa sortie reste `EVIDENCE_BYTES_ONLY_NOT_ACTIVABLE`, `semantic_verification_complete=false`, `activation_allowed=false`, même si 21 fichiers sont fournis. Un validateur indépendant devra ouvrir chaque pièce, vérifier sa population, son périmètre, sa validité temporelle, ses reviews GitHub au base/HEAD exacts, sa non-révocation et son identité de cible. Worker A, le lecteur de readiness et le runtime devront consommer **ce verdict lié au SHA de C et de A** avant toute écriture ou service public.

Le mode `public_successor` à autorités incorporées d'ADR-0070 reste refusé par `load_release_expectation` et Worker A. Il ne sert pas de raccourci de promotion ; une évolution de contrat ultérieure devra intégrer explicitement le vérificateur de C et prouver ses refus par tests. Le paquet #323 garde ses statuts `candidate/NOT_PROMOTABLE/PRE_REVIEW/NO_PRODUCTION_ACTIVATION`. La proposition #294 garde ses onze scopes `NOT_ISSUED` jusqu'à l'émission gouvernée. Aucun PDF V4/V5 n'est promu.

## Critère d'acceptation de C

Le verdict positif de C n'est atteignable que si le vérificateur indépendant réussit **toutes** les 21 pièces sur les octets exacts de l'enveloppe, sans champ inconnu ni manquant. Il doit confronter les SHA de A à l'inventaire et aux onze subjects, rejouer les décisions #300/#312/#313 et le CAS privé, vérifier les onze scopes V3 émis sur les SHA des subjects de A ainsi que leur review exacte, vérifier les onze LOT41A et LOT42 sur le manifeste de A, et qualifier droits, PII, actualité, révocations, plan et reçu de transfert sur la cible réelle. Le verdict est lié aux SHA de A et C, possède une validité temporelle, et son absence, expiration ou révocation impose le refus. Worker A, readiness et runtime doivent vérifier ce même verdict avant publication et service ; leur intégration n'est pas déduite de la seule ADR. Les contrôles d'inclusion, de CAS et du transfert local déjà possibles produisent des sous-verdicts vérifiés, jamais le verdict global.

## Invariants de sortie

Un changement de placement, d'artefact, de chunk, de profil ou de subject après A exige un **nouvel A** avec nouvelle identité et nouvelle revue des dépendances. Le plan de transfert et LOT42 lient l'inventaire de ce même A ; une répétition locale à identité de cible non qualifiée ne suffit pas. Les comptes 11/253/377/3975 décrivent seulement A #323, pas le staging ni la production. Aucun scope `student/internal`, endpoint de PDF, writer ou génération de réponse n'est ouvert. Le gate C ne peut passer au vert par la seule présence de 21 SHA : les contrôles sémantiques et l'intégration Worker/runtime restent des lots obligatoires.
