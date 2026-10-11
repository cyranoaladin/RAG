# Lot 2026-10-11 — horloge des tests du successeur A historique

Le paquet préparatoire `student-public-successor-20261010-fcc84331e7700042` a expiré le **2026-10-11 à 13:39:22.520 UTC**, conformément à son `preparation-index.json`. Le refus du paquet à l'heure courante est attendu et reste en vigueur. La CI du `main` issu de #328 (`25605df14773460c8cbed4d71150b50cc0939cec`, run [38144870305](https://github.com/cyranoaladin/RAG/actions/runs/38144870305)) est devenue rouge après cette expiration : des tests de structure et de sabotage rejouaient ce paquet scellé avec l'horloge réelle, puis attendaient un contrôle ultérieur. Les jobs `scripts/tests`, `packages/release-chain` et `services/rag-engine` étaient affectés ; les onze autres jobs de cette CI étaient verts.

Les tests qui examinent les **octets historiques** utilisent maintenant l'instant explicite `2026-10-10T21:00:00Z`, à l'intérieur de la fenêtre scellée. Les tests d'expiration gardent leurs assertions de refus, y compris à la borne exacte dans `test_content_currentness_expires_at_the_sealed_limit`. Aucun code de production, manifeste, durée de validité, décision de droits ou scope n'est modifié. En particulier, cette correction de tests ne remet pas A en vigueur pour l'émission B, le staging ou la production.

Vérification dans un nouveau worktree dérivé de `main=25605df1`, avec venv propre et installations éditables pointant exclusivement vers ses trois packages locaux :

- `scripts/tests` : **1 377 passés, 17 ignorés** ;
- `packages/release-chain/tests` : **107 passés** ;
- tests ciblés Worker A/B : **14 passés** ;
- Ruff sur les six fichiers de tests modifiés et `git diff --check` : **verts**.

Le successeur public A doit toujours être reconstruit à partir de preuves source fraîches, puis soumis à une nouvelle revue exacte de politique/scope liée à sa nouvelle ancre. Aucune preuve de go-live ni de déploiement n'est revendiquée par ce lot.
