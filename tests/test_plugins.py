""" Tests for safe plugin update / repair helpers (#7761) """

import os
import json
import threading
import time
from types import SimpleNamespace

import pytest


def write_plugin(path, version="1.0", head=None, extra=None):
    os.makedirs(path, exist_ok=True)
    meta = {"name": os.path.basename(path), "version": version}
    if head:
        meta["git_head"] = head
    with open(os.path.join(path, "metadata.json"), "w") as f:
        json.dump(meta, f)
    for rel, content in (extra or {}).items():
        full = os.path.join(path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


# --- swap / recover ---------------------------------------------------------

def test_swap_replaces_and_preserves_ui(plugins_mod, tmp_path):
    plugins = tmp_path / "plugins"
    write_plugin(str(plugins / "core"), "1.0", extra={"static/ui/dist/index.html": "old-ui", "old.py": "x"})
    src = tmp_path / "src"
    write_plugin(str(src), "2.0", extra={"static/ui/dist/.gitkeep": "", "new.py": "y"})

    plugins_mod.swap_in(str(plugins), "core", str(src), ["static/ui/dist"])

    core = plugins / "core"
    assert json.load(open(core / "metadata.json"))["version"] == "2.0"
    assert (core / "new.py").exists() and not (core / "old.py").exists()
    # UI survives the update so the running platform keeps serving it
    assert (core / "static/ui/dist/index.html").read_text() == "old-ui"
    assert sorted(os.listdir(plugins)) == ["core"]


def test_carried_over_ui_is_tagged_with_old_version(plugins_mod, tmp_path):
    # Existing installs have no marker: tag the UI with the version it belongs to
    plugins = tmp_path / "plugins"
    write_plugin(str(plugins / "core"), "1.0", extra={"static/ui/dist/index.html": "ui"})
    src = tmp_path / "src"
    write_plugin(str(src), "2.0")

    plugins_mod.swap_in(str(plugins), "core", str(src), ["static/ui/dist"])
    assert (plugins / "core/static/ui/dist/.installed_for").read_text() == "carried over from 1.0"

    # An existing marker is carried over unchanged
    src2 = tmp_path / "src2"
    write_plugin(str(src2), "3.0")
    plugins_mod.swap_in(str(plugins), "core", str(src2), ["static/ui/dist"])
    assert (plugins / "core/static/ui/dist/.installed_for").read_text() == "carried over from 1.0"


def test_swap_rejects_source_without_metadata(plugins_mod, tmp_path):
    plugins = tmp_path / "plugins"
    write_plugin(str(plugins / "core"), "1.0")
    src = tmp_path / "src"
    os.makedirs(src / "x")  # broken clone: no metadata.json

    with pytest.raises(RuntimeError):
        plugins_mod.swap_in(str(plugins), "core", str(src), [])

    assert json.load(open(plugins / "core/metadata.json"))["version"] == "1.0"
    assert sorted(os.listdir(plugins)) == ["core"]


def test_recover_restores_old_after_crash_between_renames(plugins_mod, tmp_path):
    # Crash after `core` -> `.core.old` and before `.core.new` -> `core`
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    staging = tmp_path / ".plugins_staging"
    write_plugin(str(staging / ".core.old"), "1.0")
    write_plugin(str(staging / ".core.new"), "2.0")

    plugins_mod.recover_all(str(plugins))

    assert json.load(open(plugins / "core/metadata.json"))["version"] == "1.0"
    assert sorted(os.listdir(plugins)) == ["core"]
    assert os.listdir(staging) == []


def test_recover_drops_partial_new_copy(plugins_mod, tmp_path):
    # Crash during copytree into .core.new: live dir untouched
    plugins = tmp_path / "plugins"
    write_plugin(str(plugins / "core"), "1.0")
    os.makedirs(tmp_path / ".plugins_staging" / ".core.new" / "half")

    plugins_mod.recover_all(str(plugins))

    assert sorted(os.listdir(plugins)) == ["core"]
    assert os.listdir(tmp_path / ".plugins_staging") == []


def test_staging_is_not_inside_plugins_dir(plugins_mod, tmp_path):
    # pylon lists every dir in plugins/ as a plugin, dot-dirs included
    plugins = tmp_path / "plugins"
    write_plugin(str(plugins / "core"), "1.0")
    src = tmp_path / "src"
    write_plugin(str(src), "2.0")
    seen = []
    real_rename = os.rename

    def spy(a, b):
        seen.append(sorted(os.listdir(plugins)))
        real_rename(a, b)
    os.rename, orig = spy, os.rename
    try:
        plugins_mod.swap_in(str(plugins), "core", str(src), [])
    finally:
        os.rename = orig
    assert all(not n.startswith(".") for names in seen for n in names)


def test_swap_rolls_back_when_second_rename_fails(plugins_mod, tmp_path):
    plugins = tmp_path / "plugins"
    write_plugin(str(plugins / "core"), "1.0")
    src = tmp_path / "src"
    write_plugin(str(src), "2.0")
    real_rename = os.rename

    def flaky(a, b):
        if os.path.basename(a) == ".core.new":
            raise OSError("boom")
        real_rename(a, b)
    os.rename = flaky
    try:
        with pytest.raises(OSError):
            plugins_mod.swap_in(str(plugins), "core", str(src), [])
    finally:
        os.rename = real_rename
    assert json.load(open(plugins / "core/metadata.json"))["version"] == "1.0"


def test_preserved_paths_never_overwrite_new_files(plugins_mod, tmp_path):
    plugins = tmp_path / "plugins"
    write_plugin(str(plugins / "core"), "1.0", extra={
        "static/ui/dist/index.html": "OLD", "static/ui/dist/old.js": "old"})
    src = tmp_path / "src"
    write_plugin(str(src), "2.0", extra={"static/ui/dist/index.html": "NEW"})

    plugins_mod.swap_in(str(plugins), "core", str(src), ["static/ui/dist"])

    dist = plugins / "core/static/ui/dist"
    assert (dist / "index.html").read_text() == "NEW"
    assert (dist / "old.js").read_text() == "old"


def test_is_intact(plugins_mod, tmp_path):
    write_plugin(str(tmp_path / "ok"))
    os.makedirs(tmp_path / "empty")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "metadata.json").write_text("{not json")
    assert plugins_mod.is_intact(str(tmp_path / "ok"))
    assert not plugins_mod.is_intact(str(tmp_path / "empty"))
    assert not plugins_mod.is_intact(str(tmp_path / "bad"))


