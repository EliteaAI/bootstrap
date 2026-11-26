#!/usr/bin/python3
# coding=utf-8

#   Copyright 2026 EPAM Systems
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

""" Safe plugin install / update / repair helpers """

import os
import re
import csv
import glob
import json
import time
import shutil
import threading

from pylon.core.tools import log  # pylint: disable=E0611,E0401


METADATA_FILE = "metadata.json"
DEFAULT_PRESERVE_PATHS = ["static/ui/dist"]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class UpdateTracker:
    """ Counts in-flight plugin updates so restart can wait for them """

    def __init__(self):
        self.count = 0
        self.condition = threading.Condition()

    def __enter__(self):
        with self.condition:
            self.count += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        with self.condition:
            self.count -= 1
            self.condition.notify_all()

    def wait_idle(self, timeout):
        """ Wait until no updates run; returns False on timeout """
        deadline = time.monotonic() + timeout
        with self.condition:
            if self.count:
                log.info("Restart: waiting for %s plugin update(s) to finish", self.count)
            while self.count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.warning("Restart: %s plugin update(s) still running after %ss, restarting anyway", self.count, timeout)  # pylint: disable=C0301
                    return False
                self.condition.wait(remaining)
        return True


updates = UpdateTracker()


def is_intact(path):
    """ Plugin dir is usable only with a parseable metadata.json """
    try:
        with open(os.path.join(path, METADATA_FILE), "rb") as file:
            return isinstance(json.load(file), dict)
    except:  # pylint: disable=W0702
        return False


def installed_head(plugins_path, plugin):
    """ git_head recorded in the installed plugin metadata """
    try:
        with open(os.path.join(plugins_path, plugin, METADATA_FILE), "rb") as file:
            return json.load(file).get("git_head", None)
    except:  # pylint: disable=W0702
        return None


def remote_head(source_provider, source_target):
    """ Commit the source would check out, via ls-remote; None if unknown """
    from dulwich import porcelain  # pylint: disable=E0401,C0415
    #
    branch = source_target.get("branch", getattr(source_provider, "branch", "main")) or "main"
    if SHA_RE.match(branch):
        return branch
    #
    if source_target.get("key_data") or getattr(source_provider, "key_data", None):
        return None  # ls-remote cannot use inline SSH keys; caller falls back to a normal update
    #
    auth = {}
    for key in ["username", "password", "key_filename"]:
        value = source_target.get(key, getattr(source_provider, key, None))
        if value:
            auth[key] = value
    #
    refs = porcelain.ls_remote(source_target["source"], include_tags=True, **auth).refs
    # Unknown branch: pylon's clone falls back to the default branch, so compare with HEAD
    for ref in [f"refs/heads/{branch}", f"refs/tags/{branch}^{{}}", f"refs/tags/{branch}", "HEAD"]:
        value = refs.get(ref.encode("utf-8"), None)
        if value is not None:
            return value.decode("utf-8")
    return None


def staging_path(plugins_path):
    """ Staging dir beside plugins/ (pylon lists every dir in plugins/ as a plugin) """
    staging = os.path.join(os.path.dirname(os.path.abspath(plugins_path)), ".plugins_staging")
    os.makedirs(staging, exist_ok=True)
    # Renames must stay on one filesystem
    if os.stat(staging).st_dev != os.stat(plugins_path).st_dev:
        return plugins_path
    return staging


def recover(plugins_path, plugin):
    """ Finish or roll back a swap interrupted by a crash or restart """
    target = os.path.join(plugins_path, plugin)
    staging = staging_path(plugins_path)
    old_path = os.path.join(staging, f".{plugin}.old")
    #
    if not os.path.exists(target) and os.path.isdir(old_path):
        os.rename(old_path, target)
        log.warning("%s: restored previous version after interrupted update", plugin)
    #
    for leftover in [os.path.join(staging, f".{plugin}.new"), old_path]:
        if os.path.exists(leftover):
            shutil.rmtree(leftover, ignore_errors=True)
            log.info("%s: removed leftover %s", plugin, os.path.basename(leftover))


