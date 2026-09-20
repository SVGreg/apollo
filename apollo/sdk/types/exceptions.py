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

"""Exceptions for the APOLLO SDK.

This module defines the exception hierarchy used throughout the Apollo SDK.
"""

from typing import Literal


class ApolloError(Exception):
    """Base exception class for all APOLLO SDK exceptions."""

    def __init__(self, message="An error occurred in the Apollo SDK"):
        self.message = message
        super().__init__(self.message)


class DeviceError(ApolloError):
    """Exception raised for errors related to mobile devices."""

    def __init__(self, message="A device-related error occurred"):
        super().__init__(message)


class DeviceNotFoundError(DeviceError):
    """Exception raised when no mobile device is found."""

    def __init__(self, message="No mobile device found"):
        super().__init__(message)


class ServerError(ApolloError):
    """Exception raised for errors related to APOLLO servers."""

    def __init__(self, message="A server-related error occurred"):
        super().__init__(message)


class ServerStartupError(ServerError):
    """Exception raised when APOLLO servers fail to start."""

    def __init__(self, server_name=None, message=None):
        if server_name and not message:
            message = f"Failed to start {server_name}"
        elif not message:
            message = "Failed to start Apollo servers"
        super().__init__(message)
        self.server_name = server_name


class AgentError(ApolloError):
    """Exception raised for errors related to the APOLLO agent."""

    def __init__(self, message="An agent-related error occurred"):
        super().__init__(message)


class AgentNotInitializedError(AgentError):
    """Exception raised when attempting operations on an uninitialized agent."""

    def __init__(self, message="Agent is not initialized. Call init() first"):
        super().__init__(message)


class AgentTaskRequestError(AgentError):
    """Exception raised when a requested task is invalid."""

    def __init__(self, message="An agent task-related error occurred"):
        super().__init__(message)


class AgentProfileNotFoundError(AgentTaskRequestError):
    """Exception raised when an agent profile is not found."""

    def __init__(self, profile_name: str):
        super().__init__(f"Agent profile {profile_name} not found")


EXECUTABLES = Literal["adb"]


class ExecutableNotFoundError(ApolloError):
    """Exception raised when a required executable is not found."""

    def __init__(self, executable_name: EXECUTABLES):
        install_instructions: dict[EXECUTABLES, str] = {
            "adb": "https://developer.android.com/tools/adb",
        }
        message = f"Required executable '{executable_name}' not found in PATH."
        if executable_name in install_instructions:
            message += f"\nTo install it, please visit: {install_instructions[executable_name]}"
        super().__init__(message)
