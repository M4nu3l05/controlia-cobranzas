from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from legal import documents
from legal.constants import PRIVACY_VERSION


class LegalDocumentsTests(unittest.TestCase):
    def test_document_version_reads_embedded_version(self) -> None:
        self.assertEqual(documents._document_version("Versión del documento: v2.0\n"), "v2.0")
        self.assertEqual(documents._document_version("sin versión"), "")

    def test_outdated_runtime_privacy_copy_is_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp_path = Path(raw_tmp)
            packaged_dir = tmp_path / "package" / "legal"
            packaged_dir.mkdir(parents=True)
            packaged = packaged_dir / "privacidad.txt"
            packaged.write_text(
                f"POLÍTICA NUEVA\n\nVersión del documento: {PRIVACY_VERSION}\n",
                encoding="utf-8",
            )

            config_dir = tmp_path / "config"
            runtime_file = config_dir / "legal" / "privacidad.txt"
            runtime_file.parent.mkdir(parents=True)
            runtime_file.write_text(
                "POLÍTICA ANTIGUA\n\nVersión del documento: v1.0\n",
                encoding="utf-8",
            )

            with (
                patch.object(documents, "get_config_dir", return_value=config_dir),
                patch.object(documents, "_packaged_paths", return_value=[packaged]),
            ):
                documents._ensure_config_copy("privacidad.txt")

            refreshed = runtime_file.read_text(encoding="utf-8")
            self.assertIn("POLÍTICA NUEVA", refreshed)
            self.assertIn(f"Versión del documento: {PRIVACY_VERSION}", refreshed)

    def test_current_runtime_privacy_copy_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp_path = Path(raw_tmp)
            packaged = tmp_path / "packaged.txt"
            packaged.write_text(
                f"PAQUETE\nVersión del documento: {PRIVACY_VERSION}\n",
                encoding="utf-8",
            )

            config_dir = tmp_path / "config"
            runtime_file = config_dir / "legal" / "privacidad.txt"
            runtime_file.parent.mkdir(parents=True)
            runtime_file.write_text(
                f"COPIA PERSONALIZADA\nVersión del documento: {PRIVACY_VERSION}\n",
                encoding="utf-8",
            )

            with (
                patch.object(documents, "get_config_dir", return_value=config_dir),
                patch.object(documents, "_packaged_paths", return_value=[packaged]),
            ):
                documents._ensure_config_copy("privacidad.txt")

            self.assertTrue(runtime_file.read_text(encoding="utf-8").startswith("COPIA PERSONALIZADA"))


if __name__ == "__main__":
    unittest.main()
