#!/usr/bin/env python3
"""Build referentiel coverage report: skeleton vs fill."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRE = ROOT / "data" / "programmes" / "registre_programmes.yml"
TAXONOMY_ROOT = ROOT / "taxonomy"
CHUNKS_DIR = ROOT / "data" / "chunks"
OUTPUT = ROOT / "data" / "programmes" / "couverture_referentiel.md"
SKIP_DIRS = {"common", "exams", "proposals"}


def _count_taxonomies() -> dict[str, int]:
    """Count notions per (matiere, niveau) from taxonomy files."""
    from schema.taxonomy import TaxonomySpec
    counts: dict[str, int] = {}
    for yml in sorted(TAXONOMY_ROOT.rglob("*.yml")):
        if yml.parent.name in SKIP_DIRS:
            continue
        try:
            data = yaml.safe_load(yml.read_text(encoding="utf-8"))
            spec = TaxonomySpec.model_validate(data)
            key = f"{spec.matiere}_{spec.niveau.value}"
            counts[key] = len(spec.known_notion_ids)
        except Exception:
            continue
    return counts


def _count_chunks() -> dict[str, int]:
    """Count chunks per (matiere, niveau) from chunk files."""
    counts: dict[str, int] = {}
    for jsonl in sorted(CHUNKS_DIR.rglob("*.jsonl")):
        niveau = jsonl.parent.name
        matiere = jsonl.stem.split("_")[0]
        key = f"{matiere}_{niveau}"
        line_count = len([ln for ln in jsonl.read_text().strip().split("\n") if ln.strip()])
        counts[key] = counts.get(key, 0) + line_count
    return counts


def main() -> int:
    sys.path.insert(0, str(ROOT))
    registre = yaml.safe_load(REGISTRE.read_text(encoding="utf-8"))
    programmes = registre.get("programmes", [])
    taxo_counts = _count_taxonomies()
    chunk_counts = _count_chunks()

    lines = ["# Couverture référentiel — squelette vs remplissage\n"]
    lines.append(f"Programmes inventoriés : **{len(programmes)}**\n")

    by_niveau: dict[str, list] = {}
    for p in programmes:
        niv = p["niveau"]
        by_niveau.setdefault(niv, []).append(p)

    zero_fill = []

    for niveau in ["terminale", "premiere", "seconde", "troisieme"]:
        progs = by_niveau.get(niveau, [])
        if not progs:
            continue
        lines.append(f"\n## {niveau.capitalize()} ({len(progs)} programmes)\n")
        lines.append("| Matière | Type | Taxonomie | Notions | Chunks | Statut taxo |")
        lines.append("|---|---|---|---|---|---|")

        for p in progs:
            mat = p["matiere"]
            typ = p.get("type", "?")
            stat = p.get("statut_taxonomie", "?")
            key = f"{mat}_{niveau}"
            notions = taxo_counts.get(key, 0)
            chunks = chunk_counts.get(key, 0)
            has_taxo = "oui" if notions > 0 else "non"
            lines.append(f"| {mat} | {typ} | {has_taxo} | {notions} | {chunks} | {stat} |")
            if notions == 0 and chunks == 0:
                zero_fill.append(f"{niveau}/{mat} ({typ})")

    lines.append(f"\n## Programmes à 0% remplissage ({len(zero_fill)})\n")
    for z in zero_fill:
        lines.append(f"- {z}")

    lines.append("\n## Résumé\n")
    total_with_taxo = sum(1 for p in programmes if taxo_counts.get(f"{p['matiere']}_{p['niveau']}", 0) > 0)
    total_with_chunks = sum(1 for p in programmes if chunk_counts.get(f"{p['matiere']}_{p['niveau']}", 0) > 0)
    lines.append(f"- Squelette (taxonomie existante) : {total_with_taxo}/{len(programmes)}")
    lines.append(f"- Remplissage (chunks indexés) : {total_with_chunks}/{len(programmes)}")
    lines.append(f"- Programmes à 0% : {len(zero_fill)}/{len(programmes)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {OUTPUT}")
    print(f"Squelette: {total_with_taxo}/{len(programmes)}, Remplissage: {total_with_chunks}/{len(programmes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
