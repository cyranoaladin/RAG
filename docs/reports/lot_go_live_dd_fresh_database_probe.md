# Lot DD — les contrôles d'une base neuve ne nomment aucune table absente

- Branche : `go-live/dd-fresh-database-probe`
- Base : `16e14e70d062555a7b40dd94e5ddf83b6da0946d` (main après #254, lot DC)

## 1. Le défaut, constaté sur le staging

Exécution de l'autorisation DC, le 2026-09-24 :
1. Le pré-vol réel est conforme (§ 3).
2. `backup_before_migration` : la sauvegarde de `ragdb` est faite
   (`dc-20260924T211122Z`, sha256 `4ef89e86…`).
3. `database_creation` : `createdb` crée `ragdb_profile_gate_v4`. Le contrôle
   « base vierge » qui suit échoue alors :
   `ERROR: relation "public.rag_chunks" does not exist`, et l'orchestrateur
   s'arrête (fail-closed).

**Cause.** Le contrôle protégeait chaque table par
`CASE WHEN to_regclass(…) IS NULL THEN 0 ELSE (SELECT count(*) FROM …) END`.
Or PostgreSQL résout les noms de relation à l'analyse, même dans une branche
jamais exécutée : sur une base neuve, sans aucune table, la requête échoue.
Elle n'avait été validée que sur `ragdb`, où ces tables existent. Les deux
contrôles « tête 0 avant migration » ont le même défaut.

## 2. Le correctif

`vide_cible` et le nouveau `tete_si_presente <schéma>` ne nomment plus aucune
relation. Les tables présentes sont trouvées dans `pg_class`, puis comptées
par `query_to_xml`, toujours en lecture seule. Le résultat est identique
lorsque les tables existent, et vaut 0 lorsqu'elles sont absentes.

Aucune garde n'est relâchée : les mêmes quantités sont exigées, aux mêmes
étapes.

## 3. Preuves

| Épreuve | Résultat |
|---|---|
| SQL généré par le script corrigé, exécuté en lecture seule sur le serveur | `ragdb_profile_gate_v4` : vide 0, têtes 0/0 ; `ragdb` : 1 740 lignes (730 + 26 + 26 + 479 + 479), têtes 4/15, soit les comptes connus |
| Nouveaux tests (4) contre le script de `main` | 4 échecs (rouge) |
| Nouveaux tests contre le script corrigé | verts ; 196 tests V4 réussis |

État du staging après l'arrêt, constaté en lecture seule :
- `ragdb` strictement inchangée (têtes, comptes, empreintes) ;
- `ragdb_profile_gate_v4` en UTF8/C/C, 0 relation, schéma `public` seul,
  extension `plpgsql` seule, donc vierge.

Après fusion, le plan reprend par un nouveau pré-vol. Celui-ci constate la
base dédiée **vierge**, et l'étape de création la revérifie sans rejouer
`createdb`, comme le prévoit le plan.

Aucune autre écriture n'a eu lieu.
