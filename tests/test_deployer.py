from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zapret_keenetic.deployer import (
    DeploymentError,
    DeploymentSettings,
    deploy_bundle,
    normalize_router_url,
)


class FakeApi:
    def __init__(self, *, fail_first_restart: bool = False) -> None:
        self.conf = {
            "nfqws2.conf": "OLD_CONFIG\n",
            "nfqws2.conf-opkg": 'NFQWS_BASE_ARGS=""\nNFQWS_ARGS=""\nNFQWS_ARGS_IPSET=""\nNFQWS_ARGS_CUSTOM=""\n',
        }
        self.lists = {"existing.list": "old.example\n"}
        self.logged_in = False
        self.fail_first_restart = fail_first_restart
        self.restart_count = 0

    def login(self, username: str, password: str) -> None:
        self.logged_in = bool(username and password)

    def call(self, command: str, **fields: str) -> dict[str, object]:
        if command == "filenames":
            files = self.lists if fields["type"] == "list" else self.conf
            return {"status": 0, "files": list(files)}
        if command == "filecreate":
            self.lists[fields["filename"]] = ""
            return {"status": 0}
        if command == "fileremove":
            self.lists.pop(fields["filename"], None)
            return {"status": 0}
        if command == "restart":
            self.restart_count += 1
            if self.fail_first_restart and self.restart_count == 1:
                raise DeploymentError("synthetic restart failure")
            return {"status": 0, "output": ["Started NFQWS2 service"]}
        if command == "status":
            return {"status": 0, "service": True, "nfqws2": True, "version": "test"}
        raise AssertionError(command)

    def read(self, filename: str) -> str:
        return self.conf[filename] if filename in self.conf else self.lists[filename]

    def save(self, filename: str, content: str) -> None:
        target = self.conf if filename.endswith(".conf") else self.lists
        target[filename] = content if content else "\n"


def make_bundle(root: Path) -> Path:
    bundle = root / "bundle"
    lists = bundle / "web-import" / "lists"
    lists.mkdir(parents=True)
    (bundle / "web-import" / "nfqws2.conf").write_text("NEW_CONFIG\n", encoding="utf-8")
    (lists / "existing.list").write_text("new.example\n", encoding="utf-8")
    (lists / "new.list").write_text("added.example\n", encoding="utf-8")
    return bundle


class DeployerTest(unittest.TestCase):
    def test_normalizes_router_web_url(self) -> None:
        self.assertEqual(normalize_router_url("http://192.168.1.1:90/"), "http://192.168.1.1:90/index.php")
        self.assertEqual(
            normalize_router_url("https://router.local/nfqws"),
            "https://router.local/nfqws/index.php",
        )
        with self.assertRaises(DeploymentError):
            normalize_router_url("192.168.1.1:90")

    def test_exact_install_backs_up_uploads_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = make_bundle(root)
            api = FakeApi()
            result = deploy_bundle(
                DeploymentSettings(
                    bundle=bundle,
                    password="secret",
                    mode="exact",
                    backup_root=root / "backups",
                ),
                api=api,
            )
            self.assertTrue(api.logged_in)
            self.assertEqual(api.conf["nfqws2.conf"], "NEW_CONFIG\n")
            self.assertEqual(api.lists["existing.list"], "new.example\n")
            self.assertEqual(api.lists["new.list"], "added.example\n")
            self.assertEqual((result.backup / "nfqws2.conf").read_text(), "OLD_CONFIG\n")
            self.assertEqual((result.backup / "lists" / "existing.list").read_text(), "old.example\n")
            self.assertEqual(result.service_version, "test")

    def test_failed_restart_restores_previous_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = make_bundle(root)
            api = FakeApi(fail_first_restart=True)
            with self.assertRaisesRegex(DeploymentError, "прежняя конфигурация восстановлена"):
                deploy_bundle(
                    DeploymentSettings(
                        bundle=bundle,
                        password="secret",
                        mode="exact",
                        backup_root=root / "backups",
                    ),
                    api=api,
                )
            self.assertEqual(api.conf["nfqws2.conf"], "OLD_CONFIG\n")
            self.assertEqual(api.lists["existing.list"], "old.example\n")
            self.assertNotIn("new.list", api.lists)
            self.assertEqual(api.restart_count, 2)


if __name__ == "__main__":
    unittest.main()
