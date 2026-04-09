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

""" Logs """

import logging
import traceback


class LocalListLogHandler(logging.Handler):
    """ Log handler - send logs to local list """

    def __init__(self, target_list, max_size=1000):
        super().__init__()
        self.target_list = target_list
        self.max_size = max_size

    def emit(self, record):
        try:
            log_line = self.format(record)
            self.target_list.append(log_line)
            #
            while len(self.target_list) > self.max_size:
                self.target_list.pop(0)
        except:  # pylint: disable=W0702
            # In this case we should NOT use logging to log logging error. Only print()
            print("[FATAL] Exception during sending logs")
            traceback.print_exc()
