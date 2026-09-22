from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .compat import HOSTFAKESPLIT_INIT


class ConversionError(RuntimeError):
    """The source profile cannot be converted safely."""


@dataclass(frozen=True)
class Option:
    name: str
    value: str | None


@dataclass
class Diagnostic:
    level: str
    code: str
    message: str
    profile: int | None = None
    option: str | None = None


@dataclass
class ConvertedProfile:
    source_number: int
    arguments: list[str]


@dataclass
class ConverterSettings:
    source: Path
    profile: str
    output: Path
    target: str = "keenetic"
    interface: str = "eth3"
    game_filter: str = "disabled"
    ipset_mode: str = "loaded"
    ipv6: bool = True
    policy_name: str = "nfqws"
    policy_exclude: bool = False
    queue_num: int = 300
    strict: bool = False
    archive: bool = False
    tls_fake_mode: str = "source"
    fake_repeats_limit: int | None = None


@dataclass
class ConversionResult:
    output: Path
    config: Path
    report: Path
    archive: Path | None
    profiles_read: int
    profiles_written: int
    tcp_ports: list[str]
    udp_ports: list[str]
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def warning_count(self) -> int:
        return sum(d.level == "warning" for d in self.diagnostics)


OPTION_RE = re.compile(
    r"--(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)(?:=(?P<value>\"[^\"]*\"|[^\s]+))?"
)
WINWS_RE = re.compile(r"winws(?:\.exe)?\"?", re.IGNORECASE)
VAR_RE = re.compile(r"%([^%]+)%", re.IGNORECASE)

# Flowseal ships ipset-all.txt in a deliberately disabled state and keeps the
# populated list beside it as ipset-all.txt.backup. TEST-NET-3 is a sentinel,
# not a useful public network range.
IPSET_DISABLED_SENTINELS = {"203.0.113.113/32"}

PASS_OPTIONS = {
    "filter-l3",
    "filter-l7",
    "filter-tcp",
    "filter-udp",
    "hostlist",
    "hostlist-domains",
    "hostlist-exclude",
    "hostlist-exclude-domains",
    "ipset",
    "ipset-exclude",
}
FILE_OPTIONS = {"hostlist", "hostlist-exclude", "ipset", "ipset-exclude"}
CONSUMED_OPTIONS = {
    "dpi-desync",
    "dpi-desync-any-protocol",
    "dpi-desync-badseq-increment",
    "dpi-desync-badack-increment",
    "dpi-desync-cutoff",
    "dpi-desync-fake-discord",
    "dpi-desync-fake-http",
    "dpi-desync-fake-quic",
    "dpi-desync-fake-stun",
    "dpi-desync-fake-tls",
    "dpi-desync-fake-tls-mod",
    "dpi-desync-fake-unknown",
    "dpi-desync-fake-unknown-udp",
    "dpi-desync-fakedsplit-pattern",
    "dpi-desync-fooling",
    "dpi-desync-hostfakesplit-midhost",
    "dpi-desync-hostfakesplit-mod",
    "dpi-desync-repeats",
    "dpi-desync-split-pos",
    "dpi-desync-split-seqovl",
    "dpi-desync-split-seqovl-pattern",
    "dpi-desync-ts-increment",
    "ip-id",
}
FAKE_PAYLOADS = {
    "dpi-desync-fake-http": "http_req",
    "dpi-desync-fake-tls": "tls_client_hello",
    "dpi-desync-fake-quic": "quic_initial",
    "dpi-desync-fake-discord": "discord_ip_discovery",
    "dpi-desync-fake-stun": "stun",
    "dpi-desync-fake-unknown": "unknown",
    "dpi-desync-fake-unknown-udp": "unknown",
}
BUILTIN_BLOBS = {
    "http_req": "fake_default_http",
    "tls_client_hello": "fake_default_tls",
    "quic_initial": "fake_default_quic",
    "discord_ip_discovery": "0x00000000000000000000000000000000",
    "stun": "0x00000000000000000000000000000000",
    "unknown": "0x00000000000000000000000000000000",
}
L7_PAYLOADS = {
    "http": ["http_req"],
    "tls": ["tls_client_hello"],
    "quic": ["quic_initial"],
    "discord": ["discord_ip_discovery"],
    "stun": ["stun"],
    "wireguard": ["wireguard_initiation", "wireguard_response", "wireguard_cookie"],
    "mtproto": ["mtproto_initial"],
    "unknown": ["unknown"],
}


