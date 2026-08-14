from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from . import __version__
from .converter import ConversionError, ConverterSettings, convert
from .deployer import DeploymentError, DeploymentSettings, deploy_bundle, deployment_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zapret-keenetic",
        description="Конвертация профилей zapret-discord-youtube (winws) в пакет nfqws2-keenetic/OpenWrt.",
    )
    parser.add_argument("source", type=Path, help="каталог распакованного zapret-discord-youtube")
    parser.add_argument("profile", help="имя .bat-профиля, например 'general (ALT11).bat'")
    parser.add_argument("-o", "--output", type=Path, required=True, help="новый или пустой выходной каталог")
    parser.add_argument("--target", choices=("keenetic", "openwrt"), default="keenetic")
    parser.add_argument("--interface", default="eth3", help="WAN-интерфейс роутера (по умолчанию: eth3)")
    parser.add_argument(
        "--game-filter",
        choices=("disabled", "all", "tcp", "udp"),
        default="disabled",
        help="эквивалент Game Filter Flowseal (по умолчанию: disabled)",
    )
    parser.add_argument(
        "--ipset-mode",
        choices=("loaded", "current"),
        default="loaded",
        help="loaded использует ipset-all.txt.backup, если основной список пуст или отключён заглушкой",
    )
    parser.add_argument("--no-ipv6", action="store_true", help="отключить обработку IPv6")
    parser.add_argument("--policy-name", default="nfqws", help="имя политики доступа Keenetic")
    parser.add_argument("--policy-exclude", action="store_true", help="обрабатывать всех, кроме устройств политики")
    parser.add_argument("--queue-num", type=int, default=300, help="номер NFQUEUE (по умолчанию: 300)")
    parser.add_argument("--strict", action="store_true", help="не создавать результат при предупреждениях")
    parser.add_argument("--archive", action="store_true", help="дополнительно создать ZIP рядом с каталогом")
    install = parser.add_argument_group("автоматическая установка на Keenetic")
    install.add_argument("--install", action="store_true", help="после конвертации установить результат через Web API")
    install.add_argument(
        "--install-mode",
        choices=("hybrid", "exact"),
        default="hybrid",
        help="hybrid: Discord из Flowseal + адаптивный YouTube nfqws2; exact: весь выбранный профиль",
    )
    install.add_argument("--router-url", default="http://192.168.1.1:90/", help="адрес web-интерфейса nfqws2")
    install.add_argument("--router-user", default="root", help="пользователь web-интерфейса nfqws2")
    install.add_argument(
        "--router-password",
        help="пароль (безопаснее не указывать: программа запросит его без отображения)",
    )
    install.add_argument(
        "--router-password-env",
        default="NFQWS2_ROUTER_PASSWORD",
        help="имя переменной окружения с паролем",
    )
    install.add_argument("--router-timeout", type=float, default=60.0, help="тайм-аут Web API в секундах")
    install.add_argument("--backup-dir", type=Path, help="каталог локальных резервных копий роутера")
    install.add_argument(
        "--check-services",
        action="store_true",
        help="после установки проверить с этого компьютера YouTube и Discord",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.install and args.target != "keenetic":
        print("Ошибка: автоматическая установка через Web API поддерживается только для Keenetic", file=sys.stderr)
        return 2
    password = ""
    if args.install:
        password = args.router_password or os.environ.get(args.router_password_env, "")
        if not password and sys.stdin.isatty():
            password = getpass.getpass("Пароль web-интерфейса nfqws2: ")
        if not password:
            print(
                f"Ошибка: задайте пароль интерактивно, через --router-password или переменную {args.router_password_env}",
                file=sys.stderr,
            )
            return 2
    try:
        result = convert(
            ConverterSettings(
                source=args.source,
                profile=args.profile,
                output=args.output,
                target=args.target,
                interface=args.interface,
                game_filter=args.game_filter,
                ipset_mode=args.ipset_mode,
                ipv6=not args.no_ipv6,
                policy_name=args.policy_name,
                policy_exclude=args.policy_exclude,
                queue_num=args.queue_num,
                strict=args.strict,
                archive=args.archive,
            )
        )
    except (ConversionError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2

    print(f"Готово: {result.output}")
    print(f"Профили: {result.profiles_written}/{result.profiles_read}; предупреждения: {result.warning_count}")
    print(f"Конфиг: {result.config}")
    print(f"Отчёт: {result.report}")
    if result.archive:
        print(f"Архив: {result.archive}")
    if args.install:
        try:
            deployment = deploy_bundle(
                DeploymentSettings(
                    bundle=result.output,
                    router_url=args.router_url,
                    username=args.router_user,
                    password=password,
                    mode=args.install_mode,
                    backup_root=args.backup_dir,
                    timeout=args.router_timeout,
                    check_services=args.check_services,
                ),
                progress=lambda message: print(f"[роутер] {message}"),
            )
        except (DeploymentError, OSError) as error:
            print(f"Ошибка установки: {error}", file=sys.stderr)
            print(f"Конвертированный результат сохранён: {result.output}", file=sys.stderr)
            return 3
        report_path = result.output / "deployment.json"
        report_path.write_text(
            json.dumps(deployment_report(deployment), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Установлено на роутер; nfqws2 {deployment.service_version or 'работает'}")
        print(f"Резервная копия: {deployment.backup}")
        for check in deployment.connectivity:
            outcome = f"HTTP {check.status}" if check.ok else f"ошибка: {check.error}"
            print(f"Проверка {check.url}: {outcome}")
    return 0