def recover_all(plugins_path):
    """ Boot: recover every plugin with a swap leftover, not only preordered ones """
    staging = staging_path(plugins_path)
    names = {item[1:].rsplit(".", 1)[0] for item in os.listdir(staging) if item.startswith(".") and item.endswith((".new", ".old"))}
    for plugin in sorted(names):
        recover(plugins_path, plugin)


def _copy_missing(src, dst):
    if not os.path.exists(dst):
        shutil.copy2(src, dst)


def swap_in(plugins_path, plugin, source, preserve_paths):
    """ Copy beside the live dir, verify, then swap with two renames """
    target = os.path.join(plugins_path, plugin)
    staging = staging_path(plugins_path)
    new_path = os.path.join(staging, f".{plugin}.new")
    old_path = os.path.join(staging, f".{plugin}.old")
    #
    recover(plugins_path, plugin)
    shutil.copytree(source, new_path, symlinks=True)
    #
    if not is_intact(new_path):
        shutil.rmtree(new_path, ignore_errors=True)
        raise RuntimeError(f"{plugin}: new version has no valid {METADATA_FILE}, keeping current")
    #
    for rel_path in preserve_paths:
        src = os.path.join(target, rel_path)
        if os.path.isdir(src):
            # Never overwrite what the new version ships
            shutil.copytree(
                src, os.path.join(new_path, rel_path), symlinks=True, dirs_exist_ok=True,
                copy_function=_copy_missing,
            )
    #
    if os.path.exists(target):
        os.rename(target, old_path)
    try:
        os.rename(new_path, target)
    except:  # pylint: disable=W0702
        if os.path.exists(old_path) and not os.path.exists(target):
            os.rename(old_path, target)
        raise
    shutil.rmtree(old_path, ignore_errors=True)


def install_plugin(module, plugin, force=False, preserve_paths=None):  # pylint: disable=R0911,R0914
    """ Install / update one plugin; returns installed, updated, skipped or None on error """
    resolver = module.repo_resolver
    plugins_provider = module.context.module_manager.providers["plugins"]
    plugins_path = getattr(plugins_provider, "path", None)
    exists = plugins_provider.plugin_exists(plugin)
    #
    plugin_info = resolver.resolve(plugin)
    if plugin_info is None:
        log.error("%s: plugin is not known by repo resolver(s)", plugin)
        return None
    #
    source_target = plugin_info["source"].copy()
    source_type = source_target.pop("type")
    if source_type not in ["git", "http_tar", "http_zip"]:
        log.error("%s: plugin source type is not supported: %s", plugin, source_type)
        return None
    #
    source_provider = resolver.get_source_provider(plugin)
    current_head = installed_head(plugins_path, plugin) if plugins_path else None
    #
    if exists and not force and source_type == "git" and not current_head:
        log.info("%s: no git_head in metadata (add_head_data off?), cannot skip unchanged", plugin)
    #
    if exists and not force and source_type == "git" and current_head:
        try:
            target_head = remote_head(source_provider, source_target)
        except:  # pylint: disable=W0702
            log.exception("%s: ls-remote failed, updating without skip check", plugin)
            target_head = None
        #
        if target_head == current_head:
            log.info("%s: already at %s, skipping", plugin, current_head[:7])
            return "skipped"
    #
    started = time.monotonic()
    old_version = plugins_provider.get_plugin_metadata(plugin).get("version", "-") if exists else "-"
    action = "Redownloading" if force else ("Updating" if exists else "Installing")
    log.info("%s %s (installed: %s)", action, plugin, old_version)
    #
    source = source_provider.get_source(source_target)
    #
    if plugins_path is None:
        plugins_provider.add_plugin(plugin, source)
    else:
        if preserve_paths is None:
            preserve_paths = DEFAULT_PRESERVE_PATHS
        swap_in(plugins_path, plugin, source, [] if force else preserve_paths)
    #
    new_metadata = plugins_provider.get_plugin_metadata(plugin) or {}
    log.info(
        "%s: %s %s -> %s (%s) in %.1fs", plugin, "installed" if not exists else "updated",
        old_version, new_metadata.get("version", "-"),
        str(new_metadata.get("git_head", "-"))[:7], time.monotonic() - started,
    )
    return "updated" if exists else "installed"


