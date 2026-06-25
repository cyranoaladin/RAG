# Dossier de revue — Lot 4.3a (fetch pilote réel)

## Résultat du fetch

| # | Notion | Matière | URL | Domaine | Résultat | Raison |
|---|---|---|---|---|---|---|
| 1 | suites | maths | eduscol.education.gouv.fr/2068/... | eduscol | **REFUSÉ** | robots.txt |
| 2 | derivation | maths | eduscol.education.gouv.fr/1723/... | eduscol | **REFUSÉ** | robots.txt |
| 3 | probabilites_conditionnelles | maths | eduscol.education.gouv.fr/2068/... | eduscol | **REFUSÉ** | robots.txt |
| 4 | recursivite | nsi | eduscol.education.gouv.fr/2068/... | eduscol | **REFUSÉ** | robots.txt |
| 5 | arbres | nsi | eduscol.education.gouv.fr/2068/... | eduscol | **REFUSÉ** | robots.txt |

## Analyse robots.txt par domaine

| Domaine | robots.txt | Scraping autorisé |
|---|---|---|
| `eduscol.education.gouv.fr` | Présent, restrictif | **NON** |
| `www.education.gouv.fr` | Présent, restrictif | **NON** |
| `cache.media.eduscol.education.gouv.fr` | Présent, restrictif | **NON** |
| `cache.media.education.gouv.fr` | Présent | **OUI** (mais URLs 404) |

## Constat

**Aucun contenu récupérable** depuis les sources institutionnelles whitelistées. Les domaines `eduscol` et `education.gouv.fr` interdisent explicitement le scraping via robots.txt. Le seul domaine autorisé (`cache.media.education.gouv.fr`) retourne des 404 sur les URLs testées (programme maths terminale).

## Impact sur la stratégie d'acquisition

Le corpus ne peut pas être constitué par scraping des sites institutionnels. Alternatives à explorer au lot suivant :

1. **Sources sous licence ouverte** (CC-BY, CC-BY-SA) : manuels scolaires libres, ressources IREM, ressources pédagogiques sous licence explicite.
2. **Téléchargement manuel** des programmes officiels (PDF disponibles publiquement) + ingestion locale.
3. **Partenariats** avec les éditeurs de ressources éducatives.

## Statut : aucune entrée `à_valider`

Le dossier ne contient aucun contenu exploitable. Aucune décision de revue à prendre.

## Conformité

- robots.txt : **respecté** (100% refus, aucun contournement)
- Rate limit : non applicable (aucun fetch abouti)
- Whitelist : strictement respectée (5 domaines, aucun hors-liste)
- `ingestion_allowed` : **false** (rien importé au corpus)
