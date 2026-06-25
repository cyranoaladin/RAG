# Rapport — Lot 4.3a : Fetch pilote réel + dossier de revue

## Garde-fou durci (existence ADR)

Le garde-fou vérifie désormais que l'ADR référencé dans la baseline (`ADR-XXXX`) correspond à un fichier existant `docs/adr/ADR-XXXX*.md`. Un ADR fictif (`ADR-9999`) → FAIL. Test ajouté : 16/16 guard tests PASS.

## Résultat du fetch pilote réel

**5 URLs tentées, 5 refusées par robots.txt.**

| Notion | Matière | Domaine | Résultat |
|---|---|---|---|
| suites | maths | eduscol.education.gouv.fr | robots.txt REFUSÉ |
| derivation | maths | eduscol.education.gouv.fr | robots.txt REFUSÉ |
| probabilites_conditionnelles | maths | eduscol.education.gouv.fr | robots.txt REFUSÉ |
| recursivite | nsi | eduscol.education.gouv.fr | robots.txt REFUSÉ |
| arbres | nsi | eduscol.education.gouv.fr | robots.txt REFUSÉ |

### Analyse robots.txt par domaine

| Domaine | Scraping autorisé |
|---|---|
| `eduscol.education.gouv.fr` | **NON** |
| `www.education.gouv.fr` | **NON** |
| `cache.media.eduscol.education.gouv.fr` | **NON** |
| `cache.media.education.gouv.fr` | OUI (mais URLs 404) |

## Constat

**Le corpus ne peut pas être constitué par scraping des sites institutionnels.** Les robots.txt d'eduscol et education.gouv.fr interdisent explicitement le scraping automatique. C'est le respect de cette interdiction qui justifie un changement de stratégie.

### Alternatives à explorer

1. **Téléchargement manuel** des programmes officiels (PDF publics) + ingestion locale.
2. **Ressources sous licence ouverte** (CC-BY, CC-BY-SA) : manuels libres, IREM, sites d'enseignants sous licence explicite.
3. **Élargir la whitelist** à des sources autorisées (après vérification robots.txt).

## Dossier de revue

Versionné dans `data/acquisition/dossier_revue_4_3a.md`. Statut : **aucune entrée `à_valider`** (aucun contenu récupéré).

## Conformité

- **robots.txt respecté** : 5/5 refus, aucun contournement
- **Whitelist** : 5 domaines, aucun hors-liste tenté
- **`ingestion_allowed=false`** : rien importé au corpus
- **Garde-fou** : 17/17, ADR vérifié existant

## CI locale : 6/6 PASS
