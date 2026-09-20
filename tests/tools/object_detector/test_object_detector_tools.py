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

"""Tests for object_detector universal tools."""

from apollo.tools.base import ApolloTool
from apollo.tools.object_detection_tool import (
    ObjectDetection,
    ObjectDetectionArgs,
    ObjectDetectionTool,
    ObjectDetectorTool,
    OperatorObjectDetection,
    OperatorObjectDetectionArgs,
    OperatorObjectDetectionTool,
    OperatorObjectDetectorTool,
    object_detection,
    operator_object_detection,
)


def test_object_detector_tool_subclass():
    """Verify ObjectDetectionTool is an ApolloTool subclass."""
    assert issubclass(ObjectDetectionTool, ApolloTool)
    assert issubclass(ObjectDetection, ApolloTool)
    assert issubclass(ObjectDetectorTool, ApolloTool)
    assert issubclass(OperatorObjectDetectionTool, ApolloTool)
    assert issubclass(OperatorObjectDetectionTool, ObjectDetectionTool)
    assert issubclass(OperatorObjectDetection, ApolloTool)
    assert issubclass(OperatorObjectDetectorTool, ApolloTool)

    assert isinstance(object_detection, ApolloTool)
    assert isinstance(object_detection, ObjectDetectionTool)
    assert isinstance(operator_object_detection, ApolloTool)
    assert isinstance(operator_object_detection, OperatorObjectDetectionTool)

    assert object_detection.name == "object_detection"
    assert object_detection.category == "perception"
    assert object_detection.args_schema == ObjectDetectionArgs

    assert operator_object_detection.name == "object_detection"
    assert operator_object_detection.category == "perception"
    assert operator_object_detection.args_schema == OperatorObjectDetectionArgs
