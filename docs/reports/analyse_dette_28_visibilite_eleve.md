# Dette n°28 — ce que coûte l'ouverture du corpus aux élèves

*Analyse, 28 août 2026. **Rien n'est appliqué.***

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
