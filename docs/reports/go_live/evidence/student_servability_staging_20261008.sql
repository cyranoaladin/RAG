BEGIN READ ONLY;

SELECT current_database() AS database_name, current_user AS database_role,
       current_setting('server_version') AS postgres_version,
       (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector_version;

SELECT p.collection,
       count(DISTINCT p.placement_id) AS placements,
       count(DISTINCT p.artifact_id) AS artifacts,
       count(DISTINCT c.chunk_id) AS scope_chunks,
       string_agg(DISTINCT p.visibility, ',') AS visibilities,
       count(DISTINCT p.placement_id) FILTER (WHERE p.visibility = 'public') AS public_placements,
       bool_and(a.rights = 'officiel_public') AS rights_public,
       bool_and(p.placement_status = 'active'
                AND p.review_status = 'reviewed'
                AND p.currentness IN ('current', 'official_snapshot')) AS governed_active
  FROM public.rag_artifact_placements AS p
  JOIN public.rag_artifacts AS a ON a.artifact_id = p.artifact_id
  JOIN public.rag_chunks AS c ON c.artifact_id = p.artifact_id
 GROUP BY p.collection
 ORDER BY p.collection;

SELECT (SELECT count(DISTINCT collection) FROM public.rag_artifact_placements) AS collections,
       (SELECT count(*) FROM public.rag_artifacts) AS artifacts,
       (SELECT count(*) FROM public.rag_artifact_placements) AS placements,
       (SELECT count(*) FROM public.rag_chunks) AS chunks;

ROLLBACK;
