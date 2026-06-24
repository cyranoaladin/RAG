from __future__ import annotations

from collections import defaultdict, deque

from pydantic import BaseModel, ConfigDict, Field

from rag_pedago.reference.index import OfficialReferenceIndex
from schema.document import DocumentMeta


class CompatibilityExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_id: str
    document_refs: list[str]
    compatible: bool
    matched_ref: str | None = None
    path: list[str] = Field(default_factory=list)
    reason: str


class OfficialReferenceResolver:
    def __init__(self, index: OfficialReferenceIndex):
        self.index = index
        self._children: dict[str, set[str]] = defaultdict(set)
        self._parents: dict[str, set[str]] = defaultdict(set)
        self._build_graph()

    def ancestors_for_ref(self, ref_id: str) -> set[str]:
        return self._walk(ref_id, self._parents)

    def descendants_for_ref(self, ref_id: str) -> set[str]:
        return self._walk(ref_id, self._children)

    def refs_for_document(self, meta: DocumentMeta) -> set[str]:
        return {
            ref
            for ref in (
                meta.official_level_ref,
                meta.official_exam_ref,
                meta.official_subject_ref,
                meta.candidate_status_ref,
                meta.establishment_context_ref,
            )
            if ref
        }

    def source_applies_to_document(self, source_id: str, meta: DocumentMeta) -> bool:
        return self.explain_source_compatibility(source_id, meta).compatible

    def claim_applies_to_document(self, claim_id: str, meta: DocumentMeta) -> bool:
        return self.explain_claim_compatibility(claim_id, meta).compatible

    def explain_source_compatibility(self, source_id: str, meta: DocumentMeta) -> CompatibilityExplanation:
        source = self.index.sources.get(source_id)
        applies_to = [] if source is None else source.applies_to
        return self._explain(source_id, applies_to, meta, "source")

    def explain_claim_compatibility(self, claim_id: str, meta: DocumentMeta) -> CompatibilityExplanation:
        claim = self.index.claims.get(claim_id)
        applies_to = [] if claim is None else claim.applies_to
        return self._explain(claim_id, applies_to, meta, "claim")

    def _build_graph(self) -> None:
        for level in self.index.levels.values():
            for exam_id in level.exam_refs:
                self._add_edge(level.level_id, exam_id)
            for subject_id in level.common_subjects:
                self._add_edge(level.level_id, subject_id)
            for subject_id in level.specialties_available:
                self._add_edge(level.level_id, subject_id)
            for subject_id in level.optional_subjects:
                self._add_edge(level.level_id, subject_id)

        for exam in self.index.exams.values():
            self._add_edge(exam.level_id, exam.exam_id)
            for candidate_type in exam.candidate_types:
                self._add_edge(exam.exam_id, candidate_type)

        for subject in self.index.subjects.values():
            self._add_edge(subject.level_id, subject.subject_id)
            for level_id in subject.allowed_level_ids:
                self._add_edge(level_id, subject.subject_id)

        self._add_edge("bac_general", "eaf")
        self._add_edge("bac_general", "anticipee_maths")
        self._add_edge("bac_general", "bac_specialite_ecrit")
        self._add_edge("bac_general", "philosophie")
        self._add_edge("bac_general", "grand_oral")
        self._add_edge("bac_general", "controle_continu_bac")
        self._add_edge("dnb", "dnb_scolaire")
        self._add_edge("dnb", "dnb_candidat_individuel")

    def _add_edge(self, parent: str, child: str) -> None:
        if parent == child:
            return
        self._children[parent].add(child)
        self._parents[child].add(parent)

    def _walk(self, ref_id: str, graph: dict[str, set[str]]) -> set[str]:
        seen: set[str] = set()
        queue: deque[str] = deque(graph.get(ref_id, set()))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(graph.get(current, set()) - seen)
        return seen

    def _explain(
        self,
        ref_id: str,
        applies_to: list[str],
        meta: DocumentMeta,
        ref_kind: str,
    ) -> CompatibilityExplanation:
        document_refs = sorted(self.refs_for_document(meta))
        paths: list[list[str]] = []

        for source_ref in applies_to:
            for path in self._compatible_paths_for_ref(source_ref, meta):
                paths.append(path)

        if paths:
            path = self._best_path(paths)
            matched_ref = path[-1]
            if len(path) == 1:
                reason = f"{ref_kind} applies directly to {matched_ref}"
            else:
                reason = f"{ref_kind} applies through aggregate {' -> '.join(path)}"
            return CompatibilityExplanation(
                ref_id=ref_id,
                document_refs=document_refs,
                compatible=True,
                matched_ref=matched_ref,
                path=path,
                reason=reason,
            )

        refs_label = ", ".join(applies_to) if applies_to else ref_id
        return CompatibilityExplanation(
            ref_id=ref_id,
            document_refs=document_refs,
            compatible=False,
            matched_ref=None,
            path=[],
            reason=f"no compatible path from {refs_label} to document refs",
        )

    def _best_path(self, paths: list[list[str]]) -> list[str]:
        return sorted(paths, key=lambda path: (0 if len(path) > 1 else 1, len(path), path))[0]

    def _compatible_paths_for_ref(self, source_ref: str, meta: DocumentMeta) -> list[list[str]]:
        paths: list[list[str]] = []
        exact_refs = [
            meta.official_level_ref,
            meta.official_subject_ref,
            meta.candidate_status_ref,
            meta.establishment_context_ref,
        ]
        paths.extend([source_ref] for ref in exact_refs if ref == source_ref)

        if meta.official_exam_ref:
            path = self._path_from_ancestor_to_descendant(source_ref, meta.official_exam_ref)
            if path is not None:
                paths.append(path)

        return paths

    def _path_from_ancestor_to_descendant(self, ancestor: str, descendant: str) -> list[str] | None:
        if ancestor == descendant:
            return [ancestor]

        queue: deque[tuple[str, list[str]]] = deque([(ancestor, [ancestor])])
        seen = {ancestor}
        while queue:
            current, path = queue.popleft()
            for child in sorted(self._children.get(current, set())):
                if child in seen:
                    continue
                next_path = [*path, child]
                if child == descendant:
                    return next_path
                seen.add(child)
                queue.append((child, next_path))
        return None
