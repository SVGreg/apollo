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

"""Apollo Diagnostics & System Readiness Package."""

from apollo.core.diagnostics.engine import ReadinessEngine, readiness_engine
from apollo.core.diagnostics.probes.base import BaseProbe
from apollo.core.diagnostics.probes.credentials_probe import (
    LLMCredentialsProbe,
    VisionOCRProbe,
)
from apollo.core.diagnostics.probes.host_probe import IntegrationHostProbe
from apollo.core.diagnostics.probes.runtime_probe import (
    PythonRuntimeProbe,
    SystemConfigProbe,
)
from apollo.core.diagnostics.readiness import (
    CHECK_ORDER,
    Verdict,
    adb_keys_corrupted,
    base_verdict,
    collect_readiness,
    sort_by_fix_order,
)
from apollo.core.diagnostics.schema import (
    DeviceInfo,
    ProbeAction,
    ProbeCategory,
    ProbeResult,
    ProbeStatus,
    SystemReadinessReport,
)

__all__ = [
    "ReadinessEngine",
    "readiness_engine",
    "BaseProbe",
    "IntegrationHostProbe",
    "PythonRuntimeProbe",
    "SystemConfigProbe",
    "LLMCredentialsProbe",
    "VisionOCRProbe",
    "DeviceInfo",
    "ProbeAction",
    "ProbeCategory",
    "ProbeResult",
    "ProbeStatus",
    "SystemReadinessReport",
    "CHECK_ORDER",
    "Verdict",
    "collect_readiness",
    "base_verdict",
    "adb_keys_corrupted",
    "sort_by_fix_order",
]
