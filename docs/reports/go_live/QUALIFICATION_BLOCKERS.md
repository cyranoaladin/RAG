# Blocages de qualification du go-live

- kind : `NEXUS-GO-LIVE-QUALIFICATION-BLOCKERS-V2`
- ouverts : **6** / fermés : 7

> État DÉRIVÉ, jamais tenu à la main. Un blocage sans vérificateur reste ouvert. `closed=true` avec `proof=null` est refusé à la construction.

| Blocage | Propriétaire | Fermé | Condition de fermeture |
|---|---|---|---|
| `C1` | operateur | **non** | une release gouvernée couvre l ensemble promu, sans contenu refusé |
| `C2` | session H2-C externe | **oui** | une ingestion multilevel réelle aboutit et est rejouable |
| `C3` | session H2-C externe | **oui** | le worker CLI traite un lot multilevel de bout en bout |
| `C4` | operateur | **oui** | le contrat de retrieval est validé sur le corpus SERVABLE, pas seulement sur un index de staging : les huit conditions de l écart de recherche doivent être tenues |
| `C5` | operateur | **oui** | l autorité d accès refuse une portée non autorisée, prouvé par épreuve |
| `C6` | operateur | **oui** | la qualification CAS couvre le magasin réel |
| `COCKPIT_E2E` | operateur | **non** | le cockpit interroge l API de retrieval de bout en bout |
| `STAGING_EXTERNE` | operateur | **non** | un staging externe est ingéré puis qualifié |
| `CONCURRENCE` | operateur | **non** | le comportement sous concurrence est mesuré et borné |
| `SYNC_INCREMENTALE` | operateur | **non** | une synchronisation incrémentale est prouvée sans perte ni doublon |
| `ROLLBACK` | operateur | **oui** | le rollback de la RELEASE de production est éprouvé. Le rollback de la base vectorielle de staging, prouvé au lot BK, ne ferme pas celui-ci : ce ne sont pas les mêmes objets |
| `MANIFESTE_PRODUCTION` | operateur | **non** | un manifeste de readiness de production est signé |
| `NON_PDF_REACQUISITION` | operateur | **oui** | les 37 ressources servables sont présentes au store durable canonique, taille et SHA-256 conformes |

## Preuves des blocages fermés

### `C2`

- condition : une ingestion multilevel réelle aboutit et est rejouable
- vérification : Preuve d'exécution et de conformité cryptographique de l'ingestion multilevel réelle (C2) : banc de test réel réétabli et rejoué avec succès, zéro conteneur résiduel, autorités intègres.

Ce que cette fermeture ne ferme pas :

