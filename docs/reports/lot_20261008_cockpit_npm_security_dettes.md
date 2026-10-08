# Antériorité et fermeture des échecs CI — lot npm et PII du 2026-10-08

Sur le parent `ee35544bce5af74d6186ea0ef61f6902a2258ffe`, la [CI main 37730000035](https://github.com/cyranoaladin/RAG/actions/runs/37730000035) avait trois jobs rouges : `rag-pedago` (deux tests PII), `rag-engine` (trois tests PII) et `cockpit` (audit npm). Les échecs PII étaient dus aux attentes temporelles de tests relisant un reçu du 3 septembre expiré le 3 octobre ; le vérificateur le refusait correctement. L'échec Cockpit venait des avis courants `sharp`, `source-map-js` et `postcss-selector-parser`.

Le premier HEAD de la PR #285 corrigeait l'audit Cockpit mais conservait exactement les cinq échecs PII du parent. Leur antériorité est visible dans la [CI de ce HEAD](https://github.com/cyranoaladin/RAG/actions/runs/37730384367) : deux échecs `rag-pedago`, trois `rag-engine`, tandis que `services/cockpit` passait. La PR #288 a ensuite préparé les corrections de tests de qualification temporelle, intégrées dans #285 par cherry-pick du commit `fb8cf474a91c71d08e11636a252b26d4c13cf020`.

Localement, au HEAD réunissant les deux lots, les 91 tests PII ciblés du producteur et les 84 du moteur passent. La CI complète de ce nouveau HEAD doit confirmer la fermeture des cinq échecs. Cette correction ne prolonge ni le reçu expiré ni l'exception npm #284 ; elle ne dispense d'aucun contrôle d'autorité. Le renouvellement d'un reçu PII après le 23 octobre reste soumis au protocole du [rapport de qualification temporelle](lot_go_live_pii_currentness_20261008.md).

L'E2E réel Cockpit → API n'a pas été rejoué sur cette branche : modèles, corpus et preuves de release finale absents de ce worktree ; le test historique référence un ancien SHA. Il reste exigé sur le staging final avant le go-live.
