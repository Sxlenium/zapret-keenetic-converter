from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Callable, Protocol

from .hybrid import HybridConfigError, build_hybrid_keenetic_config


class DeploymentError(RuntimeError):
    """A bundle could not be installed or verified safely."""


@dataclass(frozen=True)
class DeploymentSettings:
    bundle: Path
    router_url: str = "http://192.168.1.1:90/"
    username: str = "root"
    password: str = ""
    mode: str = "hybrid"
    backup_root: Path | None = None
    timeout: float = 60.0
    check_services: bool = False


@dataclass(frozen=True)
class ConnectivityCheck:
    url: str
    ok: bool
    status: int | None = None
    error: str | None = None


@dataclass
class DeploymentResult:
    backup: Path
    installed_config: Path
    mode: str
    files_uploaded: list[str]
    service_version: str | None
    restart_output: list[str] = field(default_factory=list)
    connectivity: list[ConnectivityCheck] = field(default_factory=list)


ProgressCallback = Callable[[str], None]


class ApiLike(Protocol):
    def login(self, username: str, password: str) -> None: ...

    def call(self, command: str, **fields: str) -> dict[str, object]: ...

    def read(self, filename: str) -> str: ...

    def save(self, filename: str, content: str) -> None: ...


def normalize_router_url(url: str) -> str:
    value = url.strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DeploymentError("Адрес роутера должен начинаться с http:// или https://")
    path = parsed.path or "/"
    if path.endswith("/"):
        path += "index.php"
    elif not path.lower().endswith(".php"):
        path += "/index.php"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


class RouterApi:
    def __init__(self, endpoint: str, timeout: float = 60.0) -> None:
        self.endpoint = normalize_router_url(endpoint)
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, command: str, **fields: str) -> dict[str, object]:
        body = urllib.parse.urlencode({"cmd": command, **fields}).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=body)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError) as error:
            raise DeploymentError(f"Роутер недоступен: {error}") from error
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DeploymentError(f"Некорректный ответ Web API для команды {command}: {raw[:200]}") from error
        if not isinstance(result, dict) or result.get("status") != 0:
            raise DeploymentError(f"Команда Web API {command} завершилась ошибкой: {result}")
        return result

    def login(self, username: str, password: str) -> None:
        self.call("login", user=username, password=password)

    def read(self, filename: str) -> str:
        result = self.call("filecontent", filename=filename)
        content = result.get("content")
        if not isinstance(content, str):
            raise DeploymentError(f"Web API не вернул содержимое {filename}")
        return content

    def save(self, filename: str, content: str) -> None:
        # PHP empty() rejects an empty form value. A newline is an equivalent
        # empty list for nfqws2 and remains editable in the web interface.
        self.call("filesave", filename=filename, content=content if content else "\n")


def _emit(callback: ProgressCallback | None, message: str) -> None:
    if callback:
        callback(message)


def _file_names(api: ApiLike, file_type: str) -> set[str]:
    result = api.call("filenames", type=file_type)
    files = result.get("files")
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise DeploymentError(f"Web API не вернул список файлов типа {file_type}")
    return set(files)


def _same_text(left: str, right: str) -> bool:
    return left.replace("\r\n", "\n").rstrip("\n") == right.replace("\r\n", "\n").rstrip("\n")


def _unique_backup(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = root / f"router-backup-{stamp}"
    suffix = 2
    while candidate.exists():
        candidate = root / f"router-backup-{stamp}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _connectivity_checks(timeout: float) -> list[ConnectivityCheck]:
    urls = (
        "https://www.youtube.com/",
        "https://discord.com/api/v10/gateway",
    )
    context = ssl.create_default_context()
    checks: list[ConnectivityCheck] = []
    for url in urls:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=min(timeout, 20.0), context=context) as response:
                checks.append(ConnectivityCheck(url, True, response.status))
        except urllib.error.HTTPError as error:
            checks.append(ConnectivityCheck(url, True, error.code))
        except (OSError, urllib.error.URLError) as error:
            checks.append(ConnectivityCheck(url, False, error=str(error)))
    return checks