def _read_batch(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ConversionError(f"Не удалось определить кодировку файла: {path}")


def parse_batch(path: Path) -> tuple[list[Option], list[list[Option]]]:
    text = _read_batch(path).replace("\r\n", "\n")
    text = re.sub(r"\^\s*\n", " ", text)
    match = WINWS_RE.search(text)
    if not match:
        raise ConversionError(f"В {path.name} не найден запуск winws.exe")
    command = text[match.end() :]
    options: list[Option] = []
    for item in OPTION_RE.finditer(command):
        value = item.group("value")
        if value is not None:
            value = value.strip('"')
            if value.startswith("^"):
                value = value[1:]
            value = value.rstrip("^")
        options.append(Option(item.group("name").lower(), value))
    if not options:
        raise ConversionError(f"В команде winws файла {path.name} не найдены параметры")

    global_options: list[Option] = []
    profiles: list[list[Option]] = [[]]
    seen_profile = False
    for option in options:
        if option.name == "new":
            seen_profile = True
            if profiles[-1]:
                profiles.append([])
            continue
        if option.name.startswith("wf-") and not seen_profile:
            global_options.append(option)
        else:
            seen_profile = True
            profiles[-1].append(option)
    profiles = [profile for profile in profiles if profile]
    return global_options, profiles


def _values(options: Sequence[Option], name: str) -> list[str]:
    return [item.value or "" for item in options if item.name == name]


def _last(options: Sequence[Option], name: str, default: str | None = None) -> str | None:
    values = _values(options, name)
    return values[-1] if values else default


def _replace_variables(value: str, settings: ConverterSettings) -> str:
    game_enabled = {
        "disabled": {"gamefiltertcp": "12", "gamefilterudp": "12"},
        "all": {"gamefiltertcp": "1024-65535", "gamefilterudp": "1024-65535"},
        "tcp": {"gamefiltertcp": "1024-65535", "gamefilterudp": "12"},
        "udp": {"gamefiltertcp": "12", "gamefilterudp": "1024-65535"},
    }[settings.game_filter]
    replacements = {
        "bin": str(settings.source / "bin") + "\\",
        "lists": str(settings.source / "lists") + "\\",
        **game_enabled,
    }

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        return replacements.get(key, match.group(0))

    source_prefix = str(settings.source) + "\\"
    value = re.sub(re.escape("%~dp0"), lambda _: source_prefix, value, flags=re.IGNORECASE)
    return VAR_RE.sub(replace, value)


def _resolved_options(options: Sequence[Option], settings: ConverterSettings) -> list[Option]:
    return [
        Option(item.name, _replace_variables(item.value, settings) if item.value is not None else None)
        for item in options
    ]


def _profile_is_disabled_game(options: Sequence[Option]) -> bool:
    filters = _values(options, "filter-tcp") + _values(options, "filter-udp")
    return bool(filters) and all(value == "12" for value in filters)


def _port_sort_key(value: str) -> tuple[int, int, str]:
    first = re.split(r"[-:]", value, maxsplit=1)[0]
    try:
        return (int(first), 0 if "-" not in value and ":" not in value else 1, value)
    except ValueError:
        return (65536, 2, value)


def _collect_ports(profiles: Sequence[Sequence[Option]], transport: str) -> list[str]:
    result: set[str] = set()
    for profile in profiles:
        for value in _values(profile, f"filter-{transport}"):
            for port in value.split(","):
                port = port.strip()
                if port and port != "12" and "%" not in port:
                    result.add(port)
    return sorted(result, key=_port_sort_key)


class _Bundle:
    def __init__(self, settings: ConverterSettings, diagnostics: list[Diagnostic]):
        self.settings = settings
        self.diagnostics = diagnostics
        self.router_root = "/opt/etc/nfqws2" if settings.target == "keenetic" else "/etc/nfqws2"
        self.blobs: dict[Path, tuple[str, str]] = {}
        self.copied: dict[Path, Path] = {}
        self.missing_reported: set[tuple[str, Path]] = set()

    def _source_path(self, raw: str) -> tuple[str, Path] | None:
        value = raw.strip('"')
        offset = ""
        if value.startswith("+") and "@" in value:
            offset, value = value.split("@", 1)
            offset += "@"
        elif value.startswith("@"):
            value = value[1:]
        if value.startswith("0x") or value == "!":
            return None
        path = Path(value.replace("\\", "/"))
        return offset, path

    def _choose_ipset(self, source: Path) -> Path:
        if self.settings.ipset_mode != "loaded" or source.name.lower() != "ipset-all.txt":
            return source
        backup = source.with_name(source.name + ".backup")
        current_entries = _substantive_lines(source)
        current_is_disabled = not current_entries or set(current_entries) <= IPSET_DISABLED_SENTINELS
        if current_is_disabled and backup.exists() and _substantive_line_count(backup) > 0:
            self.diagnostics.append(
                Diagnostic("info", "ipset-backup", f"Пустой {source.name} заменён наполненным {backup.name}")
            )
            return backup
        return source

    def copy_list(self, raw: str, profile_no: int, option: str) -> str:
        parsed = self._source_path(raw)
        if parsed is None:
            return raw
        _, source = parsed
        if not source.is_absolute():
            source = self.settings.source / source
        source = self._choose_ipset(source)
        destination_name = "ipset-all.txt" if source.name.endswith(".backup") else source.name
        destination = self.settings.output / "lists" / destination_name
        if source.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination not in self.copied.values():
                shutil.copy2(source, destination)
                self.copied[source] = destination
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.touch(exist_ok=True)
            self.copied.setdefault(source, destination)
            marker = ("list", source)
            if marker not in self.missing_reported:
                self.missing_reported.add(marker)
                is_user_list = source.stem.lower().endswith("-user")
                self.diagnostics.append(
                    Diagnostic(
                        "info" if is_user_list else "warning",
                        "empty-user-list" if is_user_list else "missing-list",
                        (
                            f"Необязательный {source.name} отсутствует; создан пустой файл."
                            if is_user_list
                            else f"Файл {source.name} отсутствует; создан пустой файл. Заполните его перед установкой."
                        ),
                        profile_no,
                        option,
                    )
                )
        return f"{self.router_root}/lists/{destination_name}"

    def blob(self, raw: str, profile_no: int, option: str) -> str:
        raw = raw.strip('"')
        if raw == "!":
            return "fake_default_tls"
        if raw.startswith("0x") or raw in set(BUILTIN_BLOBS.values()):
            return raw
        parsed = self._source_path(raw)
        if parsed is None:
            return raw
        offset, source = parsed
        if not source.is_absolute():
            source = self.settings.source / source
        if not source.exists():
            marker = ("blob", source)
            if marker not in self.missing_reported:
                self.missing_reported.add(marker)
                self.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "missing-blob",
                        f"Не найден бинарный шаблон {source}",
                        profile_no,
                        option,
                    )
                )
            return "0x00"
        if source not in self.blobs:
            stem = re.sub(r"[^a-zA-Z0-9_]", "_", source.stem).strip("_").lower() or "blob"
            name = stem
            used = {item[0] for item in self.blobs.values()}
            if name in used:
                suffix = hashlib.sha1(str(source).encode()).hexdigest()[:7]
                name = f"{name}_{suffix}"
            destination_name = source.name
            used_destinations = {item[1] for item in self.blobs.values()}
            if destination_name in used_destinations:
                suffix = hashlib.sha1(str(source).encode()).hexdigest()[:7]
                destination_name = f"{source.stem}_{suffix}{source.suffix}"
            self.blobs[source] = (name, destination_name)
            destination = self.settings.output / "blobs" / destination_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination not in self.copied.values():
                shutil.copy2(source, destination)
                self.copied[source] = destination
        return self.blobs[source][0]

    def blob_declarations(self) -> list[str]:
        result = []
        for _, (name, destination_name) in sorted(self.blobs.items(), key=lambda item: item[1][0]):
            result.append(f"--blob={name}:@{self.router_root}/blobs/{destination_name}")
        return result


