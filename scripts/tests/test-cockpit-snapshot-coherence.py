from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts/lib/validate_cockpit_snapshots.py"
SOURCES_JSON = REPO_ROOT / "services/cockpit/src/data/sources.json"
SOURCES_YAML = REPO_ROOT / "services/rag-pedago/configs/eduscol_sources.yml"
COLLECTIONS_JSON = REPO_ROOT / "services/cockpit/src/data/collections.json"
COLLECTIONS_YAML = REPO_ROOT / "services/rag-engine/configs/rag_collections.yml"


class CockpitSnapshotCoherenceTest(unittest.TestCase):
    def run_validator(
        self,
        *,
        collections: list[dict[str, object]] | None = None,
        collections_yaml: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            mutated_collections = Path(tmp) / "collections.json"
            mutated_collections_yaml = Path(tmp) / "rag_collections.yml"
            if collections is None:
                mutated_collections.write_bytes(COLLECTIONS_JSON.read_bytes())
            else:
                mutated_collections.write_text(
                    json.dumps(collections, ensure_ascii=False),
                    encoding="utf-8",
                )
            mutated_collections_yaml.write_text(
                collections_yaml
                if collections_yaml is not None
                else COLLECTIONS_YAML.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    str(SOURCES_JSON),
                    str(SOURCES_YAML),
                    str(mutated_collections),
                    str(mutated_collections_yaml),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    def load_collections(self) -> list[dict[str, object]]:
        return json.loads(COLLECTIONS_JSON.read_text(encoding="utf-8"))

    def test_snapshots_canoniques_sont_exhaustivement_concordants(self) -> None:
        expected_count = len(self.load_collections())
        result = self.run_validator()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS (20 sources)", result.stdout)
        self.assertIn(
            f"PASS ({expected_count} collections; catalogue uniquement, corpus non validé)",
            result.stdout,
        )

    def test_compteur_collections_est_derive_des_deux_sources_canoniques(self) -> None:
        collections = self.load_collections()
        extra = deepcopy(collections[0])
        extra["name"] = "rag_nexus_collection_compteur_derive"
        extra["instanciee"] = False
        canonical = yaml.safe_load(COLLECTIONS_YAML.read_text(encoding="utf-8"))
        canonical["collections"][extra["name"]] = {
            **{key: value for key, value in extra.items() if key != "name"},
            "session_policy": "declared_or_null",
        }
        mutated = yaml.safe_dump(canonical, sort_keys=False, allow_unicode=True)

        result = self.run_validator(
            collections=[*collections, extra],
            collections_yaml=mutated,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"PASS ({len(collections) + 1} collections", result.stdout)

    def test_collection_manquante_est_rejetee(self) -> None:
        collections = self.load_collections()

        result = self.run_validator(collections=collections[1:])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("entrée manquante", result.stderr)

    def test_collection_surnumeraire_est_rejetee(self) -> None:
        collections = self.load_collections()
        extra = deepcopy(collections[0])
        extra["name"] = "rag_nexus_collection_surnumeraire"

        result = self.run_validator(collections=[*collections, extra])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("entrée surnuméraire", result.stderr)

    def test_nom_de_collection_duplique_est_rejete(self) -> None:
        collections = self.load_collections()
        duplicate = deepcopy(collections[0])

        result = self.run_validator(collections=[*collections, duplicate])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nom dupliqué", result.stderr)

    def test_cle_de_collection_yaml_dupliquee_est_rejetee(self) -> None:
        canonical = COLLECTIONS_YAML.read_text(encoding="utf-8")
        duplicate = "\n  rag_nexus_nsi_premiere_specialite: {}\n"
        mutated = canonical.replace("\ndomains:\n", f"{duplicate}\ndomains:\n")

        result = self.run_validator(collections_yaml=mutated)

        self.assertEqual(mutated.count("rag_nexus_nsi_premiere_specialite:"), 2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clé dupliquée", result.stderr)

    def test_toute_derive_de_champ_canonique_est_rejetee(self) -> None:
        baseline = self.load_collections()
        mutations: dict[str, object] = {
            "matiere": "matiere_mutante",
            "niveau": "niveau_mutant",
            "voie": "voie_mutante",
            "statut": "statut_mutant",
            "domain": "domain_mutant",
            "taxonomy_file": "taxonomy/mutante.yml",
            "instanciee": not baseline[0]["instanciee"],
        }

        for field, mutated_value in mutations.items():
            with self.subTest(field=field):
                collections = deepcopy(baseline)
                collections[0][field] = mutated_value

                result = self.run_validator(collections=collections)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f".{field}", result.stderr)


if __name__ == "__main__":
    unittest.main()
