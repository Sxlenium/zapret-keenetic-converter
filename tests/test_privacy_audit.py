from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.audit_release import scan


class PrivacyAuditTest(unittest.TestCase):
    def test_allows_explicit_version_but_rejects_same_digits_as_address(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            example = Path(temporary) / "example.txt"
            example.write_text("zapret2 v1.0.5.2\n", encoding="utf-8")
            self.assertEqual(scan(example), [])
            address = ".".join(["1", "0", "5", "2"])
            example.write_text(address + "\n", encoding="utf-8")
            self.assertEqual(scan(example), [f"public IPv4 address: {address}"])

    def test_allows_cloudflare_route_example(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            example = Path(temporary) / "example.txt"
            example.write_text("ip route get 1.1.1.1\n", encoding="utf-8")
            self.assertEqual(scan(example), [])

    def test_rejects_other_public_address(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            example = Path(temporary) / "example.txt"
            public_address = ".".join(["8"] * 4)
            example.write_text(f"203.0.113.8\n{public_address}\n", encoding="utf-8")
            self.assertEqual(scan(example), [f"public IPv4 address: {public_address}"])


if __name__ == "__main__":
    unittest.main()