- C1 (Autorité de release et couverture promue : 26 contenus refusés promus)
- COCKPIT_E2E (Cockpit bout en bout contre l'API de retrieval)
- STAGING_EXTERNE (Staging externe ingéré et qualifié)
- CONCURRENCE (Comportement sous concurrence)
- SYNC_INCREMENTALE (Synchronisation incrémentale)
- MANIFESTE_PRODUCTION (Manifeste de readiness de production signé)
- PII_UNDECIDED (149 contenus PII undecided)
- RELEASE_PROMOTED_REFUSED_CONTENTS (26 contenus refusés)
- GO_LIVE_READY (Non autorisé tant que --assert-ready != 0)

### `C3`

- condition : le worker CLI traite un lot multilevel de bout en bout
- vérification : Preuve d'exécution et de conformité cryptographique du worker CLI multilevel (C3) : test bout en bout validé avec succès, zéro résidu Docker, autorités intègres.

Ce que cette fermeture ne ferme pas :

- C1 (Autorité de release et couverture promue : 26 contenus refusés promus)
- COCKPIT_E2E (Cockpit bout en bout contre l'API de retrieval)
- STAGING_EXTERNE (Staging externe ingéré et qualifié)
- CONCURRENCE (Comportement sous concurrence)
- SYNC_INCREMENTALE (Synchronisation incrémentale)
- MANIFESTE_PRODUCTION (Manifeste de readiness de production signé)
- PII_UNDECIDED (149 contenus PII undecided)
- RELEASE_PROMOTED_REFUSED_CONTENTS (26 contenus refusés)
- GO_LIVE_READY (Non autorisé tant que --assert-ready != 0)

### `C4`

- condition : le contrat de retrieval est validé sur le corpus SERVABLE, pas seulement sur un index de staging : les huit conditions de l écart de recherche doivent être tenues
- vérification : Validation stricte des 8 conditions de retrieval et searchability sur l'intégralité du SERVABLE_CANDIDATE_SET (2 264 contenus sans dimension bloquante de la matrice de servabilité, 55 251 vecteurs en base dédiée, 0 PII OCR, latence conforme au budget).

Ce que cette fermeture ne ferme pas :

- C1 (Autorité de release et couverture promue : 26 contenus refusés promus)
- ROLLBACK (Le rollback de la release de production reste à éprouver)
- MANIFESTE_PRODUCTION (Le manifeste de production n'est pas encore signé)

### `C5`

- condition : l autorité d accès refuse une portée non autorisée, prouvé par épreuve
- vérification : Preuve d'exécution et de conformité cryptographique du harnais de qualification d'autorité d'accès C5 : 15 scénarios de refus stricts sans mutation, isolation prouvée au niveau contrat, registre d'identité, endpoint de retrieval et prédicat SQL, aucune portée non autorisée ne peut être servie.

Ce que cette fermeture ne ferme pas :

- C1 (Autorité de release et couverture promue : 26 contenus refusés promus)
- MANIFESTE_PRODUCTION (Le manifeste de production n'est pas encore signé)

### `C6`

- condition : la qualification CAS couvre le magasin réel
- vérification : Preuve d'exécution et de conformité cryptographique de la qualification CAS (C6) : manifest conforme (NEXUS-CORPUS-CAS-MANIFEST-V1), objets relus depuis le disque, empreintes et tailles recalculées, zéro objet manquant, zéro fuite de portée, exclusion stricte des 266 contenus refusés par la matrice dont les 149 PII undecided et l'actualité périmée.

Ce que cette fermeture ne ferme pas :

- C1 (Autorité de release et couverture promue : 26 contenus refusés promus)
- C2 (Ingestion multilevel réelle bout en bout)
- C3 (Worker CLI multilevel bout en bout)
- COCKPIT_E2E (Cockpit bout en bout contre l'API de retrieval)
- STAGING_EXTERNE (Staging externe ingéré et qualifié)
- CONCURRENCE (Comportement sous concurrence)
- SYNC_INCREMENTALE (Synchronisation incrémentale)
- MANIFESTE_PRODUCTION (Manifeste de readiness de production signé)
- PII_UNDECIDED (149 contenus PII undecided)
- RELEASE_PROMOTED_REFUSED_CONTENTS (26 contenus refusés)
- GO_LIVE_READY (Non autorisé tant que --assert-ready != 0)

### `ROLLBACK`

- condition : le rollback de la RELEASE de production est éprouvé. Le rollback de la base vectorielle de staging, prouvé au lot BK, ne ferme pas celui-ci : ce ne sont pas les mêmes objets
- vérification : Preuve d'exécution et de conformité cryptographique du rehearsal atomique Docker V2 : scénario de rollback éprouvé, 4 scénarios de refus stricts sans mutation, zéro résidu conteneur/réseau/volume, zéro port exposé, aucune production touchée.

Ce que cette fermeture ne ferme pas :

- C1 (Autorité de release et couverture promue : 26 contenus refusés promus)
- MANIFESTE_PRODUCTION (Le manifeste de production n'est pas encore signé)

### `NON_PDF_REACQUISITION`

- condition : les 37 ressources servables sont présentes au store durable canonique, taille et SHA-256 conformes
- vérification : empreinte sha256 RECALCULÉE sur les octets présents, comparée ligne à ligne à la réconciliation ; les tailles sont comparées au manifeste

Ce que cette fermeture ne ferme pas :

- la revue PII
- l'adoption de la politique d'actualite
- les bloqueurs de qualification
- le go-live lui-meme

