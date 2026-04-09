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

import os
import json
import time
import threading

from pylon.core.tools import log  # pylint: disable=E0611,E0401
from pylon.core.tools import config as pylon_config  # pylint: disable=E0611,E0401


class RuntimeAnnoucer(threading.Thread):  # pylint: disable=R0903
    """ Announce about runtime config periodically """

    def __init__(self, module, config):
        super().__init__(daemon=True)
        self.module = module
        self.config = config
        self.interval = self.config.get("announce_interval", 15)
        self.last_announce = time.time()

    def _collect_info(self):
        result = []
        module_manager = self.module.context.module_manager
        #
        for descriptor in module_manager.descriptors.values():
            result.append({
                "name": descriptor.name,
                "description": descriptor.metadata.get("name", ""),
                "prepared": descriptor.prepared,
                "activated": descriptor.activated,
                "local_version": descriptor.metadata.get("version", "0.0.0"),
                "repo_version": "-",
                "metadata": descriptor.metadata,
                "config": descriptor.config,
            })
            #
            try:
                result[-1]["config_data"] = descriptor.config_data.decode()
            except:  # pylint: disable=W0702
                pass
            #
            try:
                schema_path = os.path.join(descriptor.path, "admin_schema.json")
                if os.path.isfile(schema_path):
                    with open(schema_path, "r", encoding="utf-8") as f:
                        result[-1]["admin_schema"] = json.load(f)
            except:  # pylint: disable=W0702
                pass
        #
        return result

    def _collect_pylon_settings(self):
        result = {}
        #
        result["active"] = self.module.context.settings
        #
        try:
            result["tunable"] = self.module.context.settings_data.decode()
        except:  # pylint: disable=W0702
            try:
                result["tunable"] = pylon_config.tunable_get("pylon_settings", None).decode()
            except:  # pylint: disable=W0702
                result["tunable"] = ""
        #
        return result

    def run(self):
        """ Run thread """
        while not self.module.stop_event.is_set():
            try:
                time.sleep(1)
                now = time.time()
                if now - self.last_announce >= self.interval:
                    self.last_announce = now
                    self.module.context.event_manager.fire_event(
                        "bootstrap_runtime_info",
                        {
                            "pylon_id": self.module.context.id,
                            "pylon_settings": self._collect_pylon_settings(),
                            "runtime_info": self._collect_info(),
                            "logs": self.module.log_buffer.copy(),
                        },
                    )
            except:  # pylint: disable=W0702
                log.exception("Exception in announcer thread, continuing")
