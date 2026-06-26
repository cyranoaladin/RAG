# Rapport — Lot 11.2 : Scellement du gating + couverture réelle

## Test de gating (6 cas, non-régression)

| Cas | Résultat |
|---|---|
| `pdf_allowed=false` | BLOCKED ✓ |
| `parsing_allowed=false` | BLOCKED ✓ |
| Both `true` | ALLOWED ✓ |
| Contrat vide | BLOCKED ✓ |
| Contrat non-dict (liste) | BLOCKED ✓ |
| Contrat inexistant | BLOCKED ✓ |

Intégré à la CI via `tests/unit/test_build_correspondence_gating.py`.

## SubjectAgent metadata-only (prouvé)

Test `test_subject_agent_metadata_only_no_pdf_opened` : monkeypatch `__import__` pour faire échouer tout accès à `pypdf`. L'agent charge la correspondance depuis le JSON artefact et produit un plan priorisé — sans jamais toucher un PDF.

## Couverture réelle recomptée

**44 fichiers staging** réellement déposés (filenames uniques par source_label).
**26/38 notions trouvées (68%)** — chiffre confirmé identique au Lot 11 après correction du faux compte.

## Dette BACKLOG

DETTE-11.1-A : gating au niveau fonction (pas seulement au niveau script). Acceptable tant qu'un seul appelant.

## CI locale : 7/7 PASS, 12 gating+agent tests PASS