# --- install_plugin skip / force -------------------------------------------

class FakeSourceProvider:
    def __init__(self, src_dir):
        self.src_dir = src_dir
        self.calls = 0
        self.username = None
        self.password = None

    def get_source(self, _target):
        self.calls += 1
        return self.src_dir


class FakePluginsProvider:
    def __init__(self, path):
        self.path = path

    def plugin_exists(self, name):
        return os.path.exists(os.path.join(self.path, name))

    def get_plugin_metadata(self, name):
        try:
            return json.load(open(os.path.join(self.path, name, "metadata.json")))
        except Exception:  # pylint: disable=W0703
            return {}


def make_module(tmp_path, src_head, config=None):
    plugins = tmp_path / "plugins"
    src = tmp_path / "src"
    write_plugin(str(src), "2.0", head=src_head)
    source_provider = FakeSourceProvider(str(src))
    resolver = SimpleNamespace(
        resolve=lambda name: {
            "source": {"type": "git", "source": f"https://example.invalid/{name}.git", "branch": "main"},
            "objects": {"metadata": "x"},
        },
        get_source_provider=lambda name: source_provider,
    )
    module = SimpleNamespace(
        descriptor=SimpleNamespace(config=config or {}),
        repo_resolver=resolver,
        context=SimpleNamespace(module_manager=SimpleNamespace(
            providers={"plugins": FakePluginsProvider(str(plugins))},
        )),
    )
    return module, plugins, source_provider


def test_install_skips_when_head_unchanged(plugins_mod, tmp_path, monkeypatch):
    module, plugins, source_provider = make_module(tmp_path, "a" * 40)
    write_plugin(str(plugins / "core"), "1.0", head="a" * 40, extra={"static/ui/dist/index.html": "ui"})
    inode = os.stat(plugins / "core").st_ino
    monkeypatch.setattr(plugins_mod, "remote_head", lambda *_: "a" * 40)

    assert plugins_mod.install_plugin(module, "core") == "skipped"

    assert source_provider.calls == 0
    assert os.stat(plugins / "core").st_ino == inode
    assert (plugins / "core/static/ui/dist/index.html").exists()


def test_install_updates_when_head_changed(plugins_mod, tmp_path, monkeypatch):
    module, plugins, source_provider = make_module(tmp_path, "b" * 40)
    write_plugin(str(plugins / "core"), "1.0", head="a" * 40, extra={"static/ui/dist/index.html": "ui"})
    monkeypatch.setattr(plugins_mod, "remote_head", lambda *_: "b" * 40)

    assert plugins_mod.install_plugin(module, "core") == "updated"

    assert source_provider.calls == 1
    assert json.load(open(plugins / "core/metadata.json"))["version"] == "2.0"
    assert (plugins / "core/static/ui/dist/index.html").exists()