def ensure_plugin(module, plugin):
    """ Boot check: re-clone a resolver-managed dir without metadata.json """
    plugins_provider = module.context.module_manager.providers["plugins"]
    plugins_path = getattr(plugins_provider, "path", None)
    #
    if plugins_path is not None:
        target = os.path.join(plugins_path, plugin)
        if os.path.exists(target) and not is_intact(target):
            config = module.descriptor.config
            if plugin in [*config.get("local_preordered_plugins", []), *config.get("customer_preordered_plugins", [])]:
                log.error("%s: %s missing or invalid in a local/customer plugin, not re-cloning", plugin, METADATA_FILE)  # pylint: disable=C0301
                return "exists"
            log.warning("%s: %s missing or invalid, re-cloning", plugin, METADATA_FILE)
            return install_plugin(module, plugin, force=True)
    #
    if plugins_provider.plugin_exists(plugin):
        log.info("Plugin %s already exists", plugin)
        return "exists"
    #
    return install_plugin(module, plugin)


def _record_paths(dist_info):
    try:
        with open(os.path.join(dist_info, "RECORD"), newline="", encoding="utf-8") as file:
            return [row[0] for row in csv.reader(file) if row]
    except:  # pylint: disable=W0702
        return None


def _is_broken(site_packages, dist_info):
    """ First file missing from RECORD (interrupted pip --target), else None """
    paths = _record_paths(dist_info)
    if not paths:
        return False
    own = os.path.basename(dist_info) + "/"
    for rel_path in paths:
        if rel_path.startswith(own) or rel_path.startswith("..") or "__pycache__" in rel_path:
            continue
        if not os.path.exists(os.path.join(site_packages, rel_path)):
            return rel_path
    return None


def _project_key(dist_info_name):
    name = dist_info_name[:-len(".dist-info")].rsplit("-", 1)
    return re.sub(r"[-_.]+", "_", name[0]).lower(), (name[1] if len(name) > 1 else "0")


def _version_key(version):
    try:
        from packaging.version import Version  # pylint: disable=E0401,C0415
        return (1, Version(version))
    except:  # pylint: disable=W0702
        return (0, version)


def repair_site_packages(site_packages):
    """ Drop broken and duplicate dist-info; returns (name, reason, needs_reinstall) """
    fixes = []
    dist_infos = sorted(glob.glob(os.path.join(site_packages, "*.dist-info")))
    #
    by_project = {}
    for dist_info in dist_infos:
        key, version = _project_key(os.path.basename(dist_info))
        by_project.setdefault(key, []).append((version, dist_info))
    #
    for items in by_project.values():
        if len(items) < 2:
            continue
        # Last written = last installed by pip, even if a stale one has a higher version
        items.sort(key=lambda item: (os.path.getmtime(item[1]), _version_key(item[0])))
        for _, stale in items[:-1]:
            shutil.rmtree(stale, ignore_errors=True)
            fixes.append((os.path.basename(stale), "stale duplicate dist-info", False))
    #
    for dist_info in dist_infos:
        missing = _is_broken(site_packages, dist_info) if os.path.isdir(dist_info) else None
        if missing:
            shutil.rmtree(dist_info, ignore_errors=True)
            fixes.append((os.path.basename(dist_info), f"{missing} missing, will reinstall", True))
    #
    return fixes


def repair_requirements(requirements_path, plugins):
    """ Repair site-packages of the given plugins before pip runs """
    for plugin in plugins:
        pattern = os.path.join(requirements_path, plugin, "lib", "python*", "site-packages")
        reinstall = False
        for site_packages in glob.glob(pattern):
            for name, reason, needs_reinstall in repair_site_packages(site_packages):
                log.warning("%s requirements: %s: %s", plugin, name, reason)
                reinstall = reinstall or needs_reinstall
        # Pylon skips pip while the cached requirements hash matches
        cache_meta = os.path.join(requirements_path, f"{plugin}.json")
        if reinstall and os.path.exists(cache_meta):
            os.remove(cache_meta)
