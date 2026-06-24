"""Pedagogical chunker — structure-aware markdown splitting for the Nexus RAG corpus.

Splits markdown files by heading hierarchy (H1/H2/H3), produces chunks with
ChunkMetadata-compatible tagging.  No LLM, no embeddings, no network.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TARGET_MAX_TOKENS = 500  # soft target — subdivide if exceeded
OVERLAP_SENTENCES = 1    # sentences of overlap between sub-chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~0.75 tokens per word for French."""
    return max(1, int(len(text.split()) * 1.3))


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (basic French-aware)."""
    parts = re.split(r'(?<=[.!?;])\s+', text.strip())
    return [s for s in parts if s.strip()]


def _heading_level(line: str) -> int | None:
    m = re.match(r'^(#{1,6})\s', line)
    return len(m.group(1)) if m else None


def _heading_text(line: str) -> str:
    return re.sub(r'^#{1,6}\s+', '', line).strip()


# ---------------------------------------------------------------------------
# Section tree parser
# ---------------------------------------------------------------------------

@dataclass
class Section:
    title: str
    level: int
    lines: list[str] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)
    path: list[str] = field(default_factory=list)  # breadcrumb titles


def parse_sections(text: str) -> list[Section]:
    """Parse markdown into a tree of sections by heading level."""
    lines = text.split('\n')
    root_sections: list[Section] = []
    stack: list[Section] = []

    for line in lines:
        level = _heading_level(line)
        if level is not None:
            title = _heading_text(line)
            section = Section(title=title, level=level)
            # Find parent
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                parent = stack[-1]
                section.path = parent.path + [parent.title]
                parent.children.append(section)
            else:
                section.path = []
                root_sections.append(section)
            stack.append(section)
        else:
            if stack:
                stack[-1].lines.append(line)
            # Lines before first heading are ignored (typically metadata)

    return root_sections


# ---------------------------------------------------------------------------
# Chunk production
# ---------------------------------------------------------------------------

@dataclass
class RawChunk:
    text: str
    section_path: list[str]
    section_title: str
    chunk_index: int = 0


def _flatten_section(section: Section, prefix: list[str] | None = None) -> list[RawChunk]:
    """Recursively flatten a section tree into chunks."""
    if prefix is None:
        prefix = section.path

    chunks: list[RawChunk] = []
    body = '\n'.join(section.lines).strip()
    full_path = prefix + [section.title]

    if body:
        # Prepend section breadcrumb for context
        breadcrumb = ' › '.join(full_path)
        body_with_title = f"[{breadcrumb}]\n\n{body}"
        tokens = _estimate_tokens(body_with_title)
        if tokens <= TARGET_MAX_TOKENS:
            chunks.append(RawChunk(
                text=body_with_title,
                section_path=full_path,
                section_title=section.title,
            ))
        else:
            # Subdivide with overlap, preserving sentence boundaries
            sub_chunks = _subdivide(body, full_path, section.title)
            chunks.extend(sub_chunks)

    for child in section.children:
        chunks.extend(_flatten_section(child, prefix=full_path))

    return chunks


def _subdivide(text: str, path: list[str], title: str) -> list[RawChunk]:
    """Split oversized text into sub-chunks with overlap."""
    sentences = _split_sentences(text)
    if not sentences:
        return [RawChunk(text=text, section_path=path, section_title=title)]

    prefix_str = ' › '.join(path)
    sub_chunks: list[RawChunk] = []
    current: list[str] = []
    current_tokens = 0
    idx = 0

    for i, sent in enumerate(sentences):
        sent_tokens = _estimate_tokens(sent)
        if current and current_tokens + sent_tokens > TARGET_MAX_TOKENS:
            chunk_text = f"[{prefix_str}]\n\n" + ' '.join(current)
            sub_chunks.append(RawChunk(
                text=chunk_text,
                section_path=path,
                section_title=title,
                chunk_index=idx,
            ))
            idx += 1
            # Overlap: keep last N sentences
            overlap = current[-OVERLAP_SENTENCES:] if OVERLAP_SENTENCES > 0 else []
            current = overlap + [sent]
            current_tokens = sum(_estimate_tokens(s) for s in current)
        else:
            current.append(sent)
            current_tokens += sent_tokens

    if current:
        chunk_text = f"[{prefix_str}]\n\n" + ' '.join(current) if idx > 0 else ' '.join(current)
        sub_chunks.append(RawChunk(
            text=chunk_text,
            section_path=path,
            section_title=title,
            chunk_index=idx,
        ))

    return sub_chunks


# ---------------------------------------------------------------------------
# Metadata tagging
# ---------------------------------------------------------------------------

@dataclass
class TaggingConfig:
    """Configuration for tagging chunks from a specific source file."""
    doc_id: str
    matiere: str
    audience: list[str]
    type_doc_default: str
    source_label: str
    source_uri: str
    rights: str
    official: bool
    notion_map: dict[str, list[str]] | None = None  # section_title_lower -> notions

    def resolve_type_doc(self, section_title: str, section_path: list[str]) -> str:
        """Heuristic to determine type_doc from section context."""
        lower = section_title.lower()
        full = ' '.join(section_path + [section_title]).lower()
        if any(k in lower for k in ('programme', 'program')):
            return 'programme_officiel'
        if any(k in lower for k in ('épreuve', 'examen', 'évaluation')):
            return 'modalite_examen'
        if any(k in lower for k in ('attendu', 'compétence')):
            return 'fiche_methode'
        if any(k in lower for k in ('exercice',)):
            return 'exercice'
        if any(k in lower for k in ('corrigé',)):
            return 'corrige'
        if any(k in lower for k in ('référentiel', 'statut', 'candidat', 'inscription',
                                      'coefficient', 'calendrier', 'modalité')):
            return 'referentiel'
        if any(k in full for k in ('note rag', 'notes rag', 'annexe')):
            return 'fiche_methode'
        return self.type_doc_default

    def resolve_notions(self, section_title: str, section_path: list[str], text: str = "") -> list[str]:
        """Map section to taxonomy notions by scanning title, path, and text."""
        if not self.notion_map:
            return []
        found: list[str] = []
        # Combine all searchable content
        searchable = (section_title + " " + " ".join(section_path) + " " + text).lower()
        for key, notions in self.notion_map.items():
            if key and len(key) > 2 and key in searchable:
                for n in notions:
                    if n and n not in found:
                        found.append(n)
        return found


def tag_chunk(raw: RawChunk, config: TaggingConfig, index: int) -> dict:
    """Produce a tagged chunk dict compatible with ChunkMetadata."""
    type_doc = config.resolve_type_doc(raw.section_title, raw.section_path)
    notions = config.resolve_notions(raw.section_title, raw.section_path, raw.text)

    return {
        "chunk_id": f"{config.doc_id}_{index:04d}",
        "text": raw.text,
        "metadata": {
            "tenant": "terminale",
            "niveau": "terminale",
            "voie": "generale",
            "matiere": config.matiere,
            "audience": config.audience,
            "type_doc": type_doc,
            "notions": notions,
            "source_label": config.source_label,
            "source_uri": config.source_uri,
            "rights": config.rights,
            "official": config.official,
            "doc_id": config.doc_id,
        },
    }


# ---------------------------------------------------------------------------
# Notion maps from taxonomy
# ---------------------------------------------------------------------------

def load_taxonomy_notion_map(yaml_path: Path) -> dict[str, list[str]]:
    """Load a taxonomy YAML and build a section-title -> notions map."""
    import yaml
    data = yaml.safe_load(yaml_path.read_text(encoding='utf-8'))
    notion_map: dict[str, list[str]] = {}
    themes = data.get('themes', [])
    for theme in themes:
        theme_name = (theme.get('label') or theme.get('nom') or theme.get('id') or '').lower().strip()
        notions = []
        for n in theme.get('notions', []):
            if isinstance(n, str) and n.strip():
                notions.append(n.strip())
            elif isinstance(n, dict):
                name = (n.get('label') or n.get('nom') or n.get('id') or '').strip()
                if name:
                    notions.append(name)
                for sn in n.get('subnotions', n.get('sous_notions', [])):
                    if isinstance(sn, str) and sn.strip():
                        notions.append(sn.strip())
        notions = [n for n in notions if n]
        if notions and theme_name:
            notion_map[theme_name] = notions
            for notion in notions:
                notion_map[notion.lower().replace('_', ' ')] = [notion]
    return notion_map


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def chunk_file(md_path: Path, config: TaggingConfig) -> list[dict]:
    """Parse a markdown file and produce tagged chunks."""
    text = md_path.read_text(encoding='utf-8')
    sections = parse_sections(text)
    raw_chunks: list[RawChunk] = []
    for section in sections:
        raw_chunks.extend(_flatten_section(section))
    tagged = [tag_chunk(raw, config, i) for i, raw in enumerate(raw_chunks)]
    return tagged


def write_jsonl(chunks: list[dict], output_path: Path) -> None:
    """Write chunks as JSONL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
