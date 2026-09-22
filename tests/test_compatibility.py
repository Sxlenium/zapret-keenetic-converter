from __future__ import annotations

import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path

from lupa import LuaRuntime

from zapret_keenetic.converter import ConversionError, ConverterSettings, convert
from zapret_keenetic.hybrid import _assignment, build_hybrid_keenetic_config


class CompatibilityTest(unittest.TestCase):
    def convert_options(self, options: str, *, strict: bool = True, **settings):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "source"
        source.mkdir()
        (source / "test.bat").write_text('winws.exe --filter-tcp=80,443 ' + options, encoding="utf-8")
        result = convert(ConverterSettings(source, "test.bat", root / "out", strict=strict, **settings))
        return result, result.config.read_text(encoding="utf-8")

    def alt13(self):
        return self.convert_options(
            "--dpi-desync=fake,hostfakesplit --dpi-desync-fooling=ts "
            "--dpi-desync-hostfakesplit-mod=host=mail.ru,altorder=1 "
            "--dpi-desync-repeats=5 --dpi-desync-fake-tls=0x160301 "
            "--dpi-desync-fake-tls=0x0000 --dpi-desync-fake-http=0x160301"
        )

    def test_alt13_keeps_altorder_without_warning(self):
        result, config = self.alt13()
        self.assertEqual(result.warning_count, 0)
        self.assertIn("--lua-desync=zk_hostfakesplit_alt1:host=mail.ru", config)
        self.assertEqual(config.count("--lua-desync=fake:"), 3)
        web = (result.output / "web-import/nfqws2.conf").read_text(encoding="utf-8")
        self.assertEqual(_assignment(config, "NFQWS_BASE_ARGS").value,
                         _assignment(web, "NFQWS_BASE_ARGS").value)

    def test_real_split_segments_do_not_receive_fake_fooling(self):
        for mode in ("multisplit", "multidisorder"):
            with self.subTest(mode=mode):
                _, config = self.convert_options(
                    f"--dpi-desync=fake,{mode} --dpi-desync-fooling=badseq,ts,md5sig,badsum "
                    "--dpi-desync-repeats=7 --dpi-desync-split-pos=1,midsld "
                    "--dpi-desync-split-seqovl=10 --ip-id=zero"
                )
                real = next(line for line in config.splitlines() if f"--lua-desync={mode}" in line)
                for forbidden in ("tcp_seq=", "tcp_ack=", "tcp_ts=", "tcp_md5", "badsum", "repeats="):
                    self.assertNotIn(forbidden, real)
                self.assertIn("ip_id=zero", real)
                self.assertIn("tcp_seq=-10000", config)

    def test_multidisorder_uses_v1_segment_order(self):
        _, config = self.convert_options("--dpi-desync=multidisorder --dpi-desync-split-pos=1,midsld")
        self.assertIn("--lua-desync=multidisorder_legacy:pos=1,midsld", config)

    def test_unsupported_host_modifiers_are_not_silently_lost(self):
        for mod in ("altorder=2", "unknown=1"):
            with self.subTest(mod=mod), self.assertRaises(ConversionError):
                self.convert_options(f"--dpi-desync=hostfakesplit --dpi-desync-hostfakesplit-mod={mod}")

    def test_none_host_modifier_uses_stock_function(self):
        _, config = self.convert_options("--dpi-desync=hostfakesplit --dpi-desync-hostfakesplit-mod=none")
        self.assertIn("--lua-desync=hostfakesplit", config)
        self.assertNotIn("zk_hostfakesplit", config)
        _, config = self.convert_options(
            "--dpi-desync=hostfakesplit --dpi-desync-hostfakesplit-mod=none,host=mail.ru,altorder=1"
        )
        self.assertIn("--lua-desync=zk_hostfakesplit_alt1:host=mail.ru", config)

    def test_initializer_survives_shell_config_and_argv_expansion(self):
        shell = shutil.which("sh")
        if not shell and shutil.which("git"):
            candidate = Path(shutil.which("git")).resolve().parents[1] / "usr/bin/sh.exe"
            if candidate.is_file():
                shell = str(candidate)
        if not shell:
            self.skipTest("POSIX shell needed for the Keenetic argv smoke test")
        result, config = self.alt13()
        script = result.output / "argv-check.sh"
        script.write_text('. "$1"\nargs=$(echo "$NFQWS_BASE_ARGS")\nprintf "%s\\0" $args\n', encoding="utf-8")
        argv = subprocess.run([shell, script.as_posix(), result.config.as_posix()],
                              capture_output=True, check=True).stdout.decode("utf-8").split("\0")
        initializers = [arg for arg in argv if arg.startswith("--lua-init=") and not arg.startswith("--lua-init=@")]
        self.assertEqual(len(initializers), 1)
        lua = LuaRuntime()
        lua.execute(initializers[0][len("--lua-init="):])
        self.assertEqual(lua.eval("type(zk_hostfakesplit_alt1)"), "function")

    def test_hybrid_keeps_compatibility_initializer(self):
        _, config = self.alt13()
        config = config.replace("--filter-tcp=80,443", "--filter-tcp=443\n--hostlist-domains=discord.media")
        stock = ('NFQWS_BASE_ARGS="--lua-init=@/opt/etc/nfqws2/lua/zapret-lib.lua\n'
                 '--lua-init=@/opt/etc/nfqws2/lua/zapret-antidpi.lua"\n'
                 'NFQWS_ARGS="--lua-desync=fake"\nNFQWS_ARGS_CUSTOM=""\nNFQWS_ARGS_IPSET=""\n')
        merged = build_hybrid_keenetic_config(stock, config)
        initializers = [line.strip() for line in _assignment(config, "NFQWS_BASE_ARGS").value.splitlines()
                        if line.strip().startswith("--lua-init=") and not line.strip().startswith("--lua-init=@")]
        self.assertEqual(len(initializers), 1)
        self.assertIn(initializers[0], _assignment(merged, "NFQWS_BASE_ARGS").value)

    def lua_runtime(self):
        _, config = self.alt13()
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
            VERDICT_PASS=0; VERDICT_DROP=1; sent={}; first=true; dropped=false
            function direction_cutoff_opposite() end
            function instance_cutoff_shim() end
            function direction_check() return true end
            function payload_check() return true end
            function replay_first() return first end
            function replay_drop_set() dropped=true end
            function replay_drop() return dropped end
            function resolve_range(data)
                local a,b=string.find(data,"example.org",1,true)
                if a then return {a,b} end
            end
            function resolve_pos() return midpos end
            function genhost(n) return string.rep("F",n) end
            function rawsend_opts_base() return {} end
            function rawsend_opts(d) return {repeats=tonumber(d.arg.repeats)} end
            function reconstruct_opts() return {} end
            function rawsend_payload_segmented(d,data,offset,opts)
                table.insert(sent,{data=data,offset=offset,ts=opts.fooling.tcp_ts,
                                  repeats=opts.rawsend.repeats})
                return #sent~=fail_at
            end
            d={dis={tcp={},payload="HEADexample.orgTAIL"},arg={host="mail.ru",tcp_ts=-600000,repeats="5"},
               l7payload="http_req"}
        ''')
        init = [line.strip()[len("--lua-init="):] for line in _assignment(config, "NFQWS_BASE_ARGS").value.splitlines()
                if line.strip().startswith("--lua-init=") and not line.strip().startswith("--lua-init=@")]
        self.assertEqual(len(init), 1)
        self.assertFalse(any(c.isspace() for c in init[0]), "init must survive the package's shell word splitting")
        lua.execute(init[0])
        return lua

    def test_altorder_packet_sequence_and_fooling(self):
        lua = self.lua_runtime()
        self.assertEqual(lua.eval("zk_hostfakesplit_alt1({},d)"), 1)
        sent = list(lua.globals().sent.values())
        self.assertEqual([(p.data, p.offset) for p in sent],
                         [("HEAD", 0), ("FFFFFFFFFFF", 4), ("TAIL", 15), ("example.org", 4)])
        self.assertEqual([(p.ts, p.repeats) for p in sent],
                         [(None, None), (-600000, 5), (None, None), (None, None)])
        lua.execute("first=false")
        self.assertEqual(lua.eval("zk_hostfakesplit_alt1({},d)"), 1)
        self.assertEqual(len(lua.globals().sent), 4, "replayed fragments must not resend the request")

    def test_altorder_midhost_and_failure_do_not_drop_unsent_data(self):
        lua = self.lua_runtime()
        lua.execute('d.arg.midhost="midsld"; midpos=8')
        self.assertEqual(lua.eval("zk_hostfakesplit_alt1({},d)"), 1)
        self.assertEqual([p.data for p in lua.globals().sent.values()],
                         ["HEAD", "FFFFFFFFFFF", "TAIL", "exa", "mple.org"])
        for fail_at in (1, 2, 3, 4, 5):
            lua.execute(f"sent={{}}; dropped=false; fail_at={fail_at}")
            self.assertEqual(lua.eval("zk_hostfakesplit_alt1({},d)"), 0)
            self.assertFalse(lua.globals().dropped)

    def test_altorder_passes_missing_host_and_non_tcp(self):
        lua = self.lua_runtime()
        lua.execute('d.dis.payload="no host here"')
        lua.eval("zk_hostfakesplit_alt1({},d)")
        self.assertEqual(len(lua.globals().sent), 0)
        lua.execute('d.dis.tcp=nil')
        lua.eval("zk_hostfakesplit_alt1({},d)")
        self.assertEqual(len(lua.globals().sent), 0)

    def test_clone_mode_generates_one_live_tls_fake_without_source_tls_blob(self):
        result, config = self.convert_options(
            "--dpi-desync=fake,multisplit --dpi-desync-fooling=ts --dpi-desync-repeats=11 "
            "--dpi-desync-fake-tls=missing1.bin --dpi-desync-fake-tls=missing2.bin "
            "--dpi-desync-fake-http=0x1234 --dpi-desync-split-pos=1",
            tls_fake_mode="clone", fake_repeats_limit=3,
        )
        self.assertIn("--lua-desync=tls_client_hello_clone:blob=zk_live_tls", config)
        self.assertIn("--lua-desync=fake:blob=zk_live_tls:tcp_ts=-600000:repeats=3:optional:tls_mod=rnd,rndsni,dupsid", config)
        self.assertNotIn("missing", config)
        self.assertNotIn("repeats=11", config)
        self.assertEqual(config.count("--lua-desync=tls_client_hello_clone"), 1)
        self.assertIn("--lua-desync=fake:blob=0x1234", config)
        self.assertEqual(result.warning_count, 0)
        self.assertIn("experimental-tls-clone", [d.code for d in result.diagnostics])

    def test_invalid_experimental_settings_are_rejected(self):
        for settings in ({"tls_fake_mode": "invalid"}, {"fake_repeats_limit": 0}, {"fake_repeats_limit": -1}):
            with self.subTest(settings=settings), self.assertRaises(ConversionError):
                self.convert_options("--dpi-desync=fake", **settings)

    def test_exact_install_is_default_for_strategy_comparison(self):
        from zapret_keenetic.cli import build_parser
        from zapret_keenetic.gui import INSTALL_MODE_LABELS
        args = build_parser().parse_args(["source", "general.bat", "-o", "output"])
        self.assertEqual(args.install_mode, "exact")
        self.assertEqual(next(iter(INSTALL_MODE_LABELS.values())), "exact")
