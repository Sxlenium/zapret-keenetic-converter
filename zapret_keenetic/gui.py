from __future__ import annotations

import os
import queue
import re
import json
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, TclError, Text, Tk, filedialog, messagebox
from tkinter import ttk

from . import __version__
from .converter import ConversionError, ConversionResult, ConverterSettings, convert, parse_batch
from .deployer import (
    DeploymentError,
    DeploymentResult,
    DeploymentSettings,
    deploy_bundle,
    deployment_report,
)


TARGET_LABELS = {
    "Keenetic / Entware": "keenetic",
    "OpenWrt": "openwrt",
}
GAME_FILTER_LABELS = {
    "Выключен": "disabled",
    "TCP и UDP": "all",
    "Только TCP": "tcp",
    "Только UDP": "udp",
}
IPSET_LABELS = {
    "Загруженный список (.backup, если основной пуст или отключён)": "loaded",
    "Текущий ipset-all.txt без замены": "current",
}
INSTALL_MODE_LABELS = {
    "Точный: полностью заменить конфиг выбранной стратегией": "exact",
    "Гибридный: Discord Flowseal + адаптивный YouTube": "hybrid",
}


def discover_profiles(source: Path) -> list[str]:
    """Find real winws profiles and return source-relative paths."""
    if not source.is_dir():
        return []
    profiles: list[str] = []
    for candidate in source.rglob("*.bat"):
        if any(part.lower() in {".git", "bin"} for part in candidate.relative_to(source).parts[:-1]):
            continue
        try:
            _, parsed = parse_batch(candidate)
        except (ConversionError, OSError):
            continue
        if any(option.name == "dpi-desync" and option.value for profile in parsed for option in profile):
            profiles.append(candidate.relative_to(source).as_posix())
    return sorted(profiles, key=lambda value: ("general" not in value.lower(), value.lower()))


def suggest_output(source: Path, profile: str, target: str, moment: datetime | None = None) -> Path:
    stamp = (moment or datetime.now()).strftime("%Y%m%d-%H%M%S")
    stem = Path(profile).stem
    safe_stem = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]+", "-", stem).strip("-").lower() or "profile"
    parent = source.parent / "KeeneticZapret-converted"
    candidate = parent / f"{safe_stem}-{target}-{stamp}"
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{safe_stem}-{target}-{stamp}-{suffix}"
        suffix += 1
    return candidate