def deploy_bundle(
    settings: DeploymentSettings,
    *,
    progress: ProgressCallback | None = None,
    api: ApiLike | None = None,
) -> DeploymentResult:
    bundle = settings.bundle.resolve()
    web_root = bundle / "web-import"
    source_config_path = web_root / "nfqws2.conf"
    lists_root = web_root / "lists"
    if settings.mode not in {"exact", "hybrid"}:
        raise DeploymentError("Режим установки должен быть exact или hybrid")
    if not settings.username.strip():
        raise DeploymentError("Не указано имя пользователя роутера")
    if not settings.password:
        raise DeploymentError("Не указан пароль роутера")
    if not source_config_path.is_file() or not lists_root.is_dir():
        raise DeploymentError("В результате конвертации отсутствует полный каталог web-import")

    list_paths = sorted(lists_root.glob("*.list"), key=lambda path: path.name.lower())
    if not list_paths:
        raise DeploymentError("В web-import/lists не найдено ни одного списка")
    client = api or RouterApi(settings.router_url, settings.timeout)

    _emit(progress, "Подключение к Web API роутера…")
    client.login(settings.username.strip(), settings.password)
    conf_names = _file_names(client, "conf")
    list_names = _file_names(client, "list")
    if "nfqws2.conf" not in conf_names:
        raise DeploymentError("На роутере не найден nfqws2.conf; сначала установите nfqws2-keenetic")

    current_config = client.read("nfqws2.conf")
    converted_config = source_config_path.read_text(encoding="utf-8")
    if settings.mode == "hybrid":
        if "nfqws2.conf-opkg" not in conf_names:
            raise DeploymentError("Для гибридного режима на роутере нужен nfqws2.conf-opkg")
        try:
            install_config = build_hybrid_keenetic_config(client.read("nfqws2.conf-opkg"), converted_config)
        except HybridConfigError as error:
            raise DeploymentError(str(error)) from error
        installed_config_path = web_root / "nfqws2-hybrid.conf"
        installed_config_path.write_text(install_config, encoding="utf-8", newline="\n")
    else:
        install_config = converted_config
        installed_config_path = source_config_path

    existing_lists = {path.name: client.read(path.name) for path in list_paths if path.name in list_names}
    created_lists = [path.name for path in list_paths if path.name not in list_names]
    backup_root = (settings.backup_root or (bundle / "router-backups")).resolve()
    backup = _unique_backup(backup_root)
    (backup / "nfqws2.conf").write_text(current_config, encoding="utf-8", newline="\n")
    backup_lists = backup / "lists"
    backup_lists.mkdir()
    for filename, content in existing_lists.items():
        (backup_lists / filename).write_text(content, encoding="utf-8", newline="\n")
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(),
        "router_url": normalize_router_url(settings.router_url),
        "mode": settings.mode,
        "restored_files": sorted(existing_lists),
        "created_files": created_lists,
    }
    (backup / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    _emit(progress, f"Резервная копия: {backup}")

    changed = False
    created_during_install: list[str] = []
    try:
        for path in list_paths:
            if path.name not in list_names:
                client.call("filecreate", filename=path.name)
                created_during_install.append(path.name)
                changed = True
            content = path.read_text(encoding="utf-8-sig")
            _emit(progress, f"Загрузка списка {path.name}…")
            client.save(path.name, content)
            changed = True
            if not _same_text(client.read(path.name), content):
                raise DeploymentError(f"Проверка загруженного списка {path.name} не прошла")

        _emit(progress, "Загрузка nfqws2.conf…")
        client.save("nfqws2.conf", install_config)
        changed = True
        if not _same_text(client.read("nfqws2.conf"), install_config):
            raise DeploymentError("Проверка загруженного nfqws2.conf не прошла")

        _emit(progress, "Перезапуск nfqws2…")
        restart = client.call("restart")
        status: dict[str, object] = {}
        for attempt in range(5):
            status = client.call("status")
            if status.get("service") is True and status.get("nfqws2") is True:
                break
            if attempt < 4:
                time.sleep(0.5)
        if status.get("service") is not True or status.get("nfqws2") is not True:
            raise DeploymentError(f"После перезапуска nfqws2 не работает: {status}")
    except Exception as error:
        rollback_error: Exception | None = None
        if changed:
            _emit(progress, "Ошибка установки — выполняется автоматический откат…")
            try:
                for filename, content in existing_lists.items():
                    client.save(filename, content)
                for filename in created_during_install:
                    client.call("fileremove", filename=filename)
                client.save("nfqws2.conf", current_config)
                client.call("restart")
            except Exception as caught:
                rollback_error = caught
        if rollback_error:
            raise DeploymentError(
                f"Установка не выполнена: {error}. Автоматический откат также завершился ошибкой: "
                f"{rollback_error}. Резервная копия: {backup}"
            ) from error
        raise DeploymentError(f"Установка отменена, прежняя конфигурация восстановлена: {error}") from error

    restart_output = restart.get("output", [])
    if not isinstance(restart_output, list):
        restart_output = []
    connectivity = _connectivity_checks(settings.timeout) if settings.check_services else []
    _emit(progress, "Установка завершена, служба nfqws2 работает.")
    return DeploymentResult(
        backup=backup,
        installed_config=installed_config_path,
        mode=settings.mode,
        files_uploaded=[path.name for path in list_paths] + ["nfqws2.conf"],
        service_version=str(status.get("version")) if status.get("version") is not None else None,
        restart_output=[str(line) for line in restart_output],
        connectivity=connectivity,
    )


def deployment_report(result: DeploymentResult) -> dict[str, object]:
    return {
        "backup": str(result.backup),
        "installed_config": str(result.installed_config),
        "mode": result.mode,
        "files_uploaded": result.files_uploaded,
        "service_version": result.service_version,
        "restart_output": result.restart_output,
        "connectivity": [asdict(check) for check in result.connectivity],
    }
