# Dette n°28 — ce que coûte l'ouverture du corpus aux élèves

*Analyse, 28 août 2026.*

> **DÉCISION OPÉRATEUR — voie B appliquée le 28/08/2026.** Le rôle `student`
> reçoit `internal`. Condition posée par l'opérateur — « vérifie d'abord que le
> contrat ne définit pas `internal` comme *exclu des utilisateurs finaux* » —
> **vérifiée et non satisfaite** : voir « Vérification de la condition » ci-dessous.
> Résultat : les 18 collections répondent sous rôle élève, en 300 à 1 165 ms.

## Le constat

Les 18 collections servies portent `visibility: internal`. Or
`allowed_visibilities_for_role` (`retrieval_scope_v2.py:129`) accorde `internal`
à `teacher`, `admin`, `reviewer` et `ingest_agent` — **jamais à `student`** :

| Rôle | Visibilités accordées |
|---|---|
| **`student`** | **`public`** — et rien d'autre |
| `teacher` | `internal`, `public` |
| `reviewer` | `internal`, `public`, `restricted` |
| `admin` | `internal`, `private`, `public`, `restricted` |

Un profil élève obtient donc `403 Forbidden`, systématiquement, sur les dix-huit
collections. Tous les tirs de charge de ce lot ont dû être menés sous `teacher`.

**Pour une plateforme destinée aux élèves, c'est un bloqueur de mise en service.**

## Deux voies, deux coûts sans commune mesure

### Voie A — passer les collections en `public`

`visibility` est un champ de `evidence_subject`, présent dans les **18 manifests-sujets**
(`subjects/*.release.json`). Chaque manifeste est scellé par son sha256 dans
`production-profile-gate.release.json` — vérifié fichier par fichier.

Et ces mêmes empreintes sont les `source_sha256` des 18 scopes `_v2`.

La cascade est donc exactement celle de cette semaine :

1. 18 manifests-sujets modifiés → 18 empreintes changées ;
2. agrégat de release ré-émis ;
3. `source_sha256` des 18 scopes `_v2` invalidés ;
4. ADR-0045 interdit de muter le `source_sha256` d'un scope publié → **18 scopes
   `_v3`**, les `_v2` restant en place ;
5. `nexus-contracts` 0.17.0 ;
6. ré-écriture des 26 placements et 730 chunks en base ;
7. nouvel ADR, et le balayage de fermeture d'impact complet.

**Coût : la cascade de rescellement entière**, celle qui a occupé deux jours.

### Voie B — accorder `internal` au rôle `student`

Une entrée dans `_ROLE_VISIBILITIES`, dans `retrieval_scope_v2.py`. **Aucun
sceau touché** : ni manifeste, ni agrégat, ni `source_sha256`, ni scope, ni
contrat, ni base. Le champ `visibility` des documents reste `internal` — c'est la
*lecture* du rôle qui change, pas la *déclaration* du contenu.

**Coût : une ligne, un test, un ADR.**

## L'arbitrage n'est pas technique

La voie B est cinquante fois moins chère. Mais elle n'est pas « la même chose en
moins cher », et ce serait malhonnête de la présenter ainsi.

**La question de fond : que signifie `internal` ?**

- Si `internal` veut dire *« interne à Nexus, pas destiné aux élèves »*, alors la
  voie B **affaiblit un contrôle** — elle donne aux élèves ce qui leur était
  refusé par déclaration. C'est un cas d'arrêt : gouvernance.
- Si `internal` veut dire *« interne à la plateforme, par opposition au web
  public »*, alors les élèves en sont les destinataires légitimes, la voie B est
  la **correction d'une erreur de correspondance rôle/visibilité**, et la voie A
  serait un rescellement pour rien.

Les documents concernés sont **26 PDF Éduscol** — des programmes officiels,
publiquement téléchargeables sur eduscol.education.fr. Rien dans leur contenu ne
justifie de les soustraire aux élèves. Cela **suggère** la seconde lecture, mais
ne la **prouve pas** : `internal` peut désigner le statut de la *ressource dans
la plateforme*, pas la sensibilité du contenu.

**C'est une décision de gouvernance, et elle appartient à l'opérateur.** Aucune
des deux voies n'est engagée ici.

## Ce qu'il faudrait vérifier avant de trancher

1. La définition de `internal` dans la taxonomie de `rag-pedago` — existe-t-il
   un document qui la fixe ?
2. Les 13 scopes `_v1` historiques : quelle visibilité portent-ils, et pour quel
   rôle cible ? Si un `_v1` sert déjà des élèves en `public`, la réponse est déjà
   dans le dépôt.
