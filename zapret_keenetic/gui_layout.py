"""Desktop layout for the approved utility design."""
from tkinter import Canvas, Text, ttk

BG = "#FAFBFC"
QUIET = "#EDF0F4"
INK = "#252B29"
MUTED = "#626C67"
LINE = "#D7DCE3"
BLUE = "#315C90"

FAQ = (
    ("Обрабатывать IPv6", "Включает обработку IPv6-трафика в создаваемом конфиге. Оставьте включённым, если ваша сеть использует IPv6. Снятие флажка не отключает IPv6 на роутере: такие соединения останутся без этой обработки."),
    ("Исключать устройства политики", "Выключено — обрабатывать устройства выбранной политики Keenetic. Включено — обрабатывать остальные устройства, исключив участников политики. Имя задаётся в поле «Политика Keenetic». Нужна существующая политика; для OpenWrt настройка не применяется."),
    ("Строгий режим", "Останавливает конвертацию при любом предупреждении, например при неточном переносе параметра. Полезен для проверки совместимости. Не усиливает обход блокировок. При выключенном режиме предупреждения остаются в отчёте."),
    ("Создать ZIP", "Дополнительно упаковывает готовый комплект в ZIP рядом с папкой результата. Удобно для переноса и хранения; на работу стратегии не влияет и само по себе ничего не устанавливает на роутер."),
    ("Эксперимент: TLS fake из живого ClientHello", "Заменяет TLS fake-шаблоны копией начального сообщения текущего TLS-соединения с изменёнными данными. Если копию создать не удалось, fake пропускается. Меняет исходную стратегию и требует ресурсов процессора; ускорение не гарантировано. Другие шаблоны сохраняются. Для первого сравнения оставьте выключенным."),
    ("Лимит fake-повторов", "Стратегия отправляет поддельные пакеты для обхода блокировок. Эта настройка ограничивает, сколько раз они повторяются.\n\nОставьте 0 — программа сохранит настройки выбранной стратегии. Например, значение 3 разрешает не больше трёх повторов. Меньше повторов может снизить нагрузку на роутер, но некоторые сайты могут перестать открываться."),
)


def configure_style(root):
    root.configure(background=BG)
    root.option_add("*Font", ("Segoe UI", 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=INK, font=("Segoe UI", 10))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG)
    style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"))
    style.configure("Heading.TLabel", font=("Segoe UI", 10, "bold"))
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Side.TFrame", background=QUIET)
    style.configure("Side.TLabel", background=QUIET)
    style.configure("SideMuted.TLabel", background=QUIET, foreground=MUTED)
    style.configure("TButton", padding=(12, 8), borderwidth=1, bordercolor=LINE, background=BG)
    style.map("TButton", background=[("active", QUIET)])
    style.configure("Primary.TButton", background=BLUE, foreground="white", font=("Segoe UI", 10, "bold"), padding=(18, 10))
    style.map("Primary.TButton", background=[("disabled", LINE), ("active", "#274C79")], foreground=[("disabled", MUTED), ("!disabled", "white")])
    style.configure("Disclosure.TButton", anchor="w", borderwidth=0, padding=(0, 10))
    style.configure("TEntry", fieldbackground=BG, bordercolor=LINE, padding=7)
    style.configure("TCombobox", fieldbackground=BG, bordercolor=LINE, padding=6, arrowsize=14)
    style.map("TCombobox", fieldbackground=[("readonly", BG)], foreground=[("readonly", INK)])
    style.configure("TSpinbox", fieldbackground=BG, bordercolor=LINE, padding=6)
    style.configure("TCheckbutton", background=BG, padding=(0, 4))
    style.map("TCheckbutton", indicatorbackground=[("selected", BLUE), ("!selected", BG)])
    style.configure("TNotebook", borderwidth=0, tabmargins=(0, 8, 0, 0))
    style.configure("TNotebook.Tab", padding=(18, 10), background=BG)
    style.map("TNotebook.Tab", foreground=[("selected", BLUE)], background=[("selected", QUIET)])
    style.configure("Horizontal.TProgressbar", background=BLUE, troughcolor=QUIET, borderwidth=0)


class ScrollPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = Canvas(self, background=BG, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=(24, 22))
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize)
        self.bindings = []

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        for label in self.bindings:
            label.configure(wraplength=max(180, event.width - 56))

    def enable_wheel(self):
        def scroll(event):
            if self.body.winfo_reqheight() > self.canvas.winfo_height():
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return "break"
        def bind_tree(widget):
            widget.bind("<MouseWheel>", scroll, add="+")
            for child in widget.winfo_children():
                bind_tree(child)
        bind_tree(self)


