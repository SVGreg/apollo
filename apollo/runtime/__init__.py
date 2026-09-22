# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Apollo cross-platform runtime and process supervisor subsystem."""

from apollo.runtime.device_lock import (
    ConcurrencyMode,
    DeviceBusyError,
    DeviceExecutionLock,
)
from apollo.runtime.device_pool import DevicePool, DeviceStatus, device_pool
from apollo.runtime.device_target import DeviceTarget
from apollo.runtime.process_probe import pid_is_alive
from apollo.runtime.daemon_client import (
    ensure_daemon_running,
    get_daemon_session,
    get_daemon_status,
    is_apollo_daemon,
    is_daemon_running,
    stop_task_on_daemon,
    submit_batch_to_daemon,
    submit_task_to_daemon,
    wait_for_daemon_task,
)
from apollo.runtime.server_lifecycle import (
    clear_server_info,
    find_server_pids,
    get_server_status,
    is_port_in_use,
    read_server_info,
    stop_server,
    write_server_info,
)
from apollo.runtime.supervisor import ProcessSupervisor, process_supervisor
from apollo.runtime.cancel_requests import (
    clear_cancel_request,
    is_cancel_requested,
    request_cancel,
    watch_for_cancel_request,
)

__all__ = [
    "ConcurrencyMode",
    "DeviceBusyError",
    "DeviceExecutionLock",
    "DevicePool",
    "DeviceStatus",
    "DeviceTarget",
    "clear_cancel_request",
    "clear_server_info",
    "device_pool",
    "ensure_daemon_running",
    "find_server_pids",
    "get_daemon_session",
    "get_daemon_status",
    "get_server_status",
    "is_apollo_daemon",
    "is_daemon_running",
    "is_cancel_requested",
    "is_port_in_use",
    "pid_is_alive",
    "ProcessSupervisor",
    "process_supervisor",
    "read_server_info",
    "request_cancel",
    "stop_server",
    "stop_task_on_daemon",
    "submit_batch_to_daemon",
    "submit_task_to_daemon",
    "wait_for_daemon_task",
    "watch_for_cancel_request",
    "write_server_info",
]
