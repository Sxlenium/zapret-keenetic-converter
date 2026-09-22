"""Exercise desktop controls without connecting to a router. Requires Tcl/Tk."""
from tkinter import Tk
from pathlib import Path
from tempfile import TemporaryDirectory

from zapret_keenetic.gui import ConverterApp


def main():
    root = Tk()
    root.withdraw()
    try:
        app = ConverterApp(root)
        root.update_idletasks()
        assert [app.tabs.tab(tab, "text") for tab in app.tabs.tabs()] == ["Конвертация", "Установка", "Журнал"]
        assert not app.auth_panel.winfo_manager()
        app.install_after_convert.set(True)
        app._on_install_changed()
        assert app.auth_panel.winfo_manager() == "pack"
        app.target_label.set("OpenWrt")
        assert not app.install_after_convert.get()
        assert not app.auth_panel.winfo_manager()
        assert app.policy_entry.instate(["disabled"])
        assert app.install_check.instate(["disabled"])
        app.target_label.set("Keenetic / Entware")
        assert not app.policy_entry.instate(["disabled"])
        for button in (app.advanced_button, app.experiments_button, app.faq_button):
            button.invoke()
            assert button.cget("text").startswith("▾")
            button.invoke()
            assert button.cget("text").startswith("▸")
        with TemporaryDirectory() as temporary:
            app.source.set(temporary)
            app.profile.set("general.bat")
            app.output.set(str(Path(temporary) / "result"))
            app.ipv6.set(False)
            app.archive.set(True)
            app.policy_exclude.set(True)
            app.strict.set(True)
            app.clone_tls.set(True)
            app.fake_repeats_limit.set("3")
            settings = app._settings()
            assert not settings.ipv6 and settings.archive and settings.policy_exclude and settings.strict
            assert settings.tls_fake_mode == "clone" and settings.fake_repeats_limit == 3
        app._write_log("GUI check", clear=True)
        assert app.log.get("1.0", "end").strip() == "GUI check"
        root.update_idletasks()
        print("GUI: tabs, disclosures, installation, platform switching, option binding and log passed.")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
