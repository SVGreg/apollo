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

from apollo.tools.diagnoser_submit_answer_tool import get_submit_answer_tool


def test_diagnoser_submit_answer_tool(apollo_context):
    tool = get_submit_answer_tool(apollo_context)

    # Execute the tool with some typical payload
    result = tool.invoke(
        {
            "analysis": "The problem is caused by a network timeout.",
            "actionable_steps": ["Check network connection", "Restart the server"],
        }
    )

    # Assert that the tool executes without raising errors and produces expected output structure
    assert result == "Answer submitted successfully."
    assert "error" not in result.lower()


def test_submit_answer_tool_subclass():
    """Verify SubmitAnswerTool is an ApolloTool subclass."""
    from apollo.tools.base import ApolloTool
    from apollo.tools.diagnoser_submit_answer_tool import (
        DiagnoserSubmitAnswerTool,
        SubmitAnswer,
        SubmitAnswerArgs,
        SubmitAnswerTool,
        submit_answer,
    )

    assert issubclass(SubmitAnswerTool, ApolloTool)
    assert issubclass(SubmitAnswer, ApolloTool)
    assert issubclass(DiagnoserSubmitAnswerTool, ApolloTool)
    assert isinstance(submit_answer, ApolloTool)
    assert isinstance(submit_answer, SubmitAnswerTool)

    assert submit_answer.name == "submit_answer"
    assert submit_answer.category == "custom"
    assert submit_answer.args_schema == SubmitAnswerArgs

    # GenAI FunctionDeclaration export
    declaration = submit_answer.to_genai_declaration()
    assert declaration.name == "submit_answer"
    assert "analysis" in declaration.parameters.properties
    assert "actionable_steps" in declaration.parameters.properties


def test_ask_diagnoser_tool_subclass():
    """Verify AskDiagnoserTool is an ApolloTool subclass."""
    from apollo.tools.base import ApolloTool
    from apollo.tools.diagnostic_tool import (
        AskDiagnoser,
        AskDiagnoserArgs,
        AskDiagnoserTool,
        DiagnosticTool,
        ask_diagnoser,
    )

    assert issubclass(AskDiagnoserTool, ApolloTool)
    assert issubclass(AskDiagnoser, ApolloTool)
    assert issubclass(DiagnosticTool, ApolloTool)
    assert isinstance(ask_diagnoser, ApolloTool)
    assert isinstance(ask_diagnoser, AskDiagnoserTool)

    assert ask_diagnoser.name == "ask_diagnoser"
    assert ask_diagnoser.category == "custom"
    assert ask_diagnoser.args_schema == AskDiagnoserArgs

    # GenAI FunctionDeclaration export
    declaration = ask_diagnoser.to_genai_declaration()
    assert declaration.name == "ask_diagnoser"
    assert "query" in declaration.parameters.properties


def test_analyze_logs_tool_subclass():
    """Verify AnalyzeLogsTool is an ApolloTool subclass."""
    from apollo.tools.base import ApolloTool
    from apollo.tools.log_tool import (
        AnalyzeLogs,
        AnalyzeLogsArgs,
        AnalyzeLogsTool,
        LogTool,
        analyze_logs,
    )

    assert issubclass(AnalyzeLogsTool, ApolloTool)
    assert issubclass(AnalyzeLogs, ApolloTool)
    assert issubclass(LogTool, ApolloTool)
    assert isinstance(analyze_logs, ApolloTool)
    assert isinstance(analyze_logs, AnalyzeLogsTool)

    assert analyze_logs.name == "analyze_logs"
    assert analyze_logs.category == "custom"
    assert analyze_logs.args_schema == AnalyzeLogsArgs

    # GenAI FunctionDeclaration export
    declaration = analyze_logs.to_genai_declaration()
    assert declaration.name == "analyze_logs"
    assert "specific_query" in declaration.parameters.properties
