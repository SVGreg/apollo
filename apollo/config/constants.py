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

"""Centralized constants, environment variable names, and type definitions for APOLLO."""

from typing import Literal

# ==============================================================================
# Environment Variable Keys
# ==============================================================================

# Application & Workspace Paths
ENV_APOLLO_APP_DIR = "APOLLO_APP_DIR"
ENV_ANTIGRAVITY_APP_DIR = "ANTIGRAVITY_APP_DIR"
ENV_APOLLO_USE_USER_DIR = "APOLLO_USE_USER_DIR"
ENV_APOLLO_TRACES_DIR = "APOLLO_TRACES_DIR"
ENV_DATA_ENGINE_DB_PATH = "DATA_ENGINE_DB_PATH"

# Cloud Brain & Distributed Execution
ENV_APOLLO_CLOUD_MODE = "APOLLO_CLOUD_MODE"
ENV_APOLLO_CLOUD_SESSION_ID = "APOLLO_CLOUD_SESSION_ID"
ENV_APOLLO_CLOUD_GATEWAY_URL = "APOLLO_CLOUD_GATEWAY_URL"
ENV_APOLLO_TENANT_ID = "APOLLO_TENANT_ID"
ENV_APOLLO_TENANT_TOKEN = "APOLLO_TENANT_TOKEN"
ENV_APOLLO_EDGE_PORT = "APOLLO_EDGE_PORT"

# Runtime State & IPC
ENV_APOLLO_IPC_PORT = "APOLLO_IPC_PORT"
ENV_ANTIGRAVITY_LS_ADDRESS = "ANTIGRAVITY_LS_ADDRESS"
ENV_APOLLO_MCP_SERVER = "APOLLO_MCP_SERVER"

# Device & ADB
ENV_ADB_DEVICE_SERIAL = "ADB_DEVICE_SERIAL"
ENV_APOLLO_DEVICE_ID = "APOLLO_DEVICE_ID"
ENV_ADB_HOST = "ADB_HOST"
ENV_ADB_PORT = "ADB_PORT"
ENV_ADB_SERVER_SOCKET = "ADB_SERVER_SOCKET"
# UI hierarchy backend: "auto" (helper, UIAutomator2 fallback), "helper", "uiautomator"
ENV_APOLLO_HIERARCHY_BACKEND = "APOLLO_HIERARCHY_BACKEND"
# "true" (default) lets a task install / upgrade the Accessibility Helper APK on a
# device it holds; "false" only attaches to a helper someone installed by hand.
ENV_APOLLO_HELPER_AUTO_INSTALL = "APOLLO_HELPER_AUTO_INSTALL"

# LLM & Vision OCR API Keys
ENV_GOOGLE_API_KEY = "GOOGLE_API_KEY"
ENV_GEMINI_API_KEY = "GEMINI_API_KEY"
ENV_GCP_API_KEY = "GCP_API_KEY"
ENV_OCR_API_KEY = "OCR_API_KEY"
ENV_VISION_API_KEY = "VISION_API_KEY"
ENV_API_KEY = "API_KEY"
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_OPENAI_BASE_URL = "OPENAI_BASE_URL"
ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
ENV_OPEN_ROUTER_API_KEY = "OPEN_ROUTER_API_KEY"
ENV_XAI_API_KEY = "XAI_API_KEY"

# Explorer & Agent Defaults
ENV_APOLLO_EXPLORER_VERSION = "APOLLO_EXPLORER_VERSION"
ENV_APOLLO_DEFAULT_PROFILE = "APOLLO_DEFAULT_PROFILE"
ENV_APOLLO_DEFAULT_MODEL = "APOLLO_DEFAULT_MODEL"
ENV_APOLLO_USE_FILE_API = "APOLLO_USE_FILE_API"

# Debugging & Output Paths
ENV_KEEP_VIDEOS = "KEEP_VIDEOS"
ENV_APOLLO_DEBUG = "APOLLO_DEBUG"
ENV_EVENTS_OUTPUT_PATH = "EVENTS_OUTPUT_PATH"
ENV_RESULTS_OUTPUT_PATH = "RESULTS_OUTPUT_PATH"


# ==============================================================================
# Configuration Filenames
# ==============================================================================

APOLLO_CONFIG_FILENAME = "apollo.jsonc"
LLM_CONFIG_FILENAME = "llm-config.json"
LLM_CONFIG_OVERRIDE_FILENAME = "llm-config.override.jsonc"
AGENT_CONFIG_FILENAME = "agent_config.json"
DATA_ENGINE_DB_FILENAME = "data_engine.db"
IPC_PORT_FILENAME = ".apollo_ipc_port"
LS_ADDRESS_FILENAME = ".jetski_ls_address"
SERVER_INFO_FILENAME = ".apollo_server.json"
PAUSE_FILENAME = ".apollo_paused"
REPLAY_DIRNAME = "replay"
TEST_DATA_DIRNAME = "data"
TEST_OUTPUTS_DIRNAME = "outputs"
IMAGES_DIRNAME = "images"
DOTENV_FILENAME = ".env"


# ==============================================================================
# Default Values & Network Ports
# ==============================================================================

DEFAULT_ADB_HOST = "127.0.0.1"
DEFAULT_ADB_PORT = 5037
DEFAULT_GATEWAY_PORT = 8000
DEFAULT_EDGE_MONITOR_PORT = 8000
DEFAULT_ACTION_TIMEOUT = 30.0
DEFAULT_STREAM_PING_INTERVAL = 15.0

DEFAULT_PROFILE = "pro"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_EXPLORER_VERSION: Literal["flash", "pro", "ultra"] = "flash"


# ==============================================================================
# Literals and Type Aliases
# ==============================================================================

LLMProvider = Literal[
    "openai", "google", "openrouter", "xai", "vertexai", "anthropic", "ollama", "vllm", "custom"
]
ExplorerVersion = Literal["flash", "pro", "ultra"]

LLMUtilsNode = Literal[
    "outputter",
    "hopper",
    "video_analyzer",
    "object_detector",
]
LLMUtilsNodeWithFallback = LLMUtilsNode

AgentNode = Literal[
    "planner",
    "summarizer",
    "operator",
    "operator_summarizer",
    "log_reader_sub_agent",
    "log_analyzer",
    "diagnoser",
    "checker",
    "planner_avatar",
    "history_analyzer_expert",
    "diagnoser_expert",
    "explorer",
    "history_analyzer",
    "validator_pixel_safety_net",
    "planner_validation",
    "validator",
    "output_analyzer",
]
AgentNodeWithFallback = AgentNode
