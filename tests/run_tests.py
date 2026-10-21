#!/usr/bin/env python3
"""Testy Blender Bridge.

    python tests/run_tests.py                 # všechno
    python tests/run_tests.py --only godot    # jen jedna sada
    python tests/run_tests.py --regen-fixtures

Sady:

* ``godot``  — logika pluginu bez editoru (vlastnictví, manifest, cesty,
  kontext, zápis zpět do scény)
* ``blender`` — Blender extension na pozadí (stavba scény, export, výroba
  zdroje, úprava modelu, převody souřadnic)
* ``editor`` — skutečný Godot editor bez okna: tlačítko, kontextové menu,
  automatické načítání změn z Blenderu
* ``e2e``    — celý cyklus Godot → Blender → Godot přes soubory na disku
* ``gui``    — Blender s oknem na virtuálním displeji (Xvfb): start z Godotu,
  panel, zaměření pohledu, úprava modelu; na Windows a bez Xvfb se přeskočí

Pracuje výhradně v ``tests/.work``: fixtures se zkopírují, addon se doplní
z repa, Godot dostane vlastní konfigurační adresář (nesahá na tvoje
editor settings) a Blender běží s ``--factory-startup`` (bez tvých addonů).

Cesty k programům: ``--godot`` / ``$GODOT``, ``--blender`` / ``$BLENDER``,
jinak se hledají na PATH a ve standardních umístěních. Terrain3D se bere
z ``--terrain3d`` / ``$TERRAIN3D`` (adresář ``addons/terrain_3d``), jinak se
stáhne zafixovaná verze do ``tests/.cache``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
WORK = TESTS / ".work"
CACHE = TESTS / ".cache"
PROJECT = WORK / "project"
OUT = WORK / "out"
LOGS = WORK / "logs"
HOME = WORK / "home"

TERRAIN3D_VERSION = "v1.0.2-stable"
TERRAIN3D_URL = (
    "https://github.com/TokisanGames/Terrain3D/releases/download/"
    f"{TERRAIN3D_VERSION}/Terrain3D_{TERRAIN3D_VERSION}.zip"
)

SUITES = ("godot", "blender", "editor", "e2e", "gui")
WINDOWS = platform.system() == "Windows"


# ------------------------------------------------------------------ programy


def find_godot(explicit: str | None) -> str:
    for candidate in (explicit, os.environ.get("GODOT"), shutil.which("godot"), shutil.which("godot4")):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("Godot nenalezen: použij --godot nebo $GODOT")


def find_blender(explicit: str | None) -> str:
    candidates = [explicit, os.environ.get("BLENDER"), shutil.which("blender")]
    if WINDOWS:
        candidates += [
            r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
            r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
        ]
    else:
        candidates += [
            str(Path.home() / ".local/share/Steam/steamapps/common/Blender/blender"),
            "/var/lib/flatpak/exports/bin/org.blender.Blender",
        ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("Blender nenalezen: použij --blender nebo $BLENDER")


def find_terrain3d(explicit: str | None) -> Path | None:
    for candidate in (explicit, os.environ.get("TERRAIN3D")):
        if candidate:
            path = Path(candidate)
            if (path / "plugin.cfg").exists():
                return path
            sys.exit(f"{path} není adresář addons/terrain_3d")
    target = CACHE / TERRAIN3D_VERSION / "addons" / "terrain_3d"
    if (target / "plugin.cfg").exists():
        return target
    archive = CACHE / f"Terrain3D_{TERRAIN3D_VERSION}.zip"
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            print(f"… stahuji Terrain3D {TERRAIN3D_VERSION}")
            urllib.request.urlretrieve(TERRAIN3D_URL, archive)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                index = member.find("addons/terrain_3d/")
                if index < 0 or member.endswith("/"):
                    continue
                relative = member[index + len("addons/"):]
                destination = CACHE / TERRAIN3D_VERSION / "addons" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(bundle.read(member))
    except OSError as error:
        print(f"! Terrain3D se nepodařilo získat ({error}); testy terénu se přeskočí")
        return None
    return target if (target / "plugin.cfg").exists() else None


# ------------------------------------------------------------------- běhy


class Tools:
    def __init__(self, godot: str, blender: str, terrain3d: Path | None) -> None:
        self.godot = godot
        self.blender = blender
        self.terrain3d = terrain3d

    def godot_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Godot s vlastním domovem: editor settings, logy ani cache se
        nemíchají s tvým Godotem."""
        env = dict(os.environ)
        if WINDOWS:
            env["APPDATA"] = str(HOME / "appdata")
            env["LOCALAPPDATA"] = str(HOME / "localappdata")
        else:
            env["XDG_CONFIG_HOME"] = str(HOME / "config")
            env["XDG_DATA_HOME"] = str(HOME / "data")
            env["XDG_CACHE_HOME"] = str(HOME / "cache")
        env.update(extra or {})
        return env

    def run(self, name: str, command: list[str], timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        LOGS.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            result = subprocess.run(
                command, cwd=REPO, env=env, timeout=timeout,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
            )
            output = result.stdout
        except subprocess.TimeoutExpired as expired:
            output = (expired.stdout or "") if isinstance(expired.stdout, str) else ""
            output += f"\n!!! TIMEOUT po {timeout} s"
            result = subprocess.CompletedProcess(command, 124, output)
        (LOGS / f"{name}.log").write_text(
            f"$ {' '.join(command)}\n({time.monotonic() - started:.1f} s, kód {result.returncode})\n\n{output}",
            encoding="utf-8",
        )
        return result

    def godot_script(self, name: str, script: str, args: list[str], timeout: int = 300, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        command = [self.godot, "--headless", "--path", str(PROJECT), "--script", script, "--", *args]
        return self.run(name, command, timeout, self.godot_env(env))

    def godot_editor(self, name: str, scene: str, env: dict[str, str], timeout: int = 180) -> subprocess.CompletedProcess:
        command = [self.godot, "--headless", "--editor", "--path", str(PROJECT), scene]
        return self.run(name, command, timeout, self.godot_env(env))

    @staticmethod
    def blender_env(extra: dict[str, str] | None = None) -> dict[str, str]:
        """Blender s vlastním uživatelským adresářem: konfigurace ani odkaz na
        rozpracovanou úpravu se nemíchají s tvým Blenderem."""
        env = dict(os.environ)
        env["BLENDER_USER_RESOURCES"] = str(HOME / "blender")
        env.update(extra or {})
        return env

    def blender_script(self, name: str, script: Path, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
        command = [self.blender, "--background", "--factory-startup", "--python", str(script), "--", *args]
        return self.run(name, command, timeout, self.blender_env())


# ------------------------------------------------------------- příprava


def prepare(tools: Tools) -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    OUT.mkdir(parents=True)
    shutil.copytree(TESTS / "godot", PROJECT, ignore=shutil.ignore_patterns(".godot"))
    shutil.copytree(REPO / "addons" / "blender_bridge", PROJECT / "addons" / "blender_bridge")
    if tools.terrain3d is not None:
        _link_or_copy(tools.terrain3d, PROJECT / "addons" / "terrain_3d")
    else:
        settings = PROJECT / "project.godot"
        settings.write_text(
            settings.read_text(encoding="utf-8").replace('"res://addons/terrain_3d/plugin.cfg", ', ""),
            encoding="utf-8",
        )
    result = tools.run(
        "import",
        [tools.godot, "--headless", "--path", str(PROJECT), "--import"],
        timeout=600, env=tools.godot_env(),
    )
    if result.returncode != 0:
        sys.exit(f"Import testovacího projektu selhal, viz {LOGS / 'import.log'}")


def reset_fixtures() -> None:
    """Každá sada začíná s nedotčenými scénami a assety; .godot (importy)
    zůstává, assety se nemění."""
    shutil.copytree(TESTS / "godot" / "fixtures", PROJECT / "fixtures", dirs_exist_ok=True)
    for leftover in (PROJECT / "fixtures").rglob("*"):
        if leftover.suffix in (".blend", ".blend1", ".bbsrc"):
            leftover.unlink()
    pipeline = PROJECT / ".pipeline"
    if pipeline.exists():
        shutil.rmtree(pipeline)


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(source, target, target_is_directory=True)
    except OSError:
        shutil.copytree(source, target)


def fake_blender() -> Path:
    """Místo Blenderu zapíše argumenty, se kterými ho Godot spustil."""
    record = OUT / "fake_blender_args.txt"
    if WINDOWS:
        script = WORK / "fake_blender.bat"
        script.write_text(f'@echo off\r\n(for %%a in (%*) do @echo %%~a) > "{record}"\r\n', encoding="utf-8")
    else:
        script = WORK / "fake_blender.sh"
        script.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > "{record}"\n', encoding="utf-8")
        script.chmod(0o755)
    return script


# ------------------------------------------------------------------ sady


def results_from(path: Path, suite: str, log: str) -> list[dict]:
    if not path.exists():
        return [{"suite": suite, "name": "(sada nedoběhla)", "status": "fail", "message": f"viz {LOGS / log}"}]
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data:
        item.setdefault("suite", suite)
    return data


def suite_godot(tools: Tools) -> list[dict]:
    out = OUT / "godot.json"
    tools.godot_script("godot", "res://tests/runner.gd", ["--out", str(out)])
    return results_from(out, "godot", "godot.log")


def export_manifests(tools: Tools) -> None:
    tools.godot_script("export_manifests", "res://tests/tools/export_manifests.gd", [])


def suite_blender(tools: Tools) -> list[dict]:
    export_manifests(tools)
    out = OUT / "blender.json"
    tools.blender_script(
        "blender", TESTS / "blender" / "run.py",
        ["--repo", str(REPO), "--project", str(PROJECT), "--out", str(out)],
    )
    return results_from(out, "blender", "blender.log")


def suite_editor(tools: Tools) -> list[dict]:
    results: list[dict] = []
    env = {"BB_FAKE_BLENDER": str(fake_blender()), "BB_TEST_OUT": str(OUT)}
    phases = (
        ("open_and_watch", "basic"), ("restart", "basic"), ("context_menu", "basic"), ("reimport", "terrain"),
    )
    for phase, scene in phases:
        if phase == "restart":
            # Simulace práce v Blenderu, zatímco Godot neběžel.
            _move_in_manifest(PROJECT / ".pipeline" / "basic.json", "Crate", (9.0, 0.0, 3.0))
        out = OUT / f"editor_{phase}.json"
        tools.godot_editor(f"editor_{phase}", f"res://fixtures/scenes/{scene}.tscn",
                           {**env, "BB_TEST_EDITOR": phase})
        results += results_from(out, "editor", f"editor_{phase}.log")
    return results


def _move_in_manifest(path: Path, name: str, origin: tuple[float, float, float]) -> None:
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for item in manifest["nodes"]:
        if item.get("name") == name:
            item["xform"][9:12] = list(origin)
    path.write_text(json.dumps(manifest, indent="\t"), encoding="utf-8")


def suite_e2e(tools: Tools) -> list[dict]:
    results: list[dict] = []
    tools.godot_script("e2e_prepare", "res://tests/e2e/prepare.gd", ["--out", str(OUT)])
    results += results_from(OUT / "e2e_prepare.json", "e2e", "e2e_prepare.log")
    tools.blender_script(
        "e2e_blender", TESTS / "blender" / "e2e_edit.py",
        ["--repo", str(REPO), "--project", str(PROJECT), "--out", str(OUT)],
    )
    results += results_from(OUT / "e2e_blender.json", "e2e", "e2e_blender.log")
    tools.godot_script("e2e_verify", "res://tests/e2e/verify.gd", ["--out", str(OUT)])
    results += results_from(OUT / "e2e_verify.json", "e2e", "e2e_verify.log")
    return results


def _free_display() -> int:
    for number in range(97, 140):
        if not Path(f"/tmp/.X11-unix/X{number}").exists() and not Path(f"/tmp/.X{number}-lock").exists():
            return number
    raise RuntimeError("žádný volný X display")


def suite_gui(tools: Tools) -> list[dict]:
    if WINDOWS or shutil.which("Xvfb") is None:
        return [{"suite": "gui", "name": "Blender s oknem", "status": "skip",
                 "message": "potřebuje Xvfb (Linux)"}]
    export_manifests(tools)
    expression = (PROJECT / ".pipeline" / "startup_expr.py").read_text(encoding="utf-8")
    display = _free_display()
    server = subprocess.Popen(
        ["Xvfb", f":{display}", "-screen", "0", "1600x1000x24", "-ac", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.5)
        env = {k: v for k, v in tools.blender_env().items() if k not in ("WAYLAND_DISPLAY", "XAUTHORITY")}
        env["DISPLAY"] = f":{display}"
        tools.run("gui", [
            tools.blender, "--factory-startup", "--python-expr", expression,
            "--python", str(TESTS / "blender" / "gui_check.py"),
            "--", "--repo", str(REPO), "--project", str(PROJECT), "--out", str(OUT),
        ], timeout=240, env=env)
    finally:
        server.terminate()
        server.wait(timeout=10)
    return results_from(OUT / "gui.json", "gui", "gui.log")


RUNNERS = {"godot": suite_godot, "blender": suite_blender, "editor": suite_editor, "e2e": suite_e2e, "gui": suite_gui}


# ------------------------------------------------------------- fixtures


def regen_fixtures(tools: Tools) -> None:
    assets = TESTS / "godot" / "fixtures" / "assets"
    tools.blender_script("make_assets", TESTS / "fixtures" / "make_assets.py", [str(assets)])
    prepare(tools)
    result = tools.godot_script("generate", "res://fixtures/generate.gd", [])
    if "FIXTURES_OK" not in result.stdout:
        sys.exit(f"Generování scén selhalo, viz {LOGS / 'generate.log'}")
    # Zpátky do repa jdou scény, data terénu a .import soubory (stabilní uid).
    for relative in ("fixtures/scenes", "fixtures/terrain_data"):
        source = PROJECT / relative
        target = TESTS / "godot" / relative
        if target.exists():
            shutil.rmtree(target)
        if source.exists():
            shutil.copytree(source, target)
    for imported in (PROJECT / "fixtures" / "assets").glob("*.import"):
        shutil.copy2(imported, assets / imported.name)
    print("Fixtures přegenerovány.")


# ------------------------------------------------------------------ main


def report(results: list[dict]) -> int:
    width = max((len(r["name"]) for r in results), default=10)
    current = None
    for item in results:
        if item["suite"] != current:
            current = item["suite"]
            print(f"\n== {current}")
        mark = {"pass": "ok  ", "fail": "FAIL", "skip": "skip"}[item["status"]]
        message = f"  {item.get('message', '')}" if item["status"] != "pass" and item.get("message") else ""
        print(f"  {mark} {item['name']:<{width}}{message}")
    passed = sum(r["status"] == "pass" for r in results)
    failed = sum(r["status"] == "fail" for r in results)
    skipped = sum(r["status"] == "skip" for r in results)
    print(f"\n{passed} ok, {failed} selhání, {skipped} přeskočeno  (logy: {LOGS})")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--godot")
    parser.add_argument("--blender")
    parser.add_argument("--terrain3d")
    parser.add_argument("--only", choices=SUITES, action="append")
    parser.add_argument("--regen-fixtures", action="store_true")
    args = parser.parse_args()

    tools = Tools(find_godot(args.godot), find_blender(args.blender), find_terrain3d(args.terrain3d))
    if args.regen_fixtures:
        regen_fixtures(tools)
        return 0

    prepare(tools)
    results: list[dict] = []
    for suite in args.only or SUITES:
        reset_fixtures()
        results += RUNNERS[suite](tools)
    if tools.terrain3d is None:
        results.append({"suite": "prostředí", "name": "Terrain3D", "status": "skip",
                        "message": "nedostupný, testy terénu neběžely"})
    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