def test_force_redownloads_and_drops_ui(plugins_mod, tmp_path, monkeypatch):
    module, plugins, source_provider = make_module(tmp_path, "a" * 40)
    write_plugin(str(plugins / "core"), "1.0", head="a" * 40, extra={"static/ui/dist/index.html": "ui"})
    monkeypatch.setattr(plugins_mod, "remote_head", lambda *_: pytest.fail("force must not check"))

    assert plugins_mod.install_plugin(module, "core", force=True) == "updated"

    assert source_provider.calls == 1
    # Fresh UI is downloaded on next boot
    assert not (plugins / "core/static/ui/dist/index.html").exists()


def test_ls_remote_failure_falls_back_to_update(plugins_mod, tmp_path, monkeypatch):
    module, plugins, source_provider = make_module(tmp_path, "b" * 40)
    write_plugin(str(plugins / "core"), "1.0", head="a" * 40)

    def boom(*_):
        raise OSError("network")
    monkeypatch.setattr(plugins_mod, "remote_head", boom)

    assert plugins_mod.install_plugin(module, "core") == "updated"
    assert source_provider.calls == 1


def test_ensure_plugin_reclones_dir_without_metadata(plugins_mod, tmp_path, monkeypatch):
    module, plugins, source_provider = make_module(tmp_path, "a" * 40)
    os.makedirs(plugins / "core" / "leftover")  # like dev 2026-11-25: dir with no metadata.json

    assert plugins_mod.ensure_plugin(module, "core") == "updated"

    assert source_provider.calls == 1
    assert plugins_mod.is_intact(str(plugins / "core"))


def test_ensure_plugin_never_reclones_local_plugin(plugins_mod, tmp_path):
    module, plugins, source_provider = make_module(
        tmp_path, "a" * 40, config={"local_preordered_plugins": ["core"]})
    os.makedirs(plugins / "core")
    (plugins / "core" / "work_in_progress.py").write_text("x")

    assert plugins_mod.ensure_plugin(module, "core") == "exists"

    assert source_provider.calls == 0
    assert (plugins / "core" / "work_in_progress.py").exists()


def test_remote_head_skips_inline_ssh_key(plugins_mod, monkeypatch):
    import dulwich.porcelain as porcelain
    monkeypatch.setattr(porcelain, "ls_remote", lambda *a, **k: pytest.fail("must not be called"))
    prov = SimpleNamespace(branch="main", key_data="k")
    assert plugins_mod.remote_head(prov, {"source": "u"}) is None


def test_ensure_plugin_keeps_intact_dir(plugins_mod, tmp_path):
    module, plugins, source_provider = make_module(tmp_path, "a" * 40)
    write_plugin(str(plugins / "core"), "1.0", head="a" * 40)

    assert plugins_mod.ensure_plugin(module, "core") == "exists"
    assert source_provider.calls == 0


def test_remote_head_resolves_branch_and_tag(plugins_mod, monkeypatch):
    import dulwich.porcelain as porcelain
    refs = {
        b"refs/heads/main": b"1" * 40,
        b"refs/tags/v1": b"2" * 40,
        b"refs/tags/v1^{}": b"3" * 40,
        b"HEAD": b"4" * 40,
    }
    monkeypatch.setattr(porcelain, "ls_remote", lambda *a, **k: SimpleNamespace(refs=refs))
    prov = SimpleNamespace(branch="main", username=None, password=None, key_filename=None)
    assert plugins_mod.remote_head(prov, {"source": "u", "branch": "main"}) == "1" * 40
    # Annotated tag: compare with the peeled commit
    assert plugins_mod.remote_head(prov, {"source": "u", "branch": "v1"}) == "3" * 40
    # e.g. release "latest" with no such ref: clone checks out the default branch
    assert plugins_mod.remote_head(prov, {"source": "u", "branch": "latest"}) == "4" * 40
    assert plugins_mod.remote_head(prov, {"source": "u", "branch": "f" * 40}) == "f" * 40


# --- requirements repair ----------------------------------------------------

def make_dist(site, project, version, files, write_files=True):
    dist = site / f"{project}-{version}.dist-info"
    dist.mkdir(parents=True)
    rows = [f"{project}-{version}.dist-info/METADATA,,"] + [f"{f},sha256=x,1" for f in files]
    (dist / "RECORD").write_text("\n".join(rows) + "\n")
    if write_files:
        for f in files:
            (site / f).parent.mkdir(parents=True, exist_ok=True)
            (site / f).write_text("x")
    return dist