def disclosure(parent, title):
    box = ttk.Frame(parent)
    box.pack(fill="x", pady=(8, 0))
    ttk.Separator(box).pack(fill="x")
    content = ttk.Frame(box, padding=(0, 10, 0, 8))
    def toggle():
        if content.winfo_manager():
            content.pack_forget()
            button.configure(text="▸  " + title)
        else:
            content.pack(fill="x")
            button.configure(text="▾  " + title)
    button = ttk.Button(box, text="▸  " + title, style="Disclosure.TButton", command=toggle)
    button.pack(fill="x", before=content if content.winfo_manager() else None)
    return content, button


def field(parent, label, variable, values=None, readonly=True, show=None):
    box = ttk.Frame(parent)
    box.pack(fill="x", pady=(0, 16))
    ttk.Label(box, text=label).pack(anchor="w", pady=(0, 6))
    if values is not None:
        widget = ttk.Combobox(box, textvariable=variable, values=values,
                              state="readonly" if readonly else "normal", width=12)
    else:
        widget = ttk.Entry(box, textvariable=variable, show=show or "", width=12)
    widget.pack(fill="x", expand=True)
    return widget


def pair(parent):
    row = ttk.Frame(parent)
    row.pack(fill="x")
    row.columnconfigure((0, 1), weight=1, uniform="fields")
    left, right = ttk.Frame(row), ttk.Frame(row)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
    return left, right


