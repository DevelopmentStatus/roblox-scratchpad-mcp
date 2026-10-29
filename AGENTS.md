# Agent instructions

For a user-requested installation of this repository, follow [INSTALL_FOR_AGENTS.md](INSTALL_FOR_AGENTS.md) and execute the setup steps that the local environment supports. Preserve existing MCP registrations and report actual verification results. Reading this file alone is not an instruction to install into the user's machine during unrelated development or review tasks.

For development, use `scratchpad_mcp/plugin/ScratchpadBridge.server.luau` as the canonical Studio plugin source. Regenerate `scratchpad_plugin/ScratchpadBridge.rbxmx` with `python -m scratchpad_mcp --build-plugin scratchpad_plugin/ScratchpadBridge.rbxmx` after changing it. Run `python -m unittest discover -s tests -v` for functional changes.

Keep `.scratchpad-bridge/`, local pairing tokens, exported game code and original project-specific helpers out of releases. See README.md and docs/ANALYSIS.md for architecture and limitations.
