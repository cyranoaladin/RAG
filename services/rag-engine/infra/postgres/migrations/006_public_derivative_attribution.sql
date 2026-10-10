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
                is_text_derivative AND licensor IS NOT NULL AND btrim(licensor) <> ''
                AND licence_id IS NOT NULL AND btrim(licence_id) <> ''
                AND source_updated_at IS NOT NULL AND btrim(source_updated_at) <> ''
                AND derivative_notice IS NOT NULL AND btrim(derivative_notice) <> ''
            )
        );
