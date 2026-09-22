from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from zapret_keenetic.converter import ConversionError, ConverterSettings, convert, parse_batch
from zapret_keenetic.gui import discover_profiles, suggest_output
from zapret_keenetic.hybrid import build_hybrid_keenetic_config


PROFILE = r'''@echo off
set "BIN=%~dp0bin\"
set "LISTS=%~dp0lists\"
start "zapret" "%BIN%winws.exe" --wf-tcp=80,443,%GameFilterTCP% --wf-udp=443,%GameFilterUDP% ^
--filter-udp=443 --hostlist="%LISTS%list-general.txt" --dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-fake-quic="%BIN%quic.bin" --new ^
--filter-tcp=80,443 --hostlist="%LISTS%list-general.txt" --hostlist-exclude="%LISTS%list-general-user.txt" --dpi-desync=fake,multisplit --dpi-desync-fooling=ts --dpi-desync-repeats=8 --dpi-desync-split-pos=1,midsld --dpi-desync-split-seqovl=5 --dpi-desync-split-seqovl-pattern="%BIN%tls.bin" --dpi-desync-fake-tls="%BIN%tls.bin" --new ^
--filter-tcp=%GameFilterTCP% --ipset="%LISTS%ipset-all.txt" --dpi-desync=multisplit --dpi-desync-any-protocol=1 --dpi-desync-cutoff=n4 --dpi-desync-split-pos=2
'''