def _substantive_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", ";"))
    ]


def _substantive_line_count(path: Path) -> int:
    return len(_substantive_lines(path))


def _append_arg(parts: list[str], key: str, value: str | None = None) -> None:
    parts.append(f"--{key}" if value is None else f"--{key}={value}")


def _fooling_args(options: Sequence[Option]) -> list[str]:
    result: list[str] = []
    modes = [mode.strip() for mode in (_last(options, "dpi-desync-fooling", "") or "").split(",") if mode.strip()]
    for mode in modes:
        if mode == "ts":
            result.append(f"tcp_ts={_last(options, 'dpi-desync-ts-increment', '-600000')}")
        elif mode == "badseq":
            seq = _last(options, "dpi-desync-badseq-increment", "-10000")
            ack = _last(options, "dpi-desync-badack-increment", "-66000")
            if seq != "0":
                result.append(f"tcp_seq={seq}")
            result.extend((f"tcp_ack={ack}", "tcp_ts_up"))
        elif mode == "md5sig":
            result.append("tcp_md5")
        elif mode == "badsum":
            result.append("badsum")
    return result


def _common_lua_args(options: Sequence[Option], include_repeats: bool = False) -> list[str]:
    result = _fooling_args(options)
    ip_id = _last(options, "ip-id")
    if ip_id:
        result.append(f"ip_id={ip_id}")
    if include_repeats:
        repeats = _last(options, "dpi-desync-repeats")
        if repeats:
            result.append(f"repeats={repeats}")
    return result


