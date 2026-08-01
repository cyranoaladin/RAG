# ADR-0021 — Politique de validation pilote dormante

- **Statut** : proposé (LOT38 ; accepté uniquement après fusion de la PR)
- **Date** : 2026-08-01
- **Périmètre** : `libre_terminale`, Mathématiques et NSI, année scolaire `2026-2027`
- **S'appuie sur** : [ADR-0001 — séparation contrôle/données/cockpit](ADR-0001-separation-controle-donnees-cockpit.md) et la [conception validée du pilote](../superpowers/specs/2026-07-31-pilot-go-live-finalization-design.md)

## Contexte

La mise en validation de documents réels ne peut pas être déduite des verrous
historiques du cockpit. Elle exige un périmètre adressé par contenu, des
capacités propres à l'environnement de validation et une autorité humaine
indépendante de l'agent qui implémente la transition. Une erreur, une preuve
absente ou une divergence de périmètre doit fermer le chemin : aucun booléen
global ne constitue à lui seul une autorisation.

Conformément à l'[ADR-0001](ADR-0001-separation-controle-donnees-cockpit.md),
`rag-pedago` reste le plan de contrôle, `rag-engine` reste le plan de données et
le cockpit ne passe que par l'API contractuelle du moteur. LOT38 ne lit aucun
document réel, ne publie rien dans pgvector et n'ouvre aucun runtime.

## Décision

LOT38 crée le scope immuable `libre_terminale_maths_nsi_real_v1`, dans l'état
`eligible_for_promotion`, jamais `active`. Son identité autorise exactement le
tenant `libre_terminale`, le niveau `terminale`, la voie `generale`, le statut
`specialite`, l'audience `libre`, les candidats `cned_libre`, `individuel` et
`libre`, ainsi que l'année scolaire `2026-2027`.

Le [document de scope](../../services/rag-pedago/configs/pilot_validation_scope.yml)
a pour SHA-256 brut
`b55ef1383fceabbbe0bf30c47a45a1fce607697f56bac340162156fabcf0fe26`.
La [politique dormante](../../services/rag-pedago/configs/pilot_validation_policy.yml)
a pour SHA-256 brut
`bb548458ec83cacc2abe0c55104ade4bb44cb06828000bf50b9c97d8f3412bad`.

Les deux seules collections et taxonomies du scope sont :

| Collection | Taxonomie | SHA-256 brut |
|---|---|---|
| `rag_nexus_maths_terminale_gen_specialite` | `services/rag-pedago/taxonomy/maths/terminale_gen_specialite.yml` | `4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6` |
| `rag_nexus_nsi_terminale_specialite` | `services/rag-pedago/taxonomy/nsi/terminale.yml` | `b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f` |

Le scope couvre exactement 39 notions :

- Mathématiques (13) : `suites_limites`, `continuite`,
  `derivation_convexite`, `logarithme`, `primitives_integration`,
  `equations_differentielles`, `combinatoire`, `geometrie_espace`,
  `produit_scalaire_espace`, `succession_epreuves`,
  `variables_aleatoires_esperance`, `loi_grands_nombres`, `python` ;
- NSI (26) : `listes`, `piles`, `files`, `arbres`, `graphes`,
  `dictionnaires`, `recursivite`, `diviser_pour_regner`,
  `programmation_dynamique`, `parcours_graphes`, `recherche`, `tri`,
  `modele_relationnel`, `sql`, `contraintes`, `jointures`, `processus`,
  `protocoles`, `reseaux`, `routage`, `securisation`, `poo`,
  `tests_mise_au_point`, `gestion_modules`, `paradigme_fonctionnel`,
  `calculabilite_decidabilite`.

La politique `libre_terminale_validation_policy_v1` reste elle aussi
`eligible_for_promotion`. Les quatre capacités de validation sont créées et
maintenues à `false` :

| Capacité de validation | Valeur LOT38 |
|---|---|
| `validation_real_documents_allowed` | `false` |
| `validation_pipeline_allowed` | `false` |
| `validation_answer_generation_allowed` | `false` |
| `validation_openrouter_allowed` | `false` |

Les quatre verrous publics historiques restent également fermés :

| Verrou public | Valeur LOT38 |
|---|---|
| `real_documents_allowed` | `false` |
| `ui_runtime_allowed` | `false` |
| `answer_generation_allowed` | `false` |
| `curated_ingestion_allowed` | `false` |

L'environnement `nexus-validation-1` décrit une isolation intentionnelle :
credentials, DSN, bucket et réseau dédiés, sans route publique ni BFF. LOT38
ne prouve pas cette isolation ; son statut reste
`intended_pending_lot41a`. Seuls les noms des références d'environnement sont
versionnés, jamais leurs valeurs.

LOT38 est un modèle dormant, sans exécuteur. LOT41 devra raccorder
`rag-engine` au scope par contrat/API ou par artefact signé, sans importer ni
lire directement le code de `rag-pedago`. LOT41A devra fournir une approbation
humaine GitHub indépendante, liée aux octets exacts du payload et au head
effectivement approuvé. LOT42 devra prouver ce raccordement et le passage
`quality → gate → review` avant la première publication.

Toute validation est fail-closed : entrée mal formée, digest divergent,
taxonomie ou collection hors scope, identité incompatible, capacité fermée,
autorisation absente ou périmée, preuve GitHub incohérente, droits ou absence
de PII non vérifiés, rollback non prouvé, package non revu ou appelant non
autorisé entraînent un refus déterministe.

## Conséquences

- Aucun document réel, pipeline de validation, appel OpenRouter ou génération
  de réponse n'est autorisé par LOT38.
- Aucun verrou global n'est activé et aucune route publique n'atteint
  `nexus-validation-1`.
- `rag-engine` demeure l'unique publisher possible vers pgvector ; une
  publication future exige un package adressé par contenu et la chaîne
  `quality → gate → review` entièrement réussie.
- L'approbation d'un agent, un fichier d'autorisation isolé ou un test vert ne
  remplace jamais l'autorité humaine de LOT41A ni sa preuve GitHub indépendante.
- L'état `eligible_for_promotion` exprime seulement l'éligibilité du modèle à
  une décision future ; il ne vaut ni activation, ni promotion, ni go-live.

## Retour arrière

LOT38 n'active aucun runtime : son retour arrière immédiat consiste à conserver
ou rétablir les quatre capacités de validation à `false`, sans migration de
données ni opération sur un service actif.

Si une autorisation future a été émise, le rollback ferme d'abord les quatre
capacités, révoque la preuve d'autorisation, coupe les références réseau et
d'accès, puis isole les stores de validation (base et bucket) avant toute autre
action. Les packages autorisés sont révoqués et toute publication est stoppée.
Le plan LOT41A devra démontrer ce retour arrière ; son absence maintient le
refus fail-closed.
