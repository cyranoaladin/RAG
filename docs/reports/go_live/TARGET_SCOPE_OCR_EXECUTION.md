# Targeted OCR Execution — 22 Documents Without Extractable Text

- kind : `NEXUS-TARGET-SCOPE-OCR-EXECUTION-V1`
- scope : `SERVABLE_CANDIDATE_SET` — 22 contents targeted
- target documents : 22
- documents processed : 22
- total pages processed : 338
- pages requiring OCR : 68
- pages with native text kept : 255
- empty/ignorable pages : 4

## PII Guard Clearance

- `pii_scan_policy` : `services/rag-pedago/configs/pii_gate_policy.yml`
- `pii_matches_detected` : **0**
- `pii_clearance` : `True`

## Token-Budgeted Rechunking

- `target_token_budget` : 384 tokens
- `model_sequence_limit` : 512 tokens
- `total_chunks_produced` : **532**
- `ocr_derived_chunks` : **185**
- `native_derived_chunks` : **347**
- `max_tokens_observed` : 384
- `chunks_over_limit` : **0**
- `unique_pages_covered` : 323

## Vector Store Incremental Audit

- previous passages : 54719
- new passages added : 532
- new total passages : **55251**
- previous vectorized contents : 2242
- new vectorized contents : **2264** (100.0%)

## Compliance

- Production untouched : `true`
- Review DB untouched : `true`
- Current switch : `0`
- PII undecided unchanged : `true` (149 open decisions preserved)

## What this proves

- Proves that 100% of the 2264 authorized contents now possess valid passages under token limit.
- Proves that no PII exists in the OCR-extracted or native text of these 22 documents.
- Closes condition `target_scope_searchable`.
