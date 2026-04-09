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

""" Event """

import logging

from pylon.core.tools import log, web, profiling  # pylint: disable=E0611,E0401

from ..tools.logs import LocalListLogHandler
from ..tools.tasks import wait_for_tasks


class Event:  # pylint: disable=R0903,E1101
    """ Event """

    @web.event("bootstrap_runtime_update")
    def _bootstrap_runtime_update(self, context, event, payload):  # pylint: disable=R0914,R0912,R0915
        _ = context, event
        #
        if not isinstance(payload, dict):
            return
        #
        if self.context.id != payload.get("pylon_id", ""):
            return
        #
        module_manager = self.context.module_manager
        plugins_provider = module_manager.providers["plugins"]
        requirements_provider = module_manager.providers["requirements"]
        repo_resolver = self.repo_resolver
        #
        pycache_path = self.context.settings.get(
            "modules", {}
        ).get(
            "plugins", {}
        ).get(
            "pycache", None
        )
        #
        def _delete_pycache():
            if pycache_path is not None:
                import os  # pylint: disable=C0415
                import shutil  # pylint: disable=C0415
                #
                try:
                    if os.path.isdir(pycache_path):
                        shutil.rmtree(pycache_path)
                    else:
                        os.remove(pycache_path)
                except:  # pylint: disable=W0702
                    pass
        #
        for plugin in payload.get("plugins", []):
            if plugin.startswith("!"):
                plugin = plugin.lstrip("!")
                log.info("Deleting plugin: %s", plugin)
                #
                if plugins_provider.plugin_exists(plugin):
                    plugins_provider.delete_plugin(plugin)
                #
                requirements_provider.delete_requirements(plugin)
                #
                _delete_pycache()
                #
                try:
                    from pylon.core.tools.module import state  # pylint: disable=E0611,E0401,C0415
                    #
                    plugin_state = state.get(plugin)
                    plugin_state["installed"] = False
                    state.set(plugin, plugin_state)
                except:  # pylint: disable=W0702
                    pass
            else:
                if plugins_provider.plugin_exists(plugin):
                    log.info("Updating plugin: %s", plugin)
                else:
                    log.info("Installing plugin: %s", plugin)
                #
                plugin_info = repo_resolver.resolve(plugin)
                #
                if plugin_info is None:
                    log.error("Plugin is not known by repo resolver(s)")
                    continue
                #
                metadata_provider = repo_resolver.get_metadata_provider(plugin)
                #
                metadata_url = plugin_info["objects"]["metadata"]
                metadata = metadata_provider.get_metadata({"source": metadata_url})
                #
                source_target = plugin_info["source"].copy()
                source_type = source_target.pop("type")
                #
                if source_type not in ["git", "http_tar", "http_zip"]:
                    log.error("Plugin source type is not supported: %s", source_type)
                    continue
                #
                source_provider = repo_resolver.get_source_provider(plugin)
                source = source_provider.get_source(source_target)
                #
                plugins_provider.add_plugin(plugin, source)
                #
                try:
                    from pylon.core.tools.module import state  # pylint: disable=E0611,E0401,C0415
                    #
                    plugin_state = state.get(plugin)
                    plugin_state["installed"] = False
                    state.set(plugin, plugin_state)
                except:  # pylint: disable=W0702
                    pass
                #
                log.info("Plugin updated to version %s", metadata.get("version", "0.0.0"))
        #
        for plugin, config in payload.get("configs", {}).items():
            log.info("Updating config: %s", plugin)
            config_data = config.encode()
            #
            module_manager.providers["config"].add_config_data(plugin, config_data)
            #
            if plugin in module_manager.descriptors:
                descriptor = module_manager.descriptors[plugin]
                descriptor.load_config()
                #
                try:
                    if descriptor.module is not None:
                        descriptor.module.reconfig()
                except:  # pylint: disable=W0702
                    pass
        #
        for action in payload.get("actions", []):
            if not isinstance(action, str):
                action, data = action
            #
            if action == "enable_debug_mode":
                log.info("Enabling debug mode")
                #
                if self.log_handler is None:  # pylint: disable=E0203
                    logging.root.setLevel(logging.DEBUG)
                    #
                    self.log_handler = LocalListLogHandler(  # pylint: disable=W0201
                        target_list=self.log_buffer,  # pylint: disable=E0203
                    )
                    self.log_handler.setFormatter(log.state.formatter)
                    #
                    logging.getLogger("").addHandler(self.log_handler)
            #
            elif action == "disable_debug_mode":
                log.info("Disabling debug mode")
                #
                if self.log_handler is not None:  # pylint: disable=E0203
                    logging.getLogger("").removeHandler(self.log_handler)
                    #
                    self.log_handler.flush()
                    self.log_handler.close()
                    self.log_handler = None  # pylint: disable=W0201
                    #
                    logging.root.setLevel(logging.INFO)
                    #
                    self.log_buffer = []  # pylint: disable=W0201
            #
            elif action == "enable_profiling":
                log.info("Enabling profiling")
                #
                if "stage" not in self.context.profiling:
                    self.context.profiling["stage"] = {}
                #
                self.context.profiling["stage"]["ondemand"] = True
                profiling.profiling_start(self.context, "ondemand")
            #
            elif action == "disable_profiling":
                log.info("Disabling profiling")
                #
                if self.context.profiling.get("stage", {}).get("ondemand", False):
                    profiling.profiling_stop(self.context, "ondemand")
                    self.context.profiling["stage"]["ondemand"] = False
            #
            elif action == "enable_splash":
                log.info("Enabling maintenance splash")
                #
                try:
                    self.descriptor.state["splash_enabled"] = True
                    self.descriptor.save_state()
                except:  # pylint: disable=W0702
                    log.exception("Skipping state exception")
                #
                if self.context.web_runtime == "gevent":
                    from ..tools.splash import maintenance_splash_hook  # pylint: disable=C0415
                    #
                    try:
                        if maintenance_splash_hook not in self.context.root_router.hooks:
                            self.context.root_router.hooks.append(maintenance_splash_hook)
                    except:  # pylint: disable=W0702
                        log.exception("Skipping exception")
            #
            elif action == "disable_splash":
                log.info("Disabling maintenance splash")
                #
                try:
                    self.descriptor.state["splash_enabled"] = False
                    self.descriptor.save_state()
                except:  # pylint: disable=W0702
                    log.exception("Skipping state exception")
                #
                if self.context.web_runtime == "gevent":
                    from ..tools.splash import maintenance_splash_hook  # pylint: disable=C0415
                    #
                    try:
                        if maintenance_splash_hook in self.context.root_router.hooks:
                            self.context.root_router.hooks.remove(maintenance_splash_hook)
                    except:  # pylint: disable=W0702
                        log.exception("Skipping exception")
            #
            elif action == "delete_requirements":
                for plugin in data:
                    log.info("Deleting requirements: %s", plugin)
                    #
                    requirements_provider.delete_requirements(plugin)
                    #
                    _delete_pycache()
            #
            elif action == "update_pylon_config":
                log.info("Updating pylon config")
                #
                try:
                    from pylon.core.tools import config  # pylint: disable=E0611,E0401,C0415
                    #
                    encoded_data = data.encode()
                    config.tunable_set("pylon_settings", encoded_data)
                    self.context.settings_data = encoded_data
                except:  # pylint: disable=W0702
                    log.exception("Skipping exception")
        #
        reload_plugins = payload.get("reload", [])
        #
        if reload_plugins:
            for plugin in module_manager.load_order:
                if plugin in reload_plugins:
                    log.info("Requesting plugin reload: %s", plugin)
                    #
                    self.context.manager.reload_plugin(plugin)
            #
            log.info("All reloads done")
        #
        if payload.get("restart", True):
            try:
                wait_for_tasks(self)
            except:  # pylint: disable=W0702
                pass
            #
            try:
                from pylon.core.tools.server import restart
            except:  # pylint: disable=W0702
                log.exception("Failed to import server restart, using bootstrap fallback")
                #
                import os  # pylint: disable=C0415
                import subprocess  # pylint: disable=C0415
                #
                pylon_pid = payload.get("pylon_pid", os.getpid())
                #
                log.info("Restarting pylon (pid = %s)", pylon_pid)
                subprocess.Popen(  # pylint: disable=R1732
                        ["/bin/bash", "-c", f"bash -c 'sleep 1; kill {pylon_pid}' &"]
                )
            else:
                log.info("Restarting via server restart")
                restart()
