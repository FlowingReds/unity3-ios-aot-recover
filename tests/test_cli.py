from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aot_recover.cli import (
    RecoveryError,
    _resolve_reference_managed,
    _write_combined_labels,
    _write_donor_index,
    build_parser,
)


class CliTests(unittest.TestCase):
    def test_resolves_and_deduplicates_reference_managed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            main = directory / "Assembly-CSharp.dll"
            firstpass = directory / "Assembly-CSharp-firstpass.dll"
            main.write_bytes(b"main")
            firstpass.write_bytes(b"firstpass")
            (directory / "UnityEngine.dll").write_bytes(b"engine")

            result = _resolve_reference_managed([str(directory), str(main)])

            self.assertEqual([firstpass.resolve(), main.resolve()], result)

    def test_rejects_reference_directory_without_game_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RecoveryError, "no Assembly-CSharp DLLs"):
                _resolve_reference_managed([temporary])

    def test_parser_accepts_repeated_reference_inputs(self) -> None:
        args = build_parser().parse_args(
            ["game.ipa", "-o", "out", "--reference-managed", "one.dll", "--reference-managed", "two"]
        )
        self.assertEqual(["one.dll", "two"], args.reference_managed)

    def test_writes_donor_json_and_stable_csv_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            report = {
                "schemaVersion": 1,
                "matches": [
                    {
                        "targetAssembly": "Assembly-CSharp",
                        "targetToken": "0x06000001",
                        "donorAssembly": "Assembly-CSharp",
                        "donorToken": "0x06000002",
                        "confidenceTier": "A",
                    }
                ],
            }

            _write_donor_index(output, report)

            with (output / "reference-donor" / "matches.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual("A", rows[0]["confidenceTier"])
            self.assertEqual("0x06000001", rows[0]["targetToken"])
            self.assertTrue((output / "reference-donor" / "index.json").is_file())

    def test_writes_ghidra_tsv_for_a_mapped_method(self) -> None:
        method = {
            "token": "0x06000001",
            "address": 0x1500,
            "raw_address": 0x1501,
            "thumb": True,
            "estimated_size": 32,
            "declaringType": "Fixture.Type",
            "name": "Run",
            "fullName": "System.Void Fixture.Type::Run()",
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _write_combined_labels(directory, [method])
            rows = (directory / "ghidra-method-map.tsv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(rows))
            self.assertIn("0x1500\t0x1501\t1\t32", rows[1])


if __name__ == "__main__":
    unittest.main()
