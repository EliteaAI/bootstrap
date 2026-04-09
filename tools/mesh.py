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

""" Mesh """

from pylon.core.tools import log  # pylint: disable=E0611,E0401,W0611


def get_plugin_frozen_requirements(plugin_name):  # pylint: disable=R0912,R0914,R0915
    """ Mesh """
    log.info("Starting")
    #
    from tools import context  # pylint: disable=C0415,E0401
    #
    module_descriptor = context.module_manager.descriptors[plugin_name]
    #
    log.info("Module %s descriptor: %s", plugin_name, module_descriptor)
    #
    frozen_requirements = context.module_manager.freeze_site_requirements(
        target_site_base=module_descriptor.requirements_base,
    )
    #
    log.info("Done")
    #
    return frozen_requirements
