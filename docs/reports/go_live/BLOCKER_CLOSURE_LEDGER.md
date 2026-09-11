# Ledger de fermeture des bloqueurs go-live

> **Fichier derive.** Regenere par
> `scripts/go_live/check_go_live_readiness.py`. Les valeurs viennent de
> l etat calcule ; les editer a la main les rendrait faux sans les
> rendre fermes.

`blockers_open=6` sur 9

| Bloqueur | Valeur | Bloque | Qui agit | Condition de fermeture |
| --- | ---: | :---: | --- | --- |
| `RAG_SEARCHABILITY` | True | oui | OPERATOR | toutes les conditions de fermeture de l ecart de recherche sont tenues, mesurees et non supposees |
| `RELEASE_PROMOTED_REFUSED_CONTENTS` | 26 | oui | HUMAN_REVIEWER | aucun contenu de l ensemble promu ne porte un verdict de refus dans la matrice de servabilite |
| `PII_UNDECIDED` | 149 | oui | HUMAN_REVIEWER | 0 PII indecise dans le perimetre servable, ou exclusion gouvernee et versionnee de ces contenus. |
| `PROGRAM_INCOMPATIBLE_IN_SERVABLE_SET` | 0 | non | HUMAN_DECISION | Artefact exclu du perimetre servable ou reattribue, avec une epreuve discriminante ; il reste comptabilise dans les 2530 en GOVERNED_NOT_SERVABLE, jamais supprime de l historique. |
| `CURRENTNESS_POLICY_APPLIED` | True | non | ENGINEERING | Un consommateur de production applique la politique et le gate le constate ; un registre seulement present ne suffit pas. |
| `NON_PDF_SERVABLE_REACQUIRED` | 37/37 | non | OPERATOR | Octets disponibles pour chaque ressource servable, empreintes concordantes, ou exclusion gouvernee. |
| `GO_LIVE_QUALIFICATION_BLOCKERS` | 13 | oui | MIXED | Chaque entree du tableau porte closed=true et sa preuve. |
| `OPEN_PRS_BLOCKING` | 6 | oui | HUMAN_DECISION | Aucune disposition BLOCKING ni UNKNOWN. |
| `PRE_RELEASE_BLOCKERS` | 1 | oui | DERIVED | Se ferme seul quand ses trois sources se ferment. |

## Detail

### RAG_SEARCHABILITY

- categorie : `DATA`
- valeur : `True`, bloque : `oui`
- source de preuve : `docs/reports/go_live/rag_searchability_gap.json (derive de l audit d ingestion sur une base nommee)`
- action requise : Indexer le perimetre cible en vecteurs, puis valider le retrieval : top-k, citations, filtres de portee, latence, rollback. Un corpus qualifie servable reste inatteignable tant qu aucun vecteur ne le reference.
- decision humaine requise : `non`
- automatisable : `oui`
- PR liees : aucune
- dependance de deploiement : `BLOQUE_LE_DEPLOIEMENT`

### RELEASE_PROMOTED_REFUSED_CONTENTS

- categorie : `BUSINESS`
- valeur : `26`, bloque : `oui`
- source de preuve : `docs/reports/handoff/servability_matrix_v1.json croisee avec l ensemble promu canonique : un contenu promu dont le gate de servabilite refuse le verdict`
- action requise : Decider du sort de chaque contenu promu desormais refuse : le retirer et resceller la release sous une identite neuve, ou documenter une derogation gouvernee. Ni l un ni l autre ne peut etre fait par un script.
- decision humaine requise : `oui`
- automatisable : `non`
- PR liees : aucune
- dependance de deploiement : `BLOQUE_LE_SCELLEMENT`

### PII_UNDECIDED

- categorie : `BUSINESS`
- valeur : `149`, bloque : `oui`
- source de preuve : `docs/reports/handoff/servability_matrix_v1.json (by_pii.PII_UNDECIDED)`
- action requise : Trancher chaque paquet de revue, ou exclure explicitement ces contenus du perimetre servable par une decision gouvernee.
- decision humaine requise : `oui`
- automatisable : `non`
- PR liees : aucune
- dependance de deploiement : `BLOQUE_LE_SCELLEMENT`

### PROGRAM_INCOMPATIBLE_IN_SERVABLE_SET

- categorie : `BUSINESS`
- valeur : `0`, bloque : `non`
- source de preuve : `docs/reports/handoff/servability_matrix_v1.json (by_verdict.REFUSED_PROGRAM_INCOMPATIBLE)`
- action requise : L artefact est nomme dans la partition programme. L exclure de la prochaine release, ou corriger sa liaison de perimetre. Ne jamais corriger sa verite pour faire passer le gate.
- decision humaine requise : `oui`
- automatisable : `non`
- PR liees : aucune
- dependance de deploiement : `BLOQUE_LE_SCELLEMENT`

### CURRENTNESS_POLICY_APPLIED

- categorie : `GOVERNANCE`
- valeur : `True`, bloque : `non`
- source de preuve : `services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml (champ applied)`
- action requise : Cabler la politique dans le runtime. ADR-0055 l adopte ; adopter et cabler sont deux actes distincts, et les confondre ferait d une revue de texte un changement de comportement.
- decision humaine requise : `non`
- automatisable : `oui`
- PR liees : [151]
- dependance de deploiement : `BLOQUE_LE_SCELLEMENT`

### NON_PDF_SERVABLE_REACQUIRED

- categorie : `DATA`
- valeur : `37/37`, bloque : `non`
- source de preuve : `docs/reports/go_live/non_pdf_retention_policy.json (magasin durable mesure) ; plancher : docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json (NON_PDF_LOCAL_COPY_RETAINED)`
- action requise : Reacquerir les ressources interactives servables depuis Drive, empreinte et taille attendues au manifeste, ou les exclure par une decision gouvernee et non silencieuse.
- decision humaine requise : `non`
- automatisable : `oui`
- PR liees : aucune
- dependance de deploiement : `BLOQUE_L_INGESTION_STAGING`

### GO_LIVE_QUALIFICATION_BLOCKERS

- categorie : `QUALIFICATION`
- valeur : `13`, bloque : `oui`
- source de preuve : `docs/reports/go_live/qualification_blockers.json`
- action requise : Fermer chaque gate avec sa preuve. Fermer les bloqueurs metier ne suffit PAS a deployer : ces gates-la restent entiers.
- decision humaine requise : `oui`
- automatisable : `non`
- PR liees : [132, 167, 168]
- dependance de deploiement : `BLOQUE_LE_DEPLOIEMENT`

### OPEN_PRS_BLOCKING

- categorie : `REPOSITORY`
- valeur : `6`, bloque : `oui`
- source de preuve : `docs/reports/go_live/open_pr_dispositions.json`
- action requise : Fusionner, fermer sur preuve, ou reclasser avec justification mesuree. Une PR non classee est UNKNOWN et bloque par construction.
- decision humaine requise : `oui`
- automatisable : `non`
- PR liees : [98, 132, 134, 138, 140, 151]
- dependance de deploiement : `BLOQUE_LE_SCELLEMENT`

### PRE_RELEASE_BLOCKERS

- categorie : `AGGREGATE`
- valeur : `1`, bloque : `oui`
- source de preuve : `agregat calcule`
- action requise : Rien directement. Ce compteur DERIVE de PII, programme et actualite. Le fermer par lui-meme reviendrait a maquiller les trois.
- decision humaine requise : `non`
- automatisable : `non`
- PR liees : aucune
- dependance de deploiement : `BLOQUE_LE_SCELLEMENT`
