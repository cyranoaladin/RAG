# Rapport d'Ingénierie & Consigne de Gouvernance — Bascule Cockpit & Moteur (29 août 2026)

## 1. Transmission Formelle de la Spécification D-20 (a) [Plan Moteur & BFF]

> **Objet** : Découplage de l'ouverture du service et dégradation fine par collection.
> **Destinataire** : Instance moteur (rag-engine), lot de déploiement et orchestration BFF.
> **Portée** : Endpoint POST /search/v2 et middleware d'autorisation de scope.

### Spécification Technique Opposable :
1. **Règle de service** : La recherche POST /search/v2 est honorée dès lors qu'au moins une collection demandée par le client et autorisée dans son scope signé est prête (ready: true).
2. **Condition de refus 503** : Le code HTTP 503 (avec le motif launch_not_ready) est strictement réservé au cas où aucune collection du scope signé n'est prête (ready_collections == 0).
3. **Invariant de sûreté (Non négociable)** : D-20 assouplit le seuil global d'ouverture de service mais ne modifie jamais le prédicat de sûreté SQL. Toute extraction dense/lexicale reste inconditionnellement filtrée par review_status = 'reviewed'. Une collection non prête ne renvoie aucun résultat, empêchant toute fuite de chunks non vérifiés.

---

## 2. Invariants d'Interface Livrés dans Cockpit (PR #140)

- **D-1bis** : Bouton conversationnel « Répondre avec sources » et appel runChat() retirés de SearchSection.tsx.
- **D-10** : Le sélecteur de recherche n'expose et ne permet la sélection que des collections ready: true (fournies par le croisement strict avec /collections/readiness).
- **D-20 (b)** : L'interface calcule dynamiquement et affiche nominativement les matières disponibles vs à venir pour le profil de l'utilisateur connecté.