def _open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class ConverterApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(f"Flowseal → nfqws2 — конвертер {__version__}")
        self.root.geometry("1060x780")
        self.root.minsize(920, 650)
        self.root.option_add("*tearOff", False)

        self.source = StringVar()
        self.profile = StringVar()
        self.output = StringVar()
        self.target_label = StringVar(value="Keenetic / Entware")
        self.interface = StringVar(value="eth3")
        self.game_filter_label = StringVar(value="Выключен")
        self.ipset_label = StringVar(value="Загруженный список (.backup, если основной пуст или отключён)")
        self.ipv6 = BooleanVar(value=True)
        self.policy_name = StringVar(value="nfqws")
        self.policy_exclude = BooleanVar(value=False)
        self.queue_num = IntVar(value=300)
        self.strict = BooleanVar(value=False)
        self.clone_tls = BooleanVar(value=False)
        self.fake_repeats_limit = StringVar(value="0")
        self.archive = BooleanVar(value=False)
        self.install_after_convert = BooleanVar(value=False)
        self.install_mode_label = StringVar(value=next(iter(INSTALL_MODE_LABELS)))
        self.router_url = StringVar(value="http://192.168.1.1:90/")
        self.router_user = StringVar(value="root")
        self.router_password = StringVar()
        self.check_services = BooleanVar(value=True)
        self.status = StringVar(value="Выберите папку zapret-discord-youtube")
        self.last_output: Path | None = None
        self._output_was_selected = False
        self._worker_messages: queue.Queue[tuple[str, object]] = queue.Queue()

        self._configure_style()
        self._build()
        self.target_label.trace_add("write", self._on_target_changed)

    def _configure_style(self) -> None:
        from .gui_layout import configure_style
        configure_style(self.root)

    def _build(self) -> None:
        from .gui_layout import build
        build(self, __version__, TARGET_LABELS, GAME_FILTER_LABELS, IPSET_LABELS, INSTALL_MODE_LABELS)
    def _choose_source(self) -> None:
        initial = self.source.get() or str(Path.home())
        selected = filedialog.askdirectory(title="Выберите папку zapret-discord-youtube", initialdir=initial)
        if not selected:
            return
        self.source.set(selected)
        self._output_was_selected = False
        self._scan_profiles()

    def _scan_profiles(self) -> None:
        source = Path(self.source.get().strip()).expanduser()
        self.status.set("Поиск стратегий…")
        self.root.update_idletasks()
        profiles = discover_profiles(source)
        self.profile_box["values"] = profiles
        if profiles:
            current = self.profile.get()
            self.profile.set(current if current in profiles else profiles[0])
            self.status.set(f"Найдено стратегий: {len(profiles)}")
            self._refresh_output()
        else:
            self.profile.set("")
            self.status.set("Рабочие .bat-стратегии не найдены")
            messagebox.showwarning(
                "Стратегии не найдены",
                "В выбранной папке не найдены .bat-файлы с распознаваемой командой winws.exe.",
            )

    def _choose_output(self) -> None:
        initial = self.output.get() or str(Path.home())
        selected = filedialog.askdirectory(title="Выберите пустую папку результата", initialdir=initial)
        if selected:
            self.output.set(selected)
            self._output_was_selected = True

    def _on_profile_changed(self, _event: object | None = None) -> None:
        self._output_was_selected = False
        self._refresh_output()

    def _on_target_changed(self, *_args: object) -> None:
        target = TARGET_LABELS[self.target_label.get()]
        if target == "openwrt" and self.interface.get() == "eth3":
            self.interface.set("pppoe-wan")
        elif target == "keenetic" and self.interface.get() == "pppoe-wan":
            self.interface.set("eth3")
        state = "normal" if target == "keenetic" else "disabled"
        self.policy_entry.configure(state=state)
        self.policy_exclude_button.configure(state=state)
        if target != "keenetic":
            self.install_after_convert.set(False)
        self._on_install_changed()
        if not self._output_was_selected:
            self._refresh_output()

    def _on_install_changed(self) -> None:
        enabled = self.install_after_convert.get() and TARGET_LABELS[self.target_label.get()] == "keenetic"
        self.install_check.configure(state="normal" if TARGET_LABELS[self.target_label.get()] == "keenetic" else "disabled")
        if enabled:
            self.auth_panel.pack(fill="x")
        else:
            self.auth_panel.pack_forget()
        self.install_summary.configure(text="Автоматически после конвертации" if enabled else "Вручную через web-интерфейс")
        state = "readonly" if enabled else "disabled"
        self.install_mode_box.configure(state=state)
        entry_state = "normal" if enabled else "disabled"
        self.router_url_entry.configure(state=entry_state)
        self.router_user_entry.configure(state=entry_state)
        self.router_password_entry.configure(state=entry_state)
        self.check_services_button.configure(state=entry_state)
        self.convert_button.configure(
            text="Конвертировать и установить" if enabled else "Конвертировать"
        )

    def _refresh_output(self) -> None:
        source_text = self.source.get().strip()
        profile = self.profile.get().strip()
        if not source_text or not profile or self._output_was_selected:
            return
        target = TARGET_LABELS[self.target_label.get()]
        self.output.set(str(suggest_output(Path(source_text).expanduser(), profile, target)))

    def _settings(self) -> ConverterSettings:
        source_text = self.source.get().strip()
        profile = self.profile.get().strip()
        output_text = self.output.get().strip()
        interface = self.interface.get().strip()
        policy_name = self.policy_name.get().strip()
        try:
            queue_num = int(self.queue_num.get())
        except (TypeError, ValueError) as error:
            raise ConversionError("Номер NFQUEUE должен быть целым числом") from error
        if not source_text:
            raise ConversionError("Выберите папку zapret-discord-youtube")
        source = Path(source_text).expanduser()
        if not source.is_dir():
            raise ConversionError("Выберите существующую папку zapret-discord-youtube")
        if not profile:
            raise ConversionError("Выберите стратегию")
        if not output_text:
            raise ConversionError("Выберите папку результата")
        output = Path(output_text).expanduser()
        if not interface:
            raise ConversionError("Укажите WAN-интерфейс")
        if not 0 <= queue_num <= 65535:
            raise ConversionError("Номер NFQUEUE должен быть от 0 до 65535")
        target = TARGET_LABELS[self.target_label.get()]
        if target == "keenetic" and not policy_name:
            raise ConversionError("Укажите имя политики Keenetic")
        try:
            repeats_limit = int(self.fake_repeats_limit.get())
        except ValueError as error:
            raise ConversionError("Лимит повторов должен быть целым числом") from error
        if repeats_limit < 0:
            raise ConversionError("Лимит повторов не может быть отрицательным")
        return ConverterSettings(
            source=source,
            profile=profile,
            output=output,
            target=target,
            interface=interface,
            game_filter=GAME_FILTER_LABELS[self.game_filter_label.get()],
            ipset_mode=IPSET_LABELS[self.ipset_label.get()],
            ipv6=self.ipv6.get(),
            policy_name=policy_name or "nfqws",
            policy_exclude=self.policy_exclude.get() if target == "keenetic" else False,
            queue_num=queue_num,
            strict=self.strict.get(),
            archive=self.archive.get(),
            tls_fake_mode="clone" if self.clone_tls.get() else "source",
            fake_repeats_limit=repeats_limit or None,
        )

    def _deployment_settings(self, conversion: ConverterSettings) -> DeploymentSettings | None:
        if not self.install_after_convert.get():
            return None
        if conversion.target != "keenetic":
            raise ConversionError("Автоматическая установка через Web API поддерживается только для Keenetic")
        router_url = self.router_url.get().strip()
        username = self.router_user.get().strip()
        password = self.router_password.get()
        if not router_url:
            raise ConversionError("Укажите адрес web-интерфейса nfqws2")
        if not username:
            raise ConversionError("Укажите пользователя web-интерфейса nfqws2")
        if not password:
            raise ConversionError("Введите пароль web-интерфейса nfqws2")
        return DeploymentSettings(
            bundle=conversion.output,
            router_url=router_url,
            username=username,
            password=password,
            mode=INSTALL_MODE_LABELS[self.install_mode_label.get()],
            check_services=self.check_services.get(),
        )

    def _start_conversion(self) -> None:
        try:
            settings = self._settings()
            deployment = self._deployment_settings(settings)
        except (ConversionError, OSError) as error:
            messagebox.showerror("Не заполнены параметры", str(error))
            return
        if deployment and not messagebox.askyesno(
            "Подтверждение установки",
            "Программа создаст локальную резервную копию, загрузит списки и nfqws2.conf "
            "на роутер, затем перезапустит службу. Продолжить?",
        ):
            return
        self.convert_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Конвертация…")
        self._write_log("Запуск конвертации…\n", clear=True)
        threading.Thread(target=self._convert_worker, args=(settings, deployment), daemon=True).start()
        self.root.after(100, self._poll_worker)

    def _convert_worker(
        self, settings: ConverterSettings, deployment: DeploymentSettings | None
    ) -> None:
        try:
            conversion = convert(settings)
            installed: DeploymentResult | None = None
            if deployment:
                installed = deploy_bundle(
                    deployment,
                    progress=lambda message: self._worker_messages.put(("progress", message)),
                )
                report_path = conversion.output / "deployment.json"
                report_path.write_text(
                    json.dumps(deployment_report(installed), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
        except (ConversionError, DeploymentError, OSError) as error:
            self._worker_messages.put(("error", str(error)))
            return
        self._worker_messages.put(("success", (conversion, installed)))

    def _poll_worker(self) -> None:
        try:
            kind, payload = self._worker_messages.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_worker)
            return
        if kind == "progress":
            self.status.set(str(payload))
            self._write_log(str(payload) + "\n")
            self.root.after(100, self._poll_worker)
        elif kind == "success" and isinstance(payload, tuple):
            conversion, deployment = payload
            self._conversion_finished(conversion, deployment)
        else:
            self._conversion_failed(str(payload))

    def _conversion_failed(self, message: str) -> None:
        self.tabs.select(self.journal_tab)
        self.progress.stop()
        self.convert_button.configure(state="normal")
        self.status.set("Ошибка конвертации")
        self._write_log(f"ОШИБКА: {message}\n")
        self.router_password.set("")
        messagebox.showerror("Конвертация не выполнена", message)

    def _conversion_finished(
        self, conversion: ConversionResult, deployment: DeploymentResult | None = None
    ) -> None:
        self.tabs.select(self.journal_tab)
        self.progress.stop()
        self.convert_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self.last_output = conversion.output
        self.status.set("Установлено на роутер" if deployment else "Готово")
        lines = [
            f"Результат: {conversion.output}",
            f"Профили: {conversion.profiles_written}/{conversion.profiles_read}",
            f"Предупреждения: {conversion.warning_count}",
            f"Конфиг: {conversion.config.name}",
            f"Отчёт: {conversion.report.name}",
        ]
        if conversion.archive:
            lines.append(f"ZIP: {conversion.archive}")
        if TARGET_LABELS[self.target_label.get()] == "keenetic":
            lines.append("Веб-интерфейс: web-import/nfqws2.conf")
        if deployment:
            lines.extend(
                (
                    f"Установка: {deployment.mode}",
                    f"Загружено файлов: {len(deployment.files_uploaded)}",
                    f"nfqws2: {deployment.service_version or 'работает'}",
                    f"Резервная копия: {deployment.backup}",
                )
            )
            for check in deployment.connectivity:
                outcome = f"HTTP {check.status}" if check.ok else f"ОШИБКА: {check.error}"
                lines.append(f"Проверка {check.url}: {outcome}")
        for diagnostic in conversion.diagnostics:
            where = f", профиль {diagnostic.profile}" if diagnostic.profile else ""
            lines.append(f"[{diagnostic.level.upper()} / {diagnostic.code}{where}] {diagnostic.message}")
        self._write_log("\n".join(lines) + "\n", clear=True)
        self.router_password.set("")
        messagebox.showinfo(
            "Установка завершена" if deployment else "Конвертация завершена",
            (
                f"Готово. Создано профилей: {conversion.profiles_written}.\n"
                f"Предупреждений: {conversion.warning_count}.\n\n"
                + (
                    f"Конфигурация установлена, nfqws2 работает.\nРезервная копия: {deployment.backup}"
                    if deployment
                    else "Перед установкой откройте REPORT.md."
                )
            ),
        )

    def _write_log(self, text: str, clear: bool = False) -> None:
        self.log.configure(state="normal")
        if clear:
            self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _open_result(self) -> None:
        if self.last_output and self.last_output.exists():
            try:
                _open_path(self.last_output)
            except OSError as error:
                messagebox.showerror("Не удалось открыть папку", str(error))


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    try:
        root = Tk()
    except TclError as error:
        print(
            "Не удалось открыть графический интерфейс Tcl/Tk. "
            "Установите обычный Python с поддержкой tkinter или используйте CLI.\n"
            f"Техническая ошибка: {error}",
            file=sys.stderr,
        )
        return 3
    ConverterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
