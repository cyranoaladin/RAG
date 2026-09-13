# Blocages de qualification du go-live

- kind : `NEXUS-GO-LIVE-QUALIFICATION-BLOCKERS-V2`
- ouverts : **12** / fermés : 1

> État DÉRIVÉ, jamais tenu à la main. Un blocage sans vérificateur reste ouvert. `closed=true` avec `proof=null` est refusé à la construction.

| Blocage | Propriétaire | Fermé | Condition de fermeture |
|---|---|---|---|
| `C1` | operateur | **non** | une release gouvernée couvre l ensemble promu, sans contenu refusé |
| `C2` | session H2-C externe | **non** | une ingestion multilevel réelle aboutit et est rejouable |
| `C3` | session H2-C externe | **non** | le worker CLI traite un lot multilevel de bout en bout |
| `C4` | operateur | **non** | le contrat de retrieval est validé sur le corpus SERVABLE, pas seulement sur un index de staging : les huit conditions de l écart de recherche doivent être tenues |
| `C5` | operateur | **non** | l autorité d accès refuse une portée non autorisée, prouvé par épreuve |
| `C6` | operateur | **non** | la qualification CAS couvre le magasin réel |
| `COCKPIT_E2E` | operateur | **non** | le cockpit interroge l API de retrieval de bout en bout |
| `STAGING_EXTERNE` | operateur | **non** | un staging externe est ingéré puis qualifié |
| `CONCURRENCE` | operateur | **non** | le comportement sous concurrence est mesuré et borné |
| `SYNC_INCREMENTALE` | operateur | **non** | une synchronisation incrémentale est prouvée sans perte ni doublon |
| `ROLLBACK` | operateur | **non** | le rollback de la RELEASE de production est éprouvé. Le rollback de la base vectorielle de staging, prouvé au lot BK, ne ferme pas celui-ci : ce ne sont pas les mêmes objets |
| `MANIFESTE_PRODUCTION` | operateur | **non** | un manifeste de readiness de production est signé |
| `NON_PDF_REACQUISITION` | operateur | **oui** | les 37 ressources servables sont présentes au store durable canonique, taille et SHA-256 conformes |

## Preuves des blocages fermés

### `NON_PDF_REACQUISITION`

- condition : les 37 ressources servables sont présentes au store durable canonique, taille et SHA-256 conformes
- vérification : empreinte sha256 RECALCULÉE sur les octets présents, comparée ligne à ligne à la réconciliation ; les tailles sont comparées au manifeste

Ce que cette fermeture ne ferme pas :

- la revue PII
- l'adoption de la politique d'actualite
- les bloqueurs de qualification
- le go-live lui-meme