def build(app, version, targets, games, ipsets, modes):
    root = app.root
    header = ttk.Frame(root, padding=(28, 24, 28, 12))
    header.pack(fill="x")
    ttk.Label(header, text="Конвертер стратегий", style="Title.TLabel").pack(side="left")
    ttk.Label(header, text=f"Версия {version}\nFlowseal → nfqws2", style="Muted.TLabel", justify="right").pack(side="right")
    footer = ttk.Frame(root, style="Side.TFrame", padding=(24, 14))
    footer.pack(side="bottom", fill="x")
    app.convert_button = ttk.Button(footer, text="Конвертировать →", style="Primary.TButton", command=app._start_conversion)
    app.convert_button.pack(side="right", padx=(15, 0))
    ttk.Label(footer, textvariable=app.status, style="SideMuted.TLabel", wraplength=460).pack(side="left", fill="x", expand=True)
    app.progress = ttk.Progressbar(root, mode="indeterminate", maximum=100)
    app.progress.pack(side="bottom", fill="x")
    app.tabs = ttk.Notebook(root)
    app.tabs.pack(fill="both", expand=True, padx=16)
    conversion = ttk.Frame(app.tabs)
    installation = ScrollPanel(app.tabs)
    journal = ttk.Frame(app.tabs, padding=24)
    for tab, title in ((conversion, "Конвертация"), (installation, "Установка"), (journal, "Журнал")):
        app.tabs.add(tab, text=title)
    app.journal_tab = journal
    sidebar = ScrollPanel(conversion)
    sidebar.configure(width=280)
    sidebar.pack(side="right", fill="y")
    sidebar.pack_propagate(False)
    sidebar.canvas.configure(background=QUIET)
    side = sidebar.body
    side.configure(style="Side.TFrame", padding=22)
    main = ScrollPanel(conversion)
    main.pack(fill="both", expand=True)
    app.main_panel = main
    body = main.body
    source_row = ttk.Frame(body)
    source_row.pack(fill="x", pady=(0, 16))
    ttk.Label(source_row, text="Папка Flowseal").pack(anchor="w", pady=(0, 6))
    ttk.Button(source_row, text="Выбрать…", command=app._choose_source).pack(side="right", padx=(10, 0))
    ttk.Entry(source_row, textvariable=app.source).pack(fill="x", expand=True, side="left")
    profile_row = ttk.Frame(body)
    profile_row.pack(fill="x")
    ttk.Button(profile_row, text="Обновить", command=app._scan_profiles).pack(side="right", anchor="s", padx=(10, 0), pady=(0, 16))
    app.profile_box = field(profile_row, "Стратегия", app.profile, [])
    app.profile_box.bind("<<ComboboxSelected>>", app._on_profile_changed)
    left, right = pair(body)
    field(left, "Платформа", app.target_label, list(targets))
    field(right, "WAN-интерфейс", app.interface, ("eth3", "eth2.2", "ppp0", "pppoe-wan"), readonly=False)
    checks = ttk.Frame(body)
    checks.pack(fill="x", pady=(0, 12))
    ttk.Checkbutton(checks, text="Обрабатывать IPv6", variable=app.ipv6).pack(side="left")
    ttk.Checkbutton(checks, text="Создать ZIP", variable=app.archive).pack(side="left", padx=20)
    advanced, app.advanced_button = disclosure(body, "Дополнительные параметры")
    left, right = pair(advanced)
    app.policy_entry = field(left, "Политика Keenetic", app.policy_name)
    ttk.Label(right, text="Номер NFQUEUE").pack(anchor="w", pady=(0, 6))
    ttk.Spinbox(right, from_=0, to=65535, textvariable=app.queue_num, width=10).pack(fill="x")
    field(advanced, "Игровые порты", app.game_filter_label, list(games))
    field(advanced, "Списки IPSET", app.ipset_label, list(ipsets))
    app.policy_exclude_button = ttk.Checkbutton(advanced, text="Исключать устройства политики", variable=app.policy_exclude)
    app.policy_exclude_button.pack(anchor="w")
    ttk.Checkbutton(advanced, text="Строгий режим", variable=app.strict).pack(anchor="w")
    experiments, app.experiments_button = disclosure(advanced, "Экспериментальные настройки")
    ttk.Checkbutton(experiments, text="TLS fake из живого ClientHello", variable=app.clone_tls).pack(anchor="w", pady=(0, 12))
    ttk.Label(experiments, text="Лимит fake-повторов (0 — исходный)").pack(anchor="w", pady=(0, 6))
    ttk.Spinbox(experiments, from_=0, to=100, width=8, textvariable=app.fake_repeats_limit).pack(anchor="w")
    help_body, app.faq_button = disclosure(body, "FAQ")
    for title, explanation in FAQ:
        ttk.Label(help_body, text=title, style="Heading.TLabel").pack(anchor="w", pady=(8, 6))
        label = ttk.Label(help_body, text=explanation, wraplength=480, justify="left")
        label.pack(fill="x", pady=(0, 16))
        main.bindings.append(label)
    ttk.Label(side, text="РЕЗУЛЬТАТ", style="SideMuted.TLabel").pack(anchor="w", pady=(0, 8))
    ttk.Label(side, text="Конфиг для nfqws2", style="Side.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 22))
    ttk.Label(side, text="Стратегия", style="SideMuted.TLabel").pack(anchor="w")
    ttk.Label(side, textvariable=app.profile, style="Side.TLabel", wraplength=210).pack(anchor="w", pady=(4, 18))
    ttk.Label(side, text="Способ установки", style="SideMuted.TLabel").pack(anchor="w")
    app.install_summary = ttk.Label(side, text="Вручную через web-интерфейс", style="Side.TLabel", wraplength=210)
    app.install_summary.pack(anchor="w", pady=(4, 18))
    ttk.Label(side, text="Папка сохранения", style="SideMuted.TLabel").pack(anchor="w")
    ttk.Label(side, textvariable=app.output, style="Side.TLabel", wraplength=210).pack(anchor="w", pady=(4, 10))
    ttk.Button(side, text="Изменить папку…", command=app._choose_output).pack(anchor="w", pady=(0, 24))
    ttk.Label(side, text="В КОМПЛЕКТЕ", style="SideMuted.TLabel").pack(anchor="w", pady=(0, 10))
    ttk.Label(side, text="nfqws2.conf\nСписки и шаблоны\nОтчёт конвертации", style="Side.TLabel", justify="left").pack(anchor="w")
    app.open_button = ttk.Button(side, text="Открыть результат", command=app._open_result, state="disabled")
    app.open_button.pack(anchor="w", pady=(20, 0))
    install = installation.body
    ttk.Label(install, text="Установка на Keenetic", style="Heading.TLabel").pack(anchor="w", pady=(0, 10))
    ttk.Label(install, text="Подключение понадобится только для загрузки результата на роутер.", style="Muted.TLabel").pack(anchor="w", pady=(0, 20))
    app.install_check = ttk.Checkbutton(install, text="Установить после конвертации", variable=app.install_after_convert, command=app._on_install_changed)
    app.install_check.pack(anchor="w")
    app.auth_panel = ttk.Frame(install, padding=(0, 22))
    app.router_url_entry = field(app.auth_panel, "Адрес nfqws2", app.router_url)
    left, right = pair(app.auth_panel)
    app.router_user_entry = field(left, "Пользователь", app.router_user)
    app.router_password_entry = field(right, "Пароль", app.router_password, show="•")
    app.install_mode_box = field(app.auth_panel, "Режим установки", app.install_mode_label, list(modes))
    app.check_services_button = ttk.Checkbutton(app.auth_panel, text="Проверить YouTube и Discord", variable=app.check_services)
    app.check_services_button.pack(anchor="w", pady=(0, 18))
    ttk.Label(app.auth_panel, text="Перед установкой программа сохранит текущий конфиг для отката.", style="Muted.TLabel").pack(anchor="w")
    ttk.Label(journal, text="Журнал конвертации", style="Heading.TLabel").pack(anchor="w", pady=(0, 14))
    log_scroll = ttk.Scrollbar(journal)
    log_scroll.pack(side="right", fill="y")
    app.log = Text(journal, wrap="word", font=("Consolas", 10), background=BG, foreground=INK, relief="flat", padx=12, pady=12, yscrollcommand=log_scroll.set)
    app.log.pack(fill="both", expand=True)
    log_scroll.configure(command=app.log.yview)
    app.log.insert("end", "Пока нет запусков. Здесь появятся результат и предупреждения.")
    app.log.configure(state="disabled")
    main.enable_wheel()
    sidebar.enable_wheel()
    installation.enable_wheel()
    app._on_install_changed()
