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

""" Tasks """

import time

from pylon.core.tools import log  # pylint: disable=E0611,E0401


def wait_for_tasks(self):  # pylint: disable=R0912,R0914,R0915
    """ Wait for running tasks to stop """
    #
    # Timeout:
    # - None = no limit, wait for all tasks as long as it takes
    # - 0 - zero limit, do not wait at all
    # - X - wait at most X seconds
    #
    wait_started = time.time()
    #
    def _get_timeout():
        return self.descriptor.config.get("task_wait_timeout", 15 * 60)
    #
    def _is_timeout():
        timeout = _get_timeout()
        #
        if timeout is None:
            return False
        #
        if timeout == 0:
            return True
        #
        return abs(time.time() - wait_started) >= timeout
    #
    if _is_timeout():
        return
    #
    log.info("Waiting for tasks to stop")
    #
    # Targets: TaskNodes and TaskQueues inside plugins/modules
    #
    targets = {
        "indexer_worker": {
            "queues": [
                {
                    "queue": "index_task_queue",
                    "tasks": [
                        "indexer_index",
                        "indexer_index_stream",
                    ],
                },
            ],
            "nodes": [
                "agent_task_node",
                "index_task_node",
            ],
        },
        "worker_core": {
            "queues": [
                {
                    "queue": "task_queue_preload",
                    "tasks": [
                        "invoke_model",
                    ],
                },
                {
                    "queue": "task_queue",
                    "tasks": [
                        "indexer_ask",
                        "indexer_ask_stream",
                        "indexer_search",
                        "indexer_deduplicate",
                        "indexer_delete",
                    ],
                },
            ],
            "nodes": [
                "task_node_light",
                "task_node_heavy",
            ],
        },
    }
    #
    # Commons
    #
    module_manager = self.context.module_manager
    #
    # Init: TaskQueues
    #
    wait_queues = []
    #
    for plugin_name, plugin_target in targets.items():
        if plugin_name not in module_manager.modules:
            continue
        #
        descriptor = module_manager.modules[plugin_name]
        #
        if descriptor.module is None:
            continue
        #
        for item in plugin_target["queues"]:
            queue_name = item["queue"]
            #
            if not hasattr(descriptor.module, queue_name):
                continue
            #
            queue = getattr(descriptor.module, queue_name)
            #
            if not queue.task_node.started:
                continue
            #
            with queue.task_node.lock:
                for task_name in item["tasks"]:
                    if task_name not in queue.task_node.task_registry:
                        continue
                    #
                    if not isinstance(queue.task_node.task_registry[task_name], list):
                        log.info("Looks like legacy arbiter, skipping task waiting")
                        return
                    #
                    log.info(
                        "Disabling approval of %s queue %s task %s",
                        plugin_name, queue_name, task_name,
                    )
                    #
                    queue.task_node.task_registry[task_name][1] = lambda *args, **kwargs: False
            #
            wait_queues.append(
                (queue_name, queue)
            )
    #
    # Wait: TaskQueues
    #
    while True:
        if not wait_queues:
            break
        #
        have_queue_tasks = False
        #
        for queue_name, queue in wait_queues:
            with queue.lock:
                if queue.tasks:
                    log.info("Queue %s still has tasks, waiting", queue_name)
                    have_queue_tasks = True
        #
        if not have_queue_tasks:
            log.info("No more TaskQueues with tasks")
            break
        #
        if _is_timeout():
            log.info("Task wait timeout reached")
            return
        #
        time.sleep(self.descriptor.config.get("task_wait_interval", 15))
    #
    # Init: TaskNodes
    #
    wait_nodes = []
    #
    for plugin_name, plugin_target in targets.items():
        if plugin_name not in module_manager.modules:
            continue
        #
        descriptor = module_manager.modules[plugin_name]
        #
        if descriptor.module is None:
            continue
        #
        for node_name in plugin_target["nodes"]:
            if not hasattr(descriptor.module, node_name):
                continue
            #
            node = getattr(descriptor.module, node_name)
            #
            if not node.started:
                continue
            #
            with node.lock:
                log.info(
                    "Disabling approval of %s node %s",
                    plugin_name, node_name,
                )
                #
                node.task_approver = lambda *args, **kwargs: False
            #
            wait_nodes.append(
                (node_name, node)
            )
    #
    # Wait: TaskNodes
    #
    while True:
        if not wait_nodes:
            break
        #
        have_node_tasks = False
        #
        for node_name, node in wait_nodes:
            if node.have_running_tasks.is_set():
                log.info("Node %s still has tasks, waiting", node_name)
                have_node_tasks = True
        #
        if not have_node_tasks:
            log.info("No more TaskNodes with tasks")
            break
        #
        if _is_timeout():
            log.info("Task wait timeout reached")
            return
        #
        time.sleep(self.descriptor.config.get("task_wait_interval", 15))
    #
    # Done
    #
    log.info("Task wait completed")
