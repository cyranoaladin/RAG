BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT 'DB',current_database(),(SELECT oid FROM pg_database WHERE datname=current_database()),(SELECT count(*) FROM public.rag_chunks),(SELECT count(*) FROM public.rag_artifacts),(SELECT count(*) FROM public.rag_artifact_placements),(SELECT max(indexed_at) FROM public.rag_chunks),(SELECT max(created_at) FROM public.rag_artifact_placements);
WITH ids(artifact_id,collection) AS (VALUES
('50cdfb015febbbc184334b3ff66162b3e2ca234c29d2d3bd9051fd16142a82bf','rag_nexus_hggsp_terminale_specialite'),
('e772ccd8d680588dcd898c2e10fd7603fa540027b4140f3c4318fc5d90badf8e','rag_nexus_hlp_premiere_specialite'),
('2ef53e02a4e1aff55d251484af299dc9a68831fc008a5003b8773cf88dfd323b','rag_nexus_hlp_terminale_specialite'),
('202ef17f4c78e680b41ea2feda10cbb28e01b3f6f170d8c4e958bdb89708ef14','rag_nexus_ses_premiere_specialite'),
('06e491d369c5164d9f746176edeef45363cef53d3de2d5fb55153e6e96f98f2e','rag_nexus_ses_premiere_specialite'),
('1ea3df5ec2e428b297007de865ac550f1cee14a5eccea2ec65b07841b0f35d31','rag_nexus_svt_premiere_specialite'),
('3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6','rag_nexus_svt_premiere_specialite')
) SELECT 'SOURCE',ids.artifact_id,ids.collection,a.rights,p.currentness,p.review_status,p.placement_status,p.visibility,count(DISTINCT c.chunk_id),min(c.page_start),max(c.page_end)
FROM ids LEFT JOIN public.rag_artifacts a ON a.artifact_id=ids.artifact_id
LEFT JOIN public.rag_artifact_placements p ON p.artifact_id=ids.artifact_id AND p.collection=ids.collection AND p.placement_status='active' AND p.review_status='reviewed'
LEFT JOIN public.rag_chunks c ON c.artifact_id=p.artifact_id
GROUP BY ids.artifact_id,ids.collection,a.rights,p.currentness,p.review_status,p.placement_status,p.visibility ORDER BY ids.collection,ids.artifact_id;
SELECT 'HLP1_SAME_CHUNK',count(DISTINCT c.chunk_id) FROM public.rag_chunks c JOIN public.rag_artifact_placements p USING(artifact_id) WHERE p.collection='rag_nexus_hlp_premiere_specialite' AND p.placement_status='active' AND p.review_status='reviewed' AND p.currentness IN ('current','official_snapshot') AND lower(c.text) LIKE '%persuad%' AND lower(c.text) LIKE '%convainc%';
SELECT 'HLPT_ARENDT_ARTIFACTS',count(DISTINCT c.artifact_id) FROM public.rag_chunks c JOIN public.rag_artifact_placements p USING(artifact_id) WHERE p.collection='rag_nexus_hlp_terminale_specialite' AND p.placement_status='active' AND p.review_status='reviewed' AND p.currentness IN ('current','official_snapshot') AND lower(c.text) LIKE '%arendt%';
SELECT 'HLPT_ARENDT_TRAVAIL_SAME_CHUNK',count(DISTINCT c.chunk_id) FROM public.rag_chunks c JOIN public.rag_artifact_placements p USING(artifact_id) WHERE p.collection='rag_nexus_hlp_terminale_specialite' AND p.placement_status='active' AND p.review_status='reviewed' AND p.currentness IN ('current','official_snapshot') AND lower(c.text) LIKE '%arendt%' AND lower(c.text) LIKE '%travail%';
SELECT 'SVT_ORACLE_MUTAT_PROTEIN_SAME_CHUNK',count(DISTINCT c.chunk_id) FROM public.rag_chunks c JOIN public.rag_artifact_placements p USING(artifact_id) WHERE c.artifact_id='1ea3df5ec2e428b297007de865ac550f1cee14a5eccea2ec65b07841b0f35d31' AND p.collection='rag_nexus_svt_premiere_specialite' AND p.placement_status='active' AND p.review_status='reviewed' AND p.currentness IN ('current','official_snapshot') AND lower(c.text) LIKE '%mutat%' AND translate(lower(c.text),'é','e') LIKE '%protein%';
WITH q(collection,case_id,query) AS (VALUES
('rag_nexus_hggsp_terminale_specialite','factual',$q$Quelles formes prennent les conflits armés contemporains ?$q$),
('rag_nexus_hlp_premiere_specialite','factual',$q$Comment la rhétorique aide-t-elle à convaincre un auditoire ?$q$),
('rag_nexus_hlp_premiere_specialite','notion',$q$Quelle différence entre persuader et convaincre ?$q$),
('rag_nexus_hlp_terminale_specialite','notion',$q$Que signifie le travail chez Hannah Arendt ?$q$),
('rag_nexus_ses_premiere_specialite','notion',$q$Qu'est-ce que l'équilibre concurrentiel ?$q$),
('rag_nexus_svt_premiere_specialite','factual',$q$Comment une mutation de l'ADN peut-elle modifier une protéine ?$q$)
) SELECT 'LEXICAL',q.collection,q.case_id,count(DISTINCT c.chunk_id) FILTER (WHERE c.text_tsv @@ plainto_tsquery('french',q.query)) FROM q LEFT JOIN public.rag_artifact_placements p ON p.collection=q.collection AND p.placement_status='active' AND p.review_status='reviewed' AND p.currentness IN ('current','official_snapshot') LEFT JOIN public.rag_chunks c ON c.artifact_id=p.artifact_id GROUP BY q.collection,q.case_id ORDER BY q.collection,q.case_id;
COMMIT;