def _lua(function: str, arguments: Iterable[str]) -> str:
    args = [arg for arg in arguments if arg]
    return function if not args else function + ":" + ":".join(args)


def _fake_specs(options: Sequence[Option]) -> list[tuple[str, str, str | None, str]]:
    """Return (source option, payload, tls mod, blob value), preserving source order."""
    specs: list[list[str | None]] = []
    current_tls_mod: str | None = None
    last_tls_index: int | None = None
    for item in options:
        if item.name == "dpi-desync-fake-tls-mod":
            current_tls_mod = item.value
            if last_tls_index is not None:
                specs[last_tls_index][2] = current_tls_mod
        elif item.name in FAKE_PAYLOADS and item.value is not None:
            tls_mod = current_tls_mod if item.name == "dpi-desync-fake-tls" else None
            specs.append([item.name, FAKE_PAYLOADS[item.name], tls_mod, item.value])
            if item.name == "dpi-desync-fake-tls":
                last_tls_index = len(specs) - 1
    return [(str(a), str(b), c, str(d)) for a, b, c, d in specs]


def _inferred_payloads(options: Sequence[Option], any_protocol: bool) -> list[str]:
    if any_protocol:
        return ["all"]
    payloads: list[str] = []
    l7 = _last(options, "filter-l7")
    if l7:
        for name in l7.split(","):
            payloads.extend(L7_PAYLOADS.get(name.strip(), []))
    if not payloads:
        tcp = ",".join(_values(options, "filter-tcp"))
        udp = ",".join(_values(options, "filter-udp"))
        if tcp:
            if "443" in tcp:
                payloads.append("tls_client_hello")
            if "80" in tcp.split(",") or tcp.startswith("80,"):
                payloads.append("http_req")
            if not payloads:
                payloads.append("tls_client_hello")
        elif udp:
            payloads.extend(spec[1] for spec in _fake_specs(options))
    return list(dict.fromkeys(payloads or ["known"]))


