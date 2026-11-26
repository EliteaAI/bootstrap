""" Load tools/plugins.py standalone with a stub pylon logger """

import sys
import types
import logging
import importlib.util
from pathlib import Path

import pytest


def _install_pylon_stub():
    if "pylon.core.tools" in sys.modules:
        return
    tools = types.ModuleType("pylon.core.tools")
    tools.log = logging.getLogger("bootstrap-tests")
    for name, mod in {
        "pylon": types.ModuleType("pylon"),
        "pylon.core": types.ModuleType("pylon.core"),
        "pylon.core.tools": tools,
    }.items():
        sys.modules[name] = mod


@pytest.fixture(scope="session")
def plugins_mod():
    _install_pylon_stub()
    path = Path(__file__).resolve().parents[1] / "tools" / "plugins.py"
    spec = importlib.util.spec_from_file_location("bootstrap_tools_plugins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
