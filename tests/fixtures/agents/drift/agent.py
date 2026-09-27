"""Library reservations agent with one defect per review rule.

Do not "fix" this file. Each line below exists so a check has something to
find: the retired package name and options class, a hard-coded retiring model,
a permission mode that skips every prompt, an allow list with no deny list, a
synchronous hook, a deprecated option, a key literal, and options built inline
so nothing outside main() can obtain them.
"""

import asyncio

from claude_code_sdk import ClaudeCodeOptions, query

ANTHROPIC_API_KEY = "sk-ant-api03-not-a-real-key-but-a-literal-in-source"


def audit(input_data, tool_use_id, context):
    print("tool", input_data.get("tool_name"))
    return {}


async def main():
    options = ClaudeCodeOptions(
        model="claude-sonnet-4-5-20250929",
        permission_mode="bypassPermissions",
        allowed_tools=["Read", "Bash"],
        max_thinking_tokens=2000,
        hooks={"PreToolUse": [{"matcher": "Bash", "hooks": [audit]}]},
    )
    async for message in query(prompt="Reserve Dune for member-42.", options=options):
        print(message)


if __name__ == "__main__":
    asyncio.run(main())
