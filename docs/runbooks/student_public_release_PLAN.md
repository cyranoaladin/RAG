# Plan gouverné — release publique de recherche étudiante

**État au 10 octobre 2026 : candidat non activable.** Les PR #300 et #312 sont fusionnées. La première a approuvé la délégation et le jeu de décisions documentaires ; la seconde a scellé un **candidat** de textes dérivés, sans autoriser son ingestion ou un accès étudiant. La review exacte de #312 et les 17 fichiers du candidat se revérifient par `scripts/go_live/pr312_authority_receipt.py`. Ce plan n'autorise aucune écriture staging ou production.

## Source autorisée et comptes

Le candidat `student-public-20261010-v1-eb39f6cd0423e184` porte 11 collections, 253 artefacts textuels dérivés, 377 placements et 3 975 chunks. Ces valeurs sont celles des manifests #312, **pas** des bases staging ou production. Les 315 PDF sources et les releases V4/V5 rehearsal restent `internal`. Le verdict CFTR reste `EXCLUDE`. Aucun PDF, rendu de page, image ou OCR graphique ne doit être publié.

Les comptes historiques 11/315/479/8268 décrivent l'union des PDF V4/V5 ; ils ne sont plus une cible de release publique. La release finale doit publier les comptes réellement produits et qualifiés. Ne jamais adapter le corpus ou les compteurs pour atteindre ces valeurs anciennes.

## Préparation de la release successeur

1. Depuis un `origin/main` frais, créer un worktree propre et un venv isolé. Relire en direct les approvals exactes de #300 et #312, les trees fusionnés, les digests du pack et du candidat, puis vérifier les 253 textes, reçus et lignages du CAS privé contre les SHA versionnés.
2. Produire une **nouvelle identité** de release. Conserver le candidat #312 inchangé et non activable. Recalculer 11 profils `CollectionProfile` complets, `visibility=public`, depuis les profils V3 scellés ; la proposition n'est pas une approbation. Émettre un inventaire lié par `(derivative_sha256, source_placement_id)`, les preuves d'actualité et les registres de droits et PII liés aux SHA dérivés. Un transfert privé n'est déclaré réussi qu'après comparaison effective des octets sur sa destination.
3. Sceller les nouvelles autorités dans l'agrégat et les onze subjects, avec un registre de release propre. La garde de readiness et Worker A doivent refuser une candidate renommée, un PDF original rendu public, une pièce manquante, une date ou attribution absente et tout status pré-review présenté comme actif.
4. Définir séparément la politique de scope public : `evidence_visibility=public` et `policy_visibility=public`, droit positif Etalab lié aux dérivés, population/collection/niveau/matière exacts, onze nouveaux scope IDs et digests liés aux nouveaux subjects. Ne pas modifier les scopes V4/V5 ou `_ROLE_VISIBILITIES['student']` ; `student` reste limité à `public`.
5. Préparer onze autorisations LOT41A-V2 et la revue batch LOT42 sur les nouveaux digests, avec les décisions de politique et le pack complet dans une PR. La review de l'autorité `abenrhouma` au HEAD exact est le gate humain ; elle ne simule pas une lecture individuelle des PDF. Aucune publication par le seul merge de la PR.

## Exécution et qualification après autorisation

Avant toute écriture staging, relire l'identité runtime/DB et établir un backup. Déployer une cible de qualification **propre** avec images par digest et sans bind mount du dépôt. Vérifier le transfert privé des seuls `.txt`, les migrations, les autorisations, la revue, les onze profils et scopes, puis exécuter `quality → gate → review → publication`. Compter sur la DB finale les collections, artefacts, placements et chunks, sans présumer les comptes du candidat.

Qualifier chaque collection par le chemin Cockpit/BFF → identité signée → API v2 → scope serveur → pgvector → citations. Exiger les quatre champs d'attribution Etalab, l'URL/titre/page/date, le bon niveau et la bonne matière, et zéro résultat hors scope. Les refus student/teacher, la qualité retrieval figée, C0 après warmup, l'observabilité, le backup/restauration isolée et le rollback appartiennent à **cette même cible finale**.

La production historique n'est jamais modifiée en place. Le cutover blue-green n'intervient qu'après une readiness `--assert-ready` verte, une signature offline valide et un GO explicite au gate final ; vérifier ensuite l'API externe, le Cockpit, les refus, les citations, les comptes réels, la charge bornée et un backup post-cutover.

**Arrêt fail-closed :** tout écart de SHA, provenance, droits, PII, actualité, révocation, scope, revue, transfert, attribution, cardinalité ou preuve de cible interdit la mutation suivante. Le candidat #312 ne doit jamais être activé directement.
