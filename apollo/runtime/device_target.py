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

"""Which device a queued task runs on, and how its execution lock is scoped.

Artemis scoped locks by ADB server endpoint plus serial, because one host could
drive devices through several adb servers. Apollo talks to simulators (and, from
Phase 3, USB devices) on this host only, so the scope is the host itself and the
key is the UDID.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

LOCAL_SCOPE = "local"


@dataclass(frozen=True)
class DeviceTarget:
    """A task's target device: a simulator or device UDID, or None for 'any'."""

    serial: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> DeviceTarget:
        if not isinstance(value, Mapping):
            return cls()
        serial = value.get("serial") or value.get("device_serial")
        return cls(serial=str(serial) if serial else None)

    @property
    def lock_scope(self) -> str:
        return LOCAL_SCOPE

    @property
    def lock_key(self) -> str:
        """Identity the device lock is taken on."""
        return f"{LOCAL_SCOPE}:{self.serial}" if self.serial else LOCAL_SCOPE

    def to_dict(self) -> dict[str, Any]:
        return {"scope": LOCAL_SCOPE, "serial": self.serial}