class ConverterTest(unittest.TestCase):
    def make_source(self, root: Path) -> Path:
        source = root / "flowseal"
        (source / "bin").mkdir(parents=True)
        (source / "lists").mkdir()
        (source / "general.bat").write_text(PROFILE, encoding="utf-8")
        (source / "bin" / "quic.bin").write_bytes(b"quic")
        (source / "bin" / "tls.bin").write_bytes(b"tls")
        (source / "lists" / "list-general.txt").write_text("youtube.com\n", encoding="utf-8")
        (source / "lists" / "ipset-all.txt").write_text("203.0.113.113/32\n", encoding="utf-8")
        (source / "lists" / "ipset-all.txt.backup").write_text("1.1.1.1/32\n", encoding="utf-8")
        return source

    def test_parser_splits_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = self.make_source(Path(temp))
            global_options, profiles = parse_batch(source / "general.bat")
            self.assertEqual([item.name for item in global_options], ["wf-tcp", "wf-udp"])
            self.assertEqual(len(profiles), 3)

    def test_gui_discovers_profiles_and_suggests_unique_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            (source / "helper.bat").write_text("@echo off\necho service helper\n", encoding="utf-8")
            (source / "service.bat").write_text(
                '@echo off\ntasklist | find "winws.exe"\ncurl --silent --output version.txt https://example.org\n',
                encoding="utf-8",
            )
            self.assertEqual(discover_profiles(source), ["general.bat"])

            moment = datetime(2026, 8, 13, 12, 30, 45)
            first = suggest_output(source, "general.bat", "keenetic", moment)
            self.assertEqual(first.name, "general-keenetic-20260813-123045")
            first.mkdir(parents=True)
            second = suggest_output(source, "general.bat", "keenetic", moment)
            self.assertEqual(second.name, "general-keenetic-20260813-123045-2")

    def test_conversion_creates_native_nfqws2_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            output = root / "result"
            result = convert(
                ConverterSettings(
                    source=source,
                    profile="general.bat",
                    output=output,
                    interface="ppp0",
                    game_filter="disabled",
                )
            )
            config = result.config.read_text(encoding="utf-8")
            self.assertEqual(result.profiles_read, 3)
            self.assertEqual(result.profiles_written, 2)
            self.assertIn("--lua-desync=fake:blob=quic", config)
            self.assertIn("--lua-desync=multisplit:pos=1,midsld:seqovl=5", config)
            self.assertIn("tcp_ts=-600000", config)
            self.assertNotIn("--dpi-desync", config)
            self.assertNotIn("TCP_PORTS=12", config)
            self.assertIn("ISP_INTERFACE='ppp0'", config)
            self.assertTrue((output / "blobs" / "quic.bin").is_file())
            self.assertTrue((output / "lists" / "list-general.txt").is_file())

            web_config_path = output / "web-import" / "nfqws2.conf"
            web_config = web_config_path.read_text(encoding="utf-8")
            self.assertIn("--blob=quic:0x71756963", web_config)
            self.assertIn("--blob=tls:0x746c73", web_config)
            self.assertNotIn("/blobs/", web_config)
            self.assertIn("/lists/list-general.list", web_config)
            self.assertNotIn("/lists/list-general.txt", web_config)
            self.assertIn("/lists/list-general-user.list", web_config)
            self.assertEqual(
                (output / "web-import" / "lists" / "list-general.list").read_text(encoding="utf-8"),
                "youtube.com\n",
            )
            self.assertEqual(
                (output / "web-import" / "lists" / "list-general-user.list").read_text(encoding="utf-8"),
                "",
            )
            self.assertTrue((output / "web-import" / "README.md").is_file())

    def test_game_and_ipset_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            output = root / "result"
            result = convert(
                ConverterSettings(
                    source=source,
                    profile="general.bat",
                    output=output,
                    game_filter="all",
                )
            )
            self.assertEqual(result.profiles_written, 3)
            self.assertIn("1024-65535", result.tcp_ports)
            self.assertEqual((output / "lists" / "ipset-all.txt").read_text().strip(), "1.1.1.1/32")
            self.assertEqual(
                (output / "web-import" / "lists" / "ipset-all.list").read_text().strip(),
                "1.1.1.1/32",
            )

    def test_current_ipset_mode_preserves_disabled_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            output = root / "result"
            convert(
                ConverterSettings(
                    source=source,
                    profile="general.bat",
                    output=output,
                    game_filter="all",
                    ipset_mode="current",
                )
            )
            self.assertEqual(
                (output / "lists" / "ipset-all.txt").read_text().strip(),
                "203.0.113.113/32",
            )

    def test_archive_keeps_dotted_output_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            output = root / "general-1.10.1-keenetic"
            result = convert(
                ConverterSettings(source=source, profile="general.bat", output=output, archive=True)
            )
            self.assertEqual(result.archive.name, "general-1.10.1-keenetic.zip")
            self.assertTrue(result.archive.is_file())

    def test_hybrid_keeps_discord_and_stock_adaptive_profiles(self) -> None:
        stock = r'''NFQWS_BASE_ARGS="--lua-init=@/opt/etc/nfqws2/lua/zapret-lib.lua\n                 --blob=quic_initial:@/opt/etc/nfqws2/blobs/quic_initial.bin"
NFQWS_ARGS="--filter-tcp=443\n                 --lua-desync=circular"
NFQWS_ARGS_QUIC="--filter-udp=443"
NFQWS_ARGS_UDP="--filter-udp=3478-3481"
NFQWS_EXTRA_ARGS="\$MODE_AUTO"
NFQWS_ARGS_IPSET="--ipset=/opt/etc/nfqws2/lists/ipset.list\n                 --ipset-exclude=/opt/etc/nfqws2/lists/ipset_exclude.list"
NFQWS_ARGS_CUSTOM=""
'''
        converted = '''NFQWS_BASE_ARGS="--lua-init=@/opt/etc/nfqws2/lua/zapret-lib.lua\n                 --blob=discord:0xc500"
NFQWS_ARGS="--filter-tcp=443\n                 --ipset=/opt/etc/nfqws2/lists/ipset-all.list"
NFQWS_ARGS_CUSTOM="--filter-udp=443\n                 --hostlist=/opt/etc/nfqws2/lists/list-general.list\n                 --new\n                 --filter-tcp=443\n                 --hostlist=/opt/etc/nfqws2/lists/list-google.list\n                 --new\n                 --filter-l7=discord,stun"
'''
        hybrid = build_hybrid_keenetic_config(stock, converted)
        self.assertIn("--blob=discord:0xc500", hybrid)
        self.assertIn("--hostlist=/opt/etc/nfqws2/lists/list-general.list", hybrid)
        self.assertIn("--filter-l7=discord,stun", hybrid)
        self.assertNotIn("list-google.list", hybrid)
        self.assertIn("--lua-desync=circular", hybrid)
        self.assertIn("--ipset=/opt/etc/nfqws2/lists/ipset-all.list", hybrid)

    def test_syndata_and_relative_dp0_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            profile = source / "syndata.bat"
            profile.write_text(
                r'''start "zapret" "%~dp0bin\winws.exe" --wf-tcp=443 ^
--filter-tcp=443 --hostlist="%~dp0lists\list-general.txt" --dpi-desync=syndata,multidisorder''',
                encoding="utf-8",
            )
            result = convert(
                ConverterSettings(source=source, profile=profile.name, output=root / "result")
            )
            config = result.config.read_text(encoding="utf-8")
            self.assertIn("--payload=empty", config)
            self.assertIn("--lua-desync=syndata", config)
            self.assertIn("--lua-desync=multidisorder", config)
            self.assertEqual(result.warning_count, 0)

    def test_rejects_invalid_nfqueue_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.make_source(root)
            with self.assertRaisesRegex(ConversionError, "queue_num"):
                convert(
                    ConverterSettings(
                        source=source,
                        profile="general.bat",
                        output=root / "result",
                        queue_num=65536,
                    )
                )


if __name__ == "__main__":
    unittest.main()
