-- Attribution durable des dérivés textuels publics.
-- Migration additive : les anciens PDF et chunks restent intacts ; leurs
-- quatre champs restent NULL. Les dérivés portent le paquet complet.

ALTER TABLE public.rag_artifacts
    ADD COLUMN is_text_derivative BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN licensor TEXT,
    ADD COLUMN licence_id TEXT,
    ADD COLUMN source_updated_at TEXT,
    ADD COLUMN derivative_notice TEXT,
    ADD CONSTRAINT rag_artifacts_public_attribution_complete_check
        CHECK (
            (
                NOT is_text_derivative
                AND licensor IS NULL AND licence_id IS NULL
                AND source_updated_at IS NULL AND derivative_notice IS NULL
            )
            OR (
                is_text_derivative AND licensor IS NOT NULL AND licensor ~ '[^[:space:]]'
                AND licence_id IS NOT NULL AND licence_id ~ '[^[:space:]]'
                AND source_updated_at IS NOT NULL AND source_updated_at ~ '[^[:space:]]'
                AND derivative_notice IS NOT NULL AND derivative_notice ~ '[^[:space:]]'
            )
        );
