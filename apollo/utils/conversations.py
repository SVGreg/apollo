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

from apollo.utils.image_data_url import image_data_url
from typing import TypeGuard

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


def is_ai_message(message: BaseMessage) -> TypeGuard[AIMessage]:
    return isinstance(message, AIMessage)


def is_human_message(message: BaseMessage) -> TypeGuard[HumanMessage]:
    return isinstance(message, HumanMessage)


def is_tool_message(message: BaseMessage) -> TypeGuard[ToolMessage]:
    return isinstance(message, ToolMessage)


def is_tool_for_name(tool_message: ToolMessage, name: str) -> bool:
    return tool_message.name == name


def get_screenshot_message_for_llm(screenshot_base64: str):
    url = (
        screenshot_base64
        if screenshot_base64.startswith("data:image")
        else image_data_url(screenshot_base64)
    )
    return HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": url},
            }
        ]
    )
