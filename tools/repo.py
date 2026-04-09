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

""" Repo tools """

import json
import importlib

from pylon.core.tools import log  # pylint: disable=E0611,E0401,W0611


class RepoResolver:
    """ Repo resolver """

    def __init__(self, module, repo_config):
        self.module = module
        self.repo_config = self._expand_meta_repos(repo_config)
        #
        self.sub_resolvers = []
        #
        self.metadata_provider = None
        self.source_provider = None
        #
        self.lookup = self._local_lookup
        self.lookup_data = None

    def _expand_meta_repos(self, repo_config):  # pylint: disable=R0914
        if not isinstance(repo_config, dict):
            return repo_config
        #
        repo_type = repo_config.get("type", "unknown")
        #
        if repo_type == "repo_depot":
            config = repo_config.copy()
            #
            release = config.get("release", "main")
            license_token = config.get("license_token", None)
            repo_url = config.get("repo_url", "https://repo.elitea.ai/target")
            #
            repo_url_base = repo_url.rstrip("/")
            #
            if license_token is not None:
                depot_url = repo_url
                provider_auth = {
                    "username": license_token,
                    "password": "",
                }
            else:
                depot_url = f"{repo_url_base}/public"
                provider_auth = {}
            #
            result = []
            #
            result.append({
                "type": "depot",
                "url": depot_url,
                "group": release,
                "metadata_provider": {
                    "type": "pylon.core.providers.metadata.http",
                    **provider_auth,
                },
                "source_provider": {
                    "type": "pylon.core.providers.source.http_tar",
                    **provider_auth,
                },
            })
            #
            if hasattr(self.module.context.module_manager, "setting_overrides"):
                if license_token is not None:
                    repo_url_base = repo_url_base.replace("://", f"://{license_token}@")
                else:
                    repo_url_base = f"{repo_url_base}/public"
                #
                index_url = f"{repo_url_base}/simple/{release}/"
                #
                setting_overrides = {
                    "requirements.index_url": index_url,
                    "requirements.extra_index_url": None,
                    "requirements.no_index": False,
                    "requirements.find_links": None,
                    "requirements.require_hashes": False,
                }
                #
                for o_key, o_value in setting_overrides.items():
                    self.module.context.module_manager.setting_overrides[o_key] = o_value
            #
            return result
        #
        if repo_type == "elitea_github":
            config = repo_config.copy()
            #
            release = config.get("release", "main")
            license_username = config.get("license_username", None)
            license_password = config.get("license_password", None)
            add_source_data = config.get("add_source_data", False)
            add_head_data = config.get("add_head_data", False)
            #
            result = []
            #
            result.append({
                "type": "github",
                "namespace": "EliteaAI",
                "branch": release,
                "metadata_provider": {
                    "type": "pylon.core.providers.metadata.http",
                    "username": license_username,
                    "password": license_password,
                },
                "source_provider": {
                    "type": "pylon.core.providers.source.git",
                    "delete_git_dir": False,
                    "add_source_data": add_source_data,
                    "add_head_data": add_head_data,
                    "branch": release,
                    "depth": None,
                    "username": license_username,
                    "password": license_password,
                },
            })
            #
            return result
        #
        return repo_config

    def _local_lookup(self, plugin):
        if self.lookup_data is None:
            return None
        #
        return self.lookup_data.get(plugin, None)

    def _depot_lookup(self, plugin):
        url = self.repo_config.get("url", None)
        group = self.repo_config.get("group", None)
        #
        if url is None or group is None:
            return None
        #
        url = url.rstrip("/")
        #
        # Target
        #
        try:
            metadata_url = f"{url}/depot/{group}/plugins/{plugin}/metadata"
            #
            self.metadata_provider.get_metadata({"source": metadata_url})
            #
            return {
                "source": {
                    "type": "http_tar",
                    "source": f"{url}/depot/{group}/plugins/{plugin}/source",
                },
                "objects": {
                    "metadata": metadata_url
                }
            }
        except:  # pylint: disable=W0702
            pass
        #
        # Not found
        #
        return None

    def _github_lookup(self, plugin):
        whitelist = self.repo_config.get("whitelist", None)
        if whitelist is not None and plugin not in whitelist:
            return None
        #
        namespace = self.repo_config.get("namespace", None)
        branch = self.repo_config.get("branch", "main")
        file = self.repo_config.get("metadata_file", "metadata.json")
        #
        if namespace is None:
            return None
        #
        metadata_url = f"https://raw.githubusercontent.com/{namespace}/{plugin}/{branch}/{file}"
        try:
            self.metadata_provider.get_metadata({"source": metadata_url})
        except:  # pylint: disable=W0702
            return None
        #
        return {
            "source": {
                "type": "git",
                "source": f"https://github.com/{namespace}/{plugin}.git",
                "branch": branch
            },
            "objects": {
                "metadata": metadata_url
            }
        }

    def _github_zip_lookup(self, plugin):
        whitelist = self.repo_config.get("whitelist", None)
        if whitelist is not None and plugin not in whitelist:
            return None
        #
        namespace = self.repo_config.get("namespace", None)
        branch = self.repo_config.get("branch", "main")
        ref_type = self.repo_config.get("ref_type", "heads")
        file = self.repo_config.get("metadata_file", "metadata.json")
        #
        if namespace is None:
            return None
        #
        metadata_url = f"https://raw.githubusercontent.com/{namespace}/{plugin}/{branch}/{file}"
        try:
            self.metadata_provider.get_metadata({"source": metadata_url})
        except:  # pylint: disable=W0702
            return None
        #
        return {
            "source": {
                "type": "http_zip",
                "source": f"https://codeload.github.com/{namespace}/{plugin}/zip/refs/{ref_type}/{branch}",  # pylint: disable=C0301
            },
            "objects": {
                "metadata": metadata_url
            }
        }

    def _github_tar_lookup(self, plugin):
        whitelist = self.repo_config.get("whitelist", None)
        if whitelist is not None and plugin not in whitelist:
            return None
        #
        namespace = self.repo_config.get("namespace", None)
        branch = self.repo_config.get("branch", "main")
        ref_type = self.repo_config.get("ref_type", "heads")
        file = self.repo_config.get("metadata_file", "metadata.json")
        #
        if namespace is None:
            return None
        #
        metadata_url = f"https://raw.githubusercontent.com/{namespace}/{plugin}/{branch}/{file}"
        try:
            self.metadata_provider.get_metadata({"source": metadata_url})
        except:  # pylint: disable=W0702
            return None
        #
        return {
            "source": {
                "type": "http_tar",
                "source": f"https://codeload.github.com/{namespace}/{plugin}/tar.gz/refs/{ref_type}/{branch}",  # pylint: disable=C0301
            },
            "objects": {
                "metadata": metadata_url
            }
        }

    def _gogs_lookup(self, plugin):
        whitelist = self.repo_config.get("whitelist", None)
        if whitelist is not None and plugin not in whitelist:
            return None
        #
        base_url = self.repo_config.get("base_url", None)
        branch = self.repo_config.get("branch", "main")
        file = self.repo_config.get("metadata_file", "metadata.json")
        #
        if base_url is None:
            return None
        #
        base_url = base_url.rstrip("/")
        #
        metadata_url = f"{base_url}/{plugin}/raw/{branch}/{file}"
        try:
            self.metadata_provider.get_metadata({"source": metadata_url})
        except:  # pylint: disable=W0702
            return None
        #
        return {
            "source": {
                "type": "git",
                "source": f"{base_url}/{plugin}.git",
                "branch": branch
            },
            "objects": {
                "metadata": metadata_url
            }
        }

    def init(self):  # pylint: disable=R0912
        """ Init resolver """
        if isinstance(self.repo_config, list):
            for config in self.repo_config:
                sub_resolver = RepoResolver(self.module, config)
                sub_resolver.init()
                self.sub_resolvers.append(sub_resolver)
            #
            return
        #
        repo_type = self.repo_config.get("type", "unknown")
        #
        if repo_type == "resource":
            log.info("Loading plugin repository from resource: %s", self.repo_config["name"])
            self.lookup_data = json.loads(
                self.module.descriptor.loader.get_data(self.repo_config["name"])
            )
        #
        elif repo_type == "config":
            log.info("Loading plugin repository from config")
            self.lookup_data = self.repo_config["data"]
        #
        elif repo_type == "config_key":
            config_key = self.repo_config["name"]
            if config_key not in self.module.descriptor.config:
                return
            log.info("Loading plugin repository from config key")
            self.lookup_data = self.module.descriptor.config[config_key]
        #
        elif repo_type == "depot":
            log.info("Using depot plugin repository")
            self.lookup = self._depot_lookup
        #
        elif repo_type == "github":
            log.info("Using GitHub plugin repository")
            self.lookup = self._github_lookup
        #
        elif repo_type == "github_zip":
            log.info("Using GitHub[zip] plugin repository")
            self.lookup = self._github_zip_lookup
        #
        elif repo_type == "github_tar":
            log.info("Using GitHub[tar] plugin repository")
            self.lookup = self._github_tar_lookup
        #
        elif repo_type == "gogs":
            log.info("Using Gogs plugin repository")
            self.lookup = self._gogs_lookup
        #
        else:
            return
        #
        # Metadata
        #
        metadata_config = self.repo_config.get("metadata_provider", None)
        if metadata_config is None:
            metadata_config = {
                "type": "pylon.core.providers.metadata.http",
            }
        #
        metadata_config = metadata_config.copy()
        metadata_provider_type = metadata_config.pop("type")
        #
        self.metadata_provider = importlib.import_module(
            metadata_provider_type
        ).Provider(self.module.context, metadata_config)
        self.metadata_provider.init()
        #
        # Source
        #
        source_config = self.repo_config.get("source_provider", None)
        if source_config is None:
            source_config = {
                "type": "pylon.core.providers.source.git",
                "delete_git_dir": False,
                "depth": None,
            }
        #
        source_config = source_config.copy()
        source_provider_type = source_config.pop("type")
        #
        self.source_provider = importlib.import_module(
            source_provider_type
        ).Provider(self.module.context, source_config)
        self.source_provider.init()

    def resolve(self, plugin):
        """ Resolve plugin """
        for sub_resolver in self.sub_resolvers:
            sub_result = sub_resolver.resolve(plugin)
            if sub_result is not None:
                return sub_result
        #
        return self.lookup(plugin)

    def get_metadata_provider(self, plugin):
        """ Get metadata provider for plugin """
        for sub_resolver in self.sub_resolvers:
            sub_result = sub_resolver.get_metadata_provider(plugin)
            if sub_result is not None:
                return sub_result
        #
        if self.lookup(plugin) is None:
            return None
        #
        return self.metadata_provider

    def get_source_provider(self, plugin):
        """ Get source provider for plugin """
        for sub_resolver in self.sub_resolvers:
            sub_result = sub_resolver.get_source_provider(plugin)
            if sub_result is not None:
                return sub_result
        #
        if self.lookup(plugin) is None:
            return None
        #
        return self.source_provider

    def deinit(self):
        """ De-init resolver """
        while self.sub_resolvers:
            sub_resolver = self.sub_resolvers.pop(0)
            sub_resolver.deinit()
        #
        if self.source_provider is not None:
            self.source_provider.deinit()
        #
        if self.metadata_provider is not None:
            self.metadata_provider.deinit()