3. Si la voie A est retenue, elle doit l'être **avant** l'ingestion des 2451
   documents — rescellement de 18 sujets contre rescellement de 2451.

## Ce que cette dette révèle au-delà d'elle-même

Le pipeline complet a été construit, scellé, ingéré, mis sous CI verte et servi —
sans que quiconque n'ait jamais exécuté une requête **sous le rôle auquel le
produit est destiné**. Le défaut n'apparaît qu'au premier tir avec un profil
élève réel.

Les tests d'intégration existants passent parce qu'ils utilisent des rôles
privilégiés. Un test qui interroge en `student` chacune des collections servies
manque, et c'est lui qui aurait mordu.


## Vérification de la condition posée par l'opérateur

*« Vérifie d'abord que le contrat ne définit pas `internal` comme "exclu des
utilisateurs finaux". Si c'est le cas, ma décision tombe. »*

**Le contrat ne le définit pas ainsi.** Trois constats, tous vérifiables :

1. **Le contrat n'attache aucune sémantique au terme.** `Visibility` est un
   `Literal["public", "internal", "restricted", "private"]`
   (`nexus_contracts/ingestion.py:51`), sans docstring ni commentaire. Les trois
   déclarations du dépôt — `ingestion.py`, `scope.py`, `document.py` — sont des
   énumérations nues.

2. **Là où « revue seulement » est visé, un terme distinct est employé.**
   `source_admission_policy.yml:89` écrit `visibility: internal_review_only`
   pour un cas explicitement non servi (`real_file_attached: false`,
   `human_review_required: true`). Le vocabulaire distingue donc les deux
   notions : `internal` seul n'est pas `internal_review_only`.

3. **La décision de droits autorise nommément le service.** Pour la zone
   `01_EDUSCOL_OFFICIEL/` — celle des 26 documents —
   `rights_evidence_registry.yml` porte `approved_for_internal_rag: true`,
   `approved_for_production_rag: true`, et la déclaration signée de Nexus
   Réussite autorise « le traitement, l'indexation, le chunking, l'embedding,
   **le retrieval, la citation** et l'ingestion de production ».

Une recherche inverse — toute cooccurrence de `internal` avec *utilisateur*,
*élève*, *student*, *final*, *interdit*, *exclu* dans `packages/contracts`,
`docs/adr` et `services/rag-pedago/configs` — **ne rend aucune occurrence**.

Un négatif vaut ce que vaut son périmètre : celui-ci couvre le contrat, les ADR
et la configuration de gouvernance. Il ne couvre pas une définition qui
n'existerait que dans la tête d'un rédacteur.

### Une valeur hors contrat, rencontrée en chemin

`retrieval_metadata_eval.yml` emploie `visibility: student_visible` — une
quatrième valeur, absente du `Literal` du contrat. Ce fichier porte
`status: metadata_only_eval` et `real_documents_allowed: false` : c'est une
fixture d'évaluation avec son vocabulaire propre, non la taxonomie faisant foi.
Signalé sans être corrigé — hors périmètre, mais c'est une divergence de
vocabulaire de plus.

## Ce qui a été appliqué

```python
"student": ("public", "internal"),   # au lieu de ("public",)
```

Une ligne dans `_ROLE_VISIBILITIES` (`retrieval_scope_v2.py`). **Aucun sceau
touché** : ni manifeste, ni agrégat, ni `source_sha256`, ni scope, ni contrat, ni
base. Le champ `visibility` des 26 documents reste `internal`.

`restricted` et `private` **restent fermés** au rôle `student` : la décision
portait sur `internal` seul, et un test le verrouille — élargir au-delà de ce qui
a été décidé serait le glissement que la gouvernance refuse.

### Preuve de bout en bout

Requête HTTP réelle, rôle `student`, pipeline complet, 18 collections :

```
rag_nexus_ses_premiere_specialite      300 ms  OK
rag_nexus_nsi_terminale_specialite     329 ms  OK
…
rag_nexus_dgemc_terminale_option      1165 ms  OK
-> 18 cibles servies
```

**18 sur 18**, de 300 à 1 165 ms. Auparavant : 18 refus `403`.

### Le test qui manquait

`test_student_can_read_served_corpus.py` vérifie que **toutes** les visibilités
portées par les scopes `_v2` servis sont couvertes par le rôle `student` — pas un
échantillon. Vérifié rouge sans le correctif.

C'est ce test qui aurait mordu il y a des semaines. Le pipeline entier a été
construit, scellé, ingéré, mis sous CI verte et servi sans que quiconque
n'interroge jamais sous le rôle auquel le produit est destiné.