def test_repair_removes_orphan_dist_info_and_cache_meta(plugins_mod, tmp_path):
    req = tmp_path / "requirements"
    site = req / "elitea_core" / "lib" / "python3.12" / "site-packages"
    good = make_dist(site, "httpx", "0.28.1", ["httpx/__init__.py"])
    # Interrupted pip: dist-info written, package dir removed
    orphan = make_dist(site, "pathspec", "1.1.1", ["pathspec/__init__.py"], write_files=False)
    (req / "elitea_core.json").write_text('{"cache_hash": "abc"}')

    plugins_mod.repair_requirements(str(req), ["elitea_core"])

    assert good.exists() and not orphan.exists()
    # Cache hash dropped so pylon actually re-runs pip
    assert not (req / "elitea_core.json").exists()


def test_repair_does_not_loop_on_the_same_dist_info(plugins_mod, tmp_path):
    # e.g. files pruned after every install: repair once, then stop deleting
    req = tmp_path / "requirements"
    site = req / "p" / "lib" / "python3.12" / "site-packages"

    def broken():
        make_dist(site, "pkg", "1.0", ["pkg/__init__.py"], write_files=False)
        (req / "p.json").write_text("{}")

    broken()
    plugins_mod.repair_requirements(str(req), ["p"])
    assert not (site / "pkg-1.0.dist-info").exists() and not (req / "p.json").exists()

    broken()  # same breakage on the next boot
    plugins_mod.repair_requirements(str(req), ["p"])
    assert (site / "pkg-1.0.dist-info").exists() and (req / "p.json").exists()

    # Guard clears once nothing is broken
    (site / "pkg").mkdir()
    (site / "pkg" / "__init__.py").write_text("x")
    plugins_mod.repair_requirements(str(req), ["p"])
    assert not (req / "p.repaired").exists()


def test_repair_drops_stale_duplicate(plugins_mod, tmp_path):
    site = tmp_path / "site-packages"
    old = make_dist(site, "mcp", "1.28.1", ["mcp/__init__.py"])
    new = make_dist(site, "mcp", "1.30.0", ["mcp/__init__.py"])

    fixes = plugins_mod.repair_site_packages(str(site))

    assert new.exists() and not old.exists()
    assert fixes == [("mcp-1.28.1.dist-info", "stale duplicate dist-info", False)]


def test_duplicate_keeps_last_installed_not_highest(plugins_mod, tmp_path):
    site = tmp_path / "site-packages"
    newer_ver = make_dist(site, "elitea_sdk", "0.12.33", ["elitea_sdk/__init__.py"])
    synced = make_dist(site, "elitea_sdk", "0.12.5", ["elitea_sdk/__init__.py"])
    os.utime(newer_ver, (1, 1))  # older install

    plugins_mod.repair_site_packages(str(site))

    assert synced.exists() and not newer_ver.exists()


def test_duplicate_only_keeps_cache_meta(plugins_mod, tmp_path):
    # Stale duplicates need no reinstall; re-running pip could replace a locally synced package
    req = tmp_path / "requirements"
    site = req / "p" / "lib" / "python3.12" / "site-packages"
    make_dist(site, "elitea_sdk", "0.12.5", ["elitea_sdk/__init__.py"])
    make_dist(site, "elitea_sdk", "0.12.40", ["elitea_sdk/__init__.py"])
    (req / "p.json").write_text("{}")

    plugins_mod.repair_requirements(str(req), ["p"])

    assert (req / "p.json").exists()
    assert sorted(os.listdir(site))[-1] == "elitea_sdk-0.12.40.dist-info"


def test_repair_ignores_pycache_and_bin_and_keeps_cache_when_clean(plugins_mod, tmp_path):
    req = tmp_path / "requirements"
    site = req / "p" / "lib" / "python3.12" / "site-packages"
    dist = make_dist(site, "black", "26.10.1", ["black/__init__.py"])
    with open(dist / "RECORD", "a") as f:
        f.write("black/__pycache__/x.cpython-312.pyc,,\n../../../bin/black,sha256=x,1\n")
    (req / "p.json").write_text("{}")

    plugins_mod.repair_requirements(str(req), ["p"])

    assert dist.exists() and (req / "p.json").exists()


# --- restart waits for updates ---------------------------------------------

def test_wait_idle_blocks_until_update_finishes(plugins_mod):
    tracker = plugins_mod.UpdateTracker()
    done = []

    def update():
        with tracker:
            time.sleep(0.3)
            done.append("update")

    thread = threading.Thread(target=update)
    thread.start()
    time.sleep(0.05)
    assert tracker.wait_idle(5) is True
    done.append("restart")
    thread.join()
    assert done == ["update", "restart"]


def test_wait_idle_times_out(plugins_mod):
    tracker = plugins_mod.UpdateTracker()
    tracker.__enter__()
    started = time.monotonic()
    assert tracker.wait_idle(0.2) is False
    assert time.monotonic() - started < 1
    tracker.__exit__(None, None, None)
    assert tracker.wait_idle(0.1) is True