def _translate_profile(
    options: Sequence[Option], profile_no: int, bundle: _Bundle, diagnostics: list[Diagnostic]
) -> ConvertedProfile | None:
    if _profile_is_disabled_game(options):
        diagnostics.append(Diagnostic("info", "game-profile-skipped", "Игровой профиль отключён", profile_no))
        return None

    result: list[str] = []
    for item in options:
        if item.name in PASS_OPTIONS:
            if item.value is None:
                diagnostics.append(Diagnostic("warning", "missing-value", f"У --{item.name} нет значения", profile_no, item.name))
                continue
            value = bundle.copy_list(item.value, profile_no, item.name) if item.name in FILE_OPTIONS else item.value
            _append_arg(result, item.name, value)

    any_protocol = (_last(options, "dpi-desync-any-protocol", "0") or "0") not in {"", "0"}
    cutoff = _last(options, "dpi-desync-cutoff")
    if cutoff:
        _append_arg(result, "out-range", f"-{cutoff}")

    modes = [mode.strip() for mode in (_last(options, "dpi-desync", "") or "").split(",") if mode.strip()]
    if not modes:
        diagnostics.append(Diagnostic("warning", "no-strategy", "В профиле отсутствует --dpi-desync", profile_no))
        return ConvertedProfile(profile_no, result)

    fake_specs = _fake_specs(options)
    inferred_payloads = _inferred_payloads(options, any_protocol)
    tls_mod_default = _last(options, "dpi-desync-fake-tls-mod")

    for mode in modes:
        if mode == "fake":
            specs = list(fake_specs)
            if not specs:
                specs = [
                    ("builtin", payload, tls_mod_default if payload == "tls_client_hello" else None, BUILTIN_BLOBS.get(payload, "0x00"))
                    for payload in inferred_payloads
                    if payload not in {"all", "known"}
                ]
            if not specs:
                specs = [("builtin", "known", None, "0x00")]
            cloned_tls = False
            for source_option, payload, tls_mod, raw_blob in specs:
                clone = payload == "tls_client_hello" and bundle.settings.tls_fake_mode == "clone"
                if clone and cloned_tls:
                    continue
                _append_arg(result, "payload", payload)
                if clone:
                    cloned_tls = True
                    blob = "zk_live_tls"
                    _append_arg(result, "lua-desync", f"tls_client_hello_clone:blob={blob}")
                    diagnostics.append(Diagnostic(
                        "info", "experimental-tls-clone",
                        "Эксперимент: TLS fake-шаблоны заменены одним живым ClientHello с rnd,rndsni,dupsid; "
                        "это изменённая стратегия. HTTP/QUIC/seqovl-шаблоны сохранены.", profile_no,
                    ))
                else:
                    blob = bundle.blob(raw_blob, profile_no, source_option)
                args = [f"blob={blob}", *_common_lua_args(options, include_repeats=True)]
                if clone:
                    args.extend(("optional", "tls_mod=rnd,rndsni,dupsid"))
                elif payload == "tls_client_hello" and tls_mod and tls_mod != "none":
                    args.append(f"tls_mod={tls_mod}")
                _append_arg(result, "lua-desync", _lua("fake", args))
            continue

        if mode == "syndata":
            _append_arg(result, "payload", "empty")
            _append_arg(result, "lua-desync", "syndata")
            continue

        _append_arg(result, "payload", ",".join(inferred_payloads))
        common = _common_lua_args(options, include_repeats=mode in {"fakedsplit", "fakeddisorder", "hostfakesplit"})
        if mode in {"multisplit", "multidisorder"}:
            # nfqws1 applies fooling/repeats to fakes, not these real segments.
            common = [arg for arg in common if arg.startswith("ip_id=") or arg == "tcp_ts_up"]
        split_pos = _last(options, "dpi-desync-split-pos")
        seqovl = _last(options, "dpi-desync-split-seqovl")
        seqovl_pattern = _last(options, "dpi-desync-split-seqovl-pattern")

        if mode in {"multisplit", "multidisorder", "fakedsplit", "fakeddisorder"}:
            args: list[str] = []
            if split_pos:
                args.append(f"pos={split_pos}")
            if mode in {"multisplit", "multidisorder", "fakedsplit", "fakeddisorder"} and seqovl:
                args.append(f"seqovl={seqovl}")
            if seqovl_pattern:
                args.append(f"seqovl_pattern={bundle.blob(seqovl_pattern, profile_no, 'dpi-desync-split-seqovl-pattern')}")
            if mode in {"fakedsplit", "fakeddisorder"}:
                pattern = _last(options, "dpi-desync-fakedsplit-pattern")
                if pattern:
                    args.append(f"pattern={bundle.blob(pattern, profile_no, 'dpi-desync-fakedsplit-pattern')}")
            function = "multidisorder_legacy" if mode == "multidisorder" else mode
            _append_arg(result, "lua-desync", _lua(function, [*args, *common]))
        elif mode == "hostfakesplit":
            args = []
            mod = _last(options, "dpi-desync-hostfakesplit-mod", "") or ""
            altorder = False
            for component in mod.split(","):
                component = component.strip()
                if component.startswith("host="):
                    args.append(component)
                elif component == "altorder=1":
                    altorder = True
                elif component == "altorder=0":
                    altorder = False
                elif component and component != "none":
                    raise ConversionError(
                        f"Профиль {profile_no}: неподдерживаемый модификатор hostfakesplit {component}"
                    )
            midhost = _last(options, "dpi-desync-hostfakesplit-midhost")
            if midhost:
                args.append(f"midhost={midhost}")
            if altorder:
                diagnostics.append(
                    Diagnostic(
                        "info",
                        "hostfakesplit-altorder",
                        "altorder=1 сохранён встроенной Lua-функцией совместимости (zapret2 v1.0.5.2).",
                        profile_no,
                        "dpi-desync-hostfakesplit-mod",
                    )
                )
            function = "zk_hostfakesplit_alt1" if altorder else "hostfakesplit"
            _append_arg(result, "lua-desync", _lua(function, [*args, *common]))
        else:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "unsupported-mode",
                    f"Режим dpi-desync={mode} не поддержан и пропущен",
                    profile_no,
                    "dpi-desync",
                )
            )

    known = PASS_OPTIONS | CONSUMED_OPTIONS | {"wf-tcp", "wf-udp"}
    for item in options:
        if item.name not in known:
            diagnostics.append(
                Diagnostic("warning", "unsupported-option", f"Параметр --{item.name} пропущен", profile_no, item.name)
            )
    limit = bundle.settings.fake_repeats_limit
    if limit is not None:
        limited = False
        def cap_repeats(match: re.Match[str]) -> str:
            nonlocal limited
            count = int(match.group(1))
            limited = limited or count > limit
            return f":repeats={min(count, limit)}"
        result = [re.sub(r":repeats=(\d+)(?=:|$)", cap_repeats, arg) for arg in result]
        if limited:
            diagnostics.append(Diagnostic(
                "info", "experimental-repeat-limit",
                f"Эксперимент: число повторов fake-пакетов ограничено до {limit}; стратегия изменена.", profile_no,
            ))
    return ConvertedProfile(profile_no, result)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _config_value(lines: Sequence[str], indent: int = 17) -> str:
    if not lines:
        return '""'
    padding = " " * indent
    escaped = [line.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") for line in lines]
    return '"' + ("\n" + padding).join(escaped) + '"'


def _render_config(
    settings: ConverterSettings,
    bundle: _Bundle,
    profiles: Sequence[ConvertedProfile],
    tcp_ports: Sequence[str],
    udp_ports: Sequence[str],
) -> str:
    custom_lines: list[str] = []
    for index, profile in enumerate(profiles[:-1]):
        if index:
            custom_lines.append("--new")
        custom_lines.extend(profile.arguments)
    final_lines = profiles[-1].arguments
    base = [
        f"--lua-init=@{bundle.router_root}/lua/zapret-lib.lua",
        f"--lua-init=@{bundle.router_root}/lua/zapret-antidpi.lua",
        *bundle.blob_declarations(),
    ]
    if any(arg.startswith("--lua-desync=zk_hostfakesplit_alt1") for profile in profiles for arg in profile.arguments):
        base.append(HOSTFAKESPLIT_INIT)
    tcp = ",".join(port.replace("-", ":") for port in tcp_ports)
    udp = ",".join(port.replace("-", ":") for port in udp_ports)
    return f'''# Generated by zapret-keenetic-converter. Do not edit the generated file by hand.
# Source profile: {settings.profile}
# Target: {settings.target}

ISP_INTERFACE={_shell_quote(settings.interface)}

NFQWS_BASE_ARGS={_config_value(base)}

# Independent Flowseal profiles: all but the final one live in CUSTOM.
# The package init script adds --new before the final NFQWS_ARGS profile.
NFQWS_ARGS={_config_value(final_lines)}
NFQWS_ARGS_QUIC=""
NFQWS_ARGS_UDP=""
NFQWS_EXTRA_ARGS=""
NFQWS_ARGS_IPSET=""
NFQWS_ARGS_CUSTOM={_config_value(custom_lines)}

IPV6_ENABLED={1 if settings.ipv6 else 0}
TCP_PORTS={tcp}
UDP_PORTS={udp}

POLICY_NAME={_shell_quote(settings.policy_name)}
POLICY_EXCLUDE={1 if settings.policy_exclude else 0}

LOG_LEVEL=0
LOG_DEBUG_PATH="@{'/opt/var' if settings.target == 'keenetic' else '/var'}/log/nfqws2-debug.log"

NFQUEUE_NUM={settings.queue_num}
USER=nobody
CONFIG_VERSION=1
'''


def _web_list_filename(source: Path, destination: Path, used: set[str]) -> str:
    """Return a filename accepted by the web UI's list editor."""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", destination.stem).strip("-").lower() or "list"
    filename = f"{stem}.list"
    if filename in used:
        suffix = hashlib.sha1(str(source).encode()).hexdigest()[:7]
        filename = f"{stem}-{suffix}.list"
    used.add(filename)
    return filename


def _render_web_import(config_text: str, settings: ConverterSettings, bundle: _Bundle) -> Path | None:
    """Create a Keenetic web-UI friendly copy of the generated bundle.

    The web UI can create text lists only with a .list extension and has no
    binary blob uploader.  Inlining blobs as hexadecimal is native nfqws2
    syntax and keeps this variant importable without SCP.
    """
    if settings.target != "keenetic":
        return None

    web_root = settings.output / "web-import"
    web_lists = web_root / "lists"
    web_lists.mkdir(parents=True, exist_ok=True)
    web_config = config_text

    for source, (name, destination_name) in sorted(bundle.blobs.items(), key=lambda item: item[1][0]):
        file_declaration = f"--blob={name}:@{bundle.router_root}/blobs/{destination_name}"
        inline_declaration = f"--blob={name}:0x{source.read_bytes().hex()}"
        web_config = web_config.replace(file_declaration, inline_declaration)

    used_names: set[str] = set()
    list_files: list[str] = []
    output_lists = settings.output / "lists"
    for source, destination in sorted(bundle.copied.items(), key=lambda item: str(item[1])):
        if destination.parent != output_lists:
            continue
        web_name = _web_list_filename(source, destination, used_names)
        shutil.copy2(destination, web_lists / web_name)
        web_config = web_config.replace(
            f"{bundle.router_root}/lists/{destination.name}",
            f"{bundle.router_root}/lists/{web_name}",
        )
        list_files.append(web_name)

    config_path = web_root / "nfqws2.conf"
    config_path.write_text(web_config, encoding="utf-8", newline="\n")
    names = "\n".join(f"- `{name}`" for name in list_files) or "- Списки этому профилю не требуются."
    readme = f"""# Импорт через nfqws-keenetic-web

Этот каталог предназначен для вкладок веб-интерфейса `nfqws-keenetic-web`.
Бинарные шаблоны уже встроены в `nfqws2.conf` как hex, поэтому каталог `blobs/`
через веб-интерфейс загружать не нужно.

## Порядок действий

1. Прочитайте `../REPORT.md` и проверьте значение `ISP_INTERFACE`.
2. Сохраните резервную копию текущего конфига роутера.
3. Откройте **Списки** и для каждого имени ниже нажмите **Создать новый файл**.
   Введите имя **без `.list`**, создайте файл, вставьте содержимое одноимённого
   файла из папки `lists/` и нажмите **Сохранить**.
4. Откройте **Настройки → nfqws2.conf**. Выделите весь старый текст, замените
   содержимым этого `nfqws2.conf` и нажмите **Сохранить**.
5. Откройте **Логи**, убедитесь, что конфиг принят и служба запущена. Затем
   проверяйте сайты с устройства, на котором выключены локальные Zapret/VPN.

Создать в веб-интерфейсе нужно следующие списки:

{names}

Полная инструкция и откат: `../../docs/WEB_INTERFACE_RU.md` в репозитории
конвертера.
"""
    (web_root / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    return config_path


def _render_report(
    settings: ConverterSettings,
    profile_path: Path,
    profiles_read: int,
    profiles_written: int,
    tcp_ports: Sequence[str],
    udp_ports: Sequence[str],
    diagnostics: Sequence[Diagnostic],
) -> str:
    rows = []
    for item in diagnostics:
        where = f"профиль {item.profile}" if item.profile is not None else "общий"
        rows.append(f"- **{item.level.upper()} / {item.code}** ({where}): {item.message}")
    diagnostics_text = "\n".join(rows) if rows else "- Замечаний нет."
    root = "/opt/etc/nfqws2" if settings.target == "keenetic" else "/etc/nfqws2"
    service = "service nfqws2-keenetic restart"
    web_note = (
        "\nДля установки только через веб-интерфейс используйте `web-import/nfqws2.conf` "
        "и файлы из `web-import/lists/`. Не вставляйте весь конфиг в поле "
        "«Пользовательская стратегия».\n"
        if settings.target == "keenetic"
        else ""
    )
    return f"""# Отчёт конвертации

- Исходник: `{profile_path}`
- Цель: `{settings.target}`
- WAN-интерфейс: `{settings.interface}`
- Прочитано профилей: {profiles_read}
- Записано профилей: {profiles_written}
- TCP-порты: `{','.join(tcp_ports) or '(отключены)'}`
- UDP-порты: `{','.join(udp_ports) or '(отключены)'}`
- TLS fake: `{settings.tls_fake_mode}`; лимит повторов: `{settings.fake_repeats_limit or 'исходный'}`
- Целевая совместимость: nfqws2-keenetic 1.2.8 / zapret2 v1.0.5.2; эффективность проверяется на роутере.

## Диагностика

{diagnostics_text}

## Установка

1. Установите актуальный пакет `nfqws2-keenetic` штатным способом.
2. Сохраните резервную копию `{root}/nfqws2.conf`.
3. Скопируйте содержимое этой папки в `{root}` с сохранением каталогов `lists/` и `blobs/`.
4. Не заменяйте штатный init-скрипт пакета.
5. Выполните `{service}` и проверьте `service nfqws2-keenetic status`.
{web_note}

Перед установкой обязательно проверьте WAN-интерфейс. Для Keenetic это часто `eth3`, `eth2.2` или `ppp0`, но значение зависит от подключения.
"""


def _write_archive(output: Path) -> Path:
    archive = output.parent / f"{output.name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                target.write(path, path.relative_to(output))
    return archive


def convert(settings: ConverterSettings) -> ConversionResult:
    settings.source = settings.source.resolve()
    settings.output = settings.output.resolve()
    if settings.target not in {"keenetic", "openwrt"}:
        raise ConversionError("target должен быть keenetic или openwrt")
    if settings.game_filter not in {"disabled", "all", "tcp", "udp"}:
        raise ConversionError("game_filter должен быть disabled, all, tcp или udp")
    if settings.ipset_mode not in {"loaded", "current"}:
        raise ConversionError("ipset_mode должен быть loaded или current")
    if settings.tls_fake_mode not in {"source", "clone"}:
        raise ConversionError("tls_fake_mode должен быть source или clone")
    if settings.fake_repeats_limit is not None and (
        not isinstance(settings.fake_repeats_limit, int) or settings.fake_repeats_limit < 1
    ):
        raise ConversionError("fake_repeats_limit должен быть положительным целым числом")
    if not 0 <= settings.queue_num <= 65535:
        raise ConversionError("queue_num должен быть от 0 до 65535")
    if not settings.source.is_dir():
        raise ConversionError(f"Каталог Flowseal не найден: {settings.source}")

    profile_path = Path(settings.profile)
    if not profile_path.is_absolute():
        profile_path = settings.source / profile_path
    if profile_path.suffix.lower() != ".bat":
        profile_path = profile_path.with_suffix(".bat")
    if not profile_path.is_file():
        raise ConversionError(f"Профиль не найден: {profile_path}")

    _, raw_profiles = parse_batch(profile_path)
    resolved_profiles = [_resolved_options(profile, settings) for profile in raw_profiles]
    diagnostics: list[Diagnostic] = []

    if settings.output.exists() and any(settings.output.iterdir()):
        raise ConversionError(f"Выходной каталог не пуст: {settings.output}")
    settings.output.mkdir(parents=True, exist_ok=True)
    bundle = _Bundle(settings, diagnostics)

    converted: list[ConvertedProfile] = []
    for number, profile in enumerate(resolved_profiles, start=1):
        item = _translate_profile(profile, number, bundle, diagnostics)
        if item is not None and item.arguments:
            converted.append(item)

    if not converted:
        raise ConversionError("После конвертации не осталось ни одного рабочего профиля")
    tcp_ports = _collect_ports(resolved_profiles, "tcp")
    udp_ports = _collect_ports(resolved_profiles, "udp")
    for transport, ports in (("TCP", tcp_ports), ("UDP", udp_ports)):
        multiport_slots = sum(2 if "-" in port or ":" in port else 1 for port in ports)
        if multiport_slots > 15:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "multiport-limit",
                    f"{transport}_PORTS использует {multiport_slots} слотов, но xt_multiport допускает не более 15.",
                )
            )
    if settings.strict and any(item.level == "warning" for item in diagnostics):
        messages = "; ".join(item.message for item in diagnostics if item.level == "warning")
        raise ConversionError(f"Строгий режим: {messages}")

    config_text = _render_config(settings, bundle, converted, tcp_ports, udp_ports)
    config_path = settings.output / "nfqws2.conf"
    config_path.write_text(config_text, encoding="utf-8", newline="\n")
    _render_web_import(config_text, settings, bundle)

    report_text = _render_report(
        settings, profile_path, len(raw_profiles), len(converted), tcp_ports, udp_ports, diagnostics
    )
    report_path = settings.output / "REPORT.md"
    report_path.write_text(report_text, encoding="utf-8", newline="\n")
    machine_report = {
        "source": str(profile_path),
        "target": settings.target,
        "profiles_read": len(raw_profiles),
        "profiles_written": len(converted),
        "tls_fake_mode": settings.tls_fake_mode,
        "fake_repeats_limit": settings.fake_repeats_limit,
        "tcp_ports": tcp_ports,
        "udp_ports": udp_ports,
        "diagnostics": [asdict(item) for item in diagnostics],
        "files": [str(path.relative_to(settings.output)) for path in sorted(settings.output.rglob("*")) if path.is_file()],
    }
    (settings.output / "report.json").write_text(
        json.dumps(machine_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    archive_path = _write_archive(settings.output) if settings.archive else None
    return ConversionResult(
        settings.output,
        config_path,
        report_path,
        archive_path,
        len(raw_profiles),
        len(converted),
        tcp_ports,
        udp_ports,
        diagnostics,
    )
