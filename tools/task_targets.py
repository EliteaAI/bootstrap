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

""" Task topology: single source of truth for TaskNode/TaskQueue locations.

Consumed by:
- tools/tasks.py::wait_for_tasks (graceful shutdown drain)
- tools/maintenance.py (approver toggle + stop_all_tasks)

When adding/renaming a TaskNode or TaskQueue, update ONLY this dict.
"""


TASK_TARGETS = {
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
    # pylon_main-hosted TaskNodes. Accept agent/pipeline predicts and index
    # dispatches submitted by the main pylon itself, so both maintenance and
    # graceful-shutdown drain must cover them.
    "elitea_core": {
        "queues": [],
        "nodes": [
            "task_node",
            # Serves the local "eval_runs" pool. A run executes case by case for as long as its
            # dataset takes, so draining it is what stops a deploy orphaning a run mid-case
            # (bounded by task_wait_timeout, after which the eval_run_reap cron fails the row).
            "eval_task_node",
        ],
    },
    "worker_client": {
        "queues": [],
        "nodes": [
            "task_node",
        ],
    },
    # `admin.task_node` is attached at runtime via @web.init in
    # plugins/admin/methods/tasks.py — may not be present depending on load
    # order, so consumers gate on hasattr().
    "admin": {
        "queues": [],
        "nodes": [
            "task_node",
        ],
    },
}
