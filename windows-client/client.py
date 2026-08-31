import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

CONFIG_BASE = "https://apps.93-119-6-183.sslip.io"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BouwFlow"
APP_EXE = APP_DIR / "BouwFlow.exe"
CONFIG_FILE = APP_DIR / "config.json"


def message(text, title="BouwFlow"):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception:
        pass


def slug_from_filename():
    name = Path(sys.executable).name if getattr(sys, "frozen", False) else Path(sys.argv[0]).name
    m = re.match(r"BouwFlow-(.+?)-Setup\.exe$", name, re.I)
    return m.group(1) if m else None


def fetch_config(slug):
    url = f"{CONFIG_BASE}/api/client-config/{slug}"
    req = urllib.request.Request(url, headers={"User-Agent": "BouwFlow-Windows/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def create_shortcut(path, target, description):
    ps = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut('{str(path).replace("'", "''")}');"
        f"$s.TargetPath='{str(target).replace("'", "''")}';"
        f"$s.WorkingDirectory='{str(APP_DIR).replace("'", "''")}';"
        f"$s.Description='{description.replace("'", "''")}';"
        "$s.Save()"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", ps],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


def install(slug):
    config = fetch_config(slug)
    APP_DIR.mkdir(parents=True, exist_ok=True)

    current = Path(sys.executable)
    if current.resolve() != APP_EXE.resolve():
        shutil.copy2(current, APP_EXE)

    config["slug"] = slug
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "BouwFlow.lnk"
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "BouwFlow.lnk"
    description = f"BouwFlow - {config.get('company', slug)}"
    create_shortcut(desktop, APP_EXE, description)
    create_shortcut(start_menu, APP_EXE, description)

    message(f"BouwFlow is geinstalleerd voor {config.get('company', slug)}.\n\nJe vindt BouwFlow op je bureaublad en in het Startmenu.")
    launch(config)


def load_config():
    if not CONFIG_FILE.exists():
        return None
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_edge():
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def launch(config):
    url = config.get("app_url") or CONFIG_BASE
    edge = find_edge()
    if edge:
        subprocess.Popen([str(edge), f"--app={url}", "--start-maximized"])
    else:
        os.startfile(url)


def main():
    slug = slug_from_filename()
    if slug:
        try:
            install(slug)
        except Exception as exc:
            message(f"Installeren is niet gelukt.\n\n{exc}", "BouwFlow - fout")
        return

    config = load_config()
    if not config:
        message("Deze BouwFlow-installatie is nog niet gekoppeld aan een bedrijf.", "BouwFlow")
        return
    launch(config)


if __name__ == "__main__":
    main()
