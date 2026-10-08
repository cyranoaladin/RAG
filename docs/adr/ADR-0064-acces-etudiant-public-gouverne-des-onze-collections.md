# ADR-0064 — Accès étudiant public gouverné aux onze collections de recherche

- **Statut** : proposition soumise à revue humaine ; aucune ouverture de droit avant une review `APPROVED` au HEAD exact.
- **Date** : 2026-10-08.
- **Décideur** : `abenrhouma`, selon le protocole `NEXUS-TRUSTED-REVIEW-V1`.
- **S'appuie sur** : ADR-0033, ADR-0035, ADR-0045, ADR-0050, ADR-0052, ADR-0053, ADR-0058, ADR-0059, ADR-0060, ADR-0061, ADR-0062 et ADR-0063.

## Problème et décision demandée

Le produit V1 visé est la **recherche pédagogique gouvernée avec passages cités** pour les élèves de la population `libre` en première et terminale, sur les onze collections ci-dessous. Au 2026-10-08, le rôle `student` n'autorise que la visibilité `public`, tandis que les onze politiques de scope V4/V5, les treize autorisations r4 actives et les placements déjà publiés portent `internal`. Le droit documentaire `officiel_public` et la provenance publique du PDF ne rendent pas automatiquement le service public : ADR-0045 a choisi une politique plus restrictive.

L'approbation humaine de cette ADR **déciderait** l'ouverture de `policy_visibility=public`, limitée aux onze collections et aux contenus explicitement présents dans les futures releases successeurs scellées. Elle ne vaut ni promotion automatique des contenus, ni publication, ni autorisation de cutover. Chaque contenu reste soumis aux contrôles de droits, PII, actualité, revue, citation et portée signée. Aucun droit `usage_interne`, privé, inconnu ou révoqué n'est éligible à l'accès étudiant.

| Collection | Placements attendus dans l'union scellée |
|---|---:|
| `rag_nexus_dgemc_terminale_option` | 12 |
| `rag_nexus_hggsp_premiere_specialite` | 39 |
| `rag_nexus_hggsp_terminale_specialite` | 35 |
| `rag_nexus_hlp_premiere_specialite` | 115 |
| `rag_nexus_hlp_terminale_specialite` | 89 |
| `rag_nexus_nsi_premiere_specialite` | 29 |
| `rag_nexus_nsi_terminale_specialite` | 47 |
| `rag_nexus_ses_premiere_specialite` | 30 |
| `rag_nexus_ses_terminale_specialite` | 28 |
| `rag_nexus_svt_premiere_specialite` | 19 |
| `rag_nexus_svt_terminale_specialite` | 36 |
| **Total** | **479** |

Le périmètre matériel envisagé est l'union de la V4 **hors HGGSP** (9 collections, 263 artefacts, 405 placements, 5 678 chunks) et du successeur HGGSP V5 (2 collections, 52 artefacts, 74 placements, 2 590 chunks). Les trois empreintes sources recalculées au `main` `ee35544bce5af74d6186ea0ef61f6902a2258ffe` sont : manifeste V4 `bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be`, manifeste HGGSP V5 `8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf`, registre mixte `59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6`. Ces empreintes identifient des **références historiques**, pas encore les releases publiques à construire. Les manifestes actuels portent `rehearsal`, `PRE_REVIEW`, `NOT_PROMOTABLE` et `NO_PRODUCTION_ACTIVATION` ; ils ne peuvent pas être déclarés production par changement d'étiquette.

## Règles de réalisation après la décision humaine

1. Préserver les releases V4 et HGGSP V5, leurs manifests, leurs scopes et les lignes déjà publiées. Conformément à ADR-0050, émettre **de nouvelles identités de release** pour la partie non-HGGSP et pour HGGSP, puis un registre mixte qui nomme exactement ces deux propriétaires. Utiliser les producteurs, vérificateurs et rôles gouvernés existants. La qualification se fait sur une **cible propre et isolée** ; elle doit prouver 11 collections, 315 artefacts, 479 placements et 8 268 chunks, sans ajuster les compteurs pour cacher des doublons.
2. Émettre des profils, preuves de release, autorisations de publication liées au contenu et scopes **successeurs** dont les deux dimensions `evidence_visibility` et `policy_visibility` valent explicitement `public`. Ne pas modifier les anciens profils, artefacts de scope, autorisations r4 ni le registre actif par effet de bord. Les nouveaux scopes lient chacun le digest du subject de sa nouvelle release ; une correspondance absente ou ambiguë est un refus.
3. Soumettre les nouvelles autorités et chaque revue batch à une approbation humaine sur son HEAD exact avant enregistrement. Prouver qu'aucun contenu hors des 315 empreintes scellées, hors droits `officiel_public`, hors portée, non revu, non courant ou révoqué n'est servi. Une revue de droits ne se déduit pas de ce texte ni de la seule valeur `officiel_public` en base : les reçus et la validité des droits sont revérifiés au moment de la nouvelle publication.
4. Garder `_ROLE_VISIBILITIES['student'] == ('public',)` et le filtrage `placement.visibility` de l'API v2. Interdire toute acceptation de `internal` pour `student`. Les anciennes valeurs `rag_chunks.visibility` ne sont jamais réécrites pour simuler une ouverture ; le placement gouverné et le scope signé font autorité pour le retrieval des artefacts liés.
5. Sur la cible finale, exiger une recherche étudiante positive et citée dans chacune des onze collections via Cockpit/BFF → identité signée → API v2 → scope serveur → pgvector, des refus teacher/student hors portée, `OUT_OF_SCOPE_RESULTS=0`, `MISSING_CITATIONS=0`, et la preuve de cardinalité ci-dessus. Répéter les contrôles droits, PII, actualité et révocations avant le cutover.

## Pourquoi une cible propre

Le publisher calcule `placement_id` à partir du tuple qui inclut `visibility` et ajoute les placements sans modifier les anciens. Ajouter 479 placements `public` aux 479 placements `internal` d'une même base ferait **958 lignes physiques**, ce qui contredirait la cible finale de 479. Une mutation SQL des placements existants, un élargissement de `_ROLE_VISIBILITIES` ou un changement de politique seul ne sont pas des transitions gouvernées et ne satisfont pas la sélection réelle de l'API v2. Une cible propre avec les nouveaux manifests conserve l'historique et les cardinalités sans nouveau chemin permissif.

## Frontières de cette ADR

Cette PR de décision ne crée aucun manifeste public, aucune autorisation active, aucune attestation, aucun job et aucune ligne produit. Elle ne change pas `answer_generation_allowed=false`. Les nouvelles identités, empreintes et approbations techniques seront vérifiées et publiées dans des PR de lot distinctes avant exécution. Tant que cela n'est pas réalisé, `STUDENT_SERVABLE=false` pour les onze collections et `GO_LIVE_READY=false`.
