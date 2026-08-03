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

""" Maintenance mode task control """

from pylon.core.tools import log  # pylint: disable=E0611,E0401

from .task_targets import TASK_TARGETS


def reject_approver(*_args, **_kwargs):
    return False


# admin.task_node is the shared, always operator-triggered System -> Tasks
# node (fed by admin + several other plugins via register_admin_task()).
MAINTENANCE_EXEMPT_PLUGINS = frozenset({"admin"})


def _iter_queue_nodes(module_manager):
    """ Yield (label, task_node, queue_or_none, task_names) for each queue-backed node. """
    for plugin_name, plugin_target in TASK_TARGETS.items():
        if plugin_name not in module_manager.modules:
            continue
        if plugin_name in MAINTENANCE_EXEMPT_PLUGINS:
            continue
        #
        descriptor = module_manager.modules[plugin_name]
        if descriptor.module is None:
            continue
        #
        for item in plugin_target["queues"]:
            queue_name = item["queue"]
            if not hasattr(descriptor.module, queue_name):
                continue
            #
            queue = getattr(descriptor.module, queue_name)
            if queue is None or getattr(queue, "task_node", None) is None:
                continue
            #
            yield (
                f"{plugin_name}.{queue_name}",
                queue.task_node,
                queue,
                item["tasks"],
            )


def _iter_standalone_nodes(module_manager):
    """ Yield (label, task_node) for each standalone TaskNode. """
    for plugin_name, plugin_target in TASK_TARGETS.items():
        if plugin_name not in module_manager.modules:
            continue
        if plugin_name in MAINTENANCE_EXEMPT_PLUGINS:
            continue
        #
        descriptor = module_manager.modules[plugin_name]
        if descriptor.module is None:
            continue
        #
        for node_name in plugin_target["nodes"]:
            if not hasattr(descriptor.module, node_name):
                log.debug("maintenance: skipping %s.%s (no attribute)", plugin_name, node_name)
                continue
            #
            node = getattr(descriptor.module, node_name)
            if node is None:
                continue
            #
            yield (f"{plugin_name}.{node_name}", node)


def set_task_approvers(self, approver):
    """ Set the task_approver on every discovered TaskNode/TaskQueue.

    Pass approver=None to restore acceptance.
    """
    module_manager = self.context.module_manager
    #
    for label, task_node, _queue, task_names in _iter_queue_nodes(module_manager):
        try:
            if not task_node.started:
                continue
            #
            with task_node.lock:
                for task_name in task_names:
                    if task_name not in task_node.task_registry:
                        continue
                    #
                    if not isinstance(task_node.task_registry[task_name], list):
                        log.info("Legacy arbiter detected on %s, skipping approver toggle", label)
                        continue
                    #
                    current = task_node.task_registry[task_name][1]
                    if approver is None:
                        if current is reject_approver:
                            task_node.task_registry[task_name][1] = None
                        else:
                            log.debug(
                                "maintenance: leaving %s/%s approver alone (%r)",
                                label, task_name, current,
                            )
                    else:
                        task_node.task_registry[task_name][1] = approver
        except:  # pylint: disable=W0702
            log.exception("Failed to toggle approver on %s", label)
    #
    for label, node in _iter_standalone_nodes(module_manager):
        try:
            if not node.started:
                continue
            #
            with node.lock:
                # Only clobber an existing approver if it is ours; otherwise
                # a third party owns it and we must not stomp their state.
                # When approver is None (leaving maintenance) we only clear
                # if the current one is our reject_approver.
                current = getattr(node, "task_approver", None)
                if approver is None:
                    if current is reject_approver:
                        node.task_approver = None
                    else:
                        log.debug(
                            "maintenance: leaving %s alone, approver not ours (%r)",
                            label, current,
                        )
                else:
                    node.task_approver = approver
        except:  # pylint: disable=W0702
            log.exception("Failed to toggle approver on %s", label)


def stop_all_tasks(self):
    """ Stop every running task on every discovered TaskNode.

    Iterates the global task state, calls stop_task on each non-stopped id.
    Non-blocking: does not wait for tasks to fully terminate.
    """
    module_manager = self.context.module_manager
    stopped = 0
    #
    seen_nodes = []
    for _label, task_node, _queue, _tasks in _iter_queue_nodes(module_manager):
        seen_nodes.append((_label, task_node))
    for entry in _iter_standalone_nodes(module_manager):
        seen_nodes.append(entry)
    #
    for label, node in seen_nodes:
        try:
            if not node.started:
                continue
            #
            with node.lock:
                task_ids = []
                for state in node.global_task_state.values():
                    status = state.get("status")
                    task_id = state.get("task_id")
                    if not task_id:
                        continue
                    if status in (None, "stopped", "done", "failed"):
                        continue
                    task_ids.append(task_id)
            #
            for task_id in task_ids:
                try:
                    node.stop_task(task_id)
                    stopped += 1
                except:  # pylint: disable=W0702
                    log.exception("Failed to stop task %s on %s", task_id, label)
        except:  # pylint: disable=W0702
            log.exception("Failed to enumerate tasks on %s", label)
    #
    log.info("Maintenance stop_all_tasks: signalled %s task(s)", stopped)
    return stopped


def enter_maintenance(self):
    """ Signal every task node to reject new tasks and stop what is running. """
    log.info("Maintenance: rejecting new tasks and stopping running tasks")
    try:
        set_task_approvers(self, reject_approver)
    except:  # pylint: disable=W0702
        log.exception("Failed to set reject approvers")
    #
    try:
        stop_all_tasks(self)
    except:  # pylint: disable=W0702
        log.exception("Failed to stop running tasks")


def leave_maintenance(self):
    """ Restore approvers so new tasks are accepted again. """
    log.info("Maintenance: restoring task approvers")
    try:
        set_task_approvers(self, None)
    except:  # pylint: disable=W0702
        log.exception("Failed to restore approvers")


def pause_tasks(self):
    """ Reject new tasks only; running tasks are left to finish on their own. """
    log.info("Task pause: rejecting new tasks, leaving running tasks alone")
    try:
        set_task_approvers(self, reject_approver)
    except:  # pylint: disable=W0702
        log.exception("Failed to set reject approvers")


def resume_tasks(self):
    """ Restore approvers so new tasks are accepted again. """
    log.info("Task pause: restoring task approvers")
    try:
        set_task_approvers(self, None)
    except:  # pylint: disable=W0702
        log.exception("Failed to restore approvers")


def is_maintenance_active(module_manager):
    """ Cheap check for other plugins: is maintenance splash or task-pause on? """
    try:
        if "bootstrap" in module_manager.descriptors:
            state = module_manager.descriptors["bootstrap"].state
            return bool(state.get("splash_enabled", False) or state.get("tasks_paused", False))
    except:  # pylint: disable=W0702
        pass
    return False
