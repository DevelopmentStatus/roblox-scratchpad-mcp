# Roblox Scratchpad MCP

An **alpha** local MCP server and Roblox Studio plugin for script files, acknowledged sync, script export snapshots, and Luau execution in edit and playtest contexts. Designed to run alongside Roblox Studio MCP tools.

Maintainer: **developmentstatus**. This is an independent project, not an official Roblox product.

[GitHub repository](https://github.com/DevelopmentStatus/roblox-scratchpad-mcp)

## Let an AI agent install it

Give your local Claude Code, Codex, or other coding agent this repository link and say:

> Install this repository by following INSTALL_FOR_AGENTS.md. Set up the dependencies, Studio plugin, and MCP client connection, then verify it.

The [agent installation guide](INSTALL_FOR_AGENTS.md) walks the agent through setup and client registration. [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md) point agents to it. The agent needs local machine access; Studio reloads and permission prompts may still require you.

## What goes where

```text
MCP host ── stdio ── Scratchpad MCP ── token-authenticated loopback HTTP ── Studio plugin
        └────────── Roblox Studio MCP (scene tools, assets, play controls, screenshots)
```

Scratchpad MCP owns its HTTP listener for the life of the stdio connection. It does not depend on Claude hooks, kill previous sessions, or register itself with another MCP server. Configure both servers in your MCP host. The local HTTP listener is a private Studio transport, **not** an MCP HTTP endpoint.

| Tool | Purpose |
| --- | --- |
| `scratchpad_status` | Discover peers, place metadata, selection and work directory |
| `scratchpad_select_studio` | Bind work-file sync and exports to one edit peer |
| `scratchpad_list_files` | List locally staged scripts |
| `scratchpad_read_file` | Read a locally staged script |
| `scratchpad_write_file` | Stage a script; consult logs for its apply acknowledgement |
| `scratchpad_execute` | Run Luau on an explicit edit/server/client-relay peer |
| `scratchpad_export` | Create a new snapshot of selected Studio scripts |
| `scratchpad_logs` | Inspect sync, compile, apply and export events |

## Install and connect (Windows)

Requires Python 3.11+ and Roblox Studio. From this checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m scratchpad_mcp --install-plugin
```

Restart Studio after installation. Installing replaces a local plugin named `ScratchpadBridge.rbxmx`. If you have the original bridge installed, keep a backup and stop its push server before using this version.

Configure your MCP host to launch the installed environment's executable. Generic JSON example (replace both absolute paths):

```json
{
  "mcpServers": {
    "roblox-scratchpad": {
      "command": "C:/path/to/RobloxScratchpadBridge/.venv/Scripts/roblox-scratchpad-mcp.exe",
      "args": ["--project", "C:/path/to/your/game", "--port", "35006"]
    }
  }
}
```

The project directory must exist. Start/reconnect this MCP server in your host, then:

1. Read `<project>/.scratchpad-bridge/token` locally. In PowerShell: `Get-Content C:/path/to/your/game/.scratchpad-bridge/token`.
2. Open Studio's **Scratchpad → Bridge** panel. Paste that token into the pairing field and press Enter. Allow localhost HTTP and script-edit permissions when Studio prompts.
3. Call `scratchpad_status`. Match the place name and place ID with your intended Studio window. Call `scratchpad_select_studio` with its **edit peer ID**.
4. Enable **Sync** in that window's panel. It defaults to off for a new installation.
5. Stage a file such as `ReplicatedStorage/Example.luau` with source `return { greeting = "hello" }`. Read `scratchpad_logs` for an `applied` acknowledgement.

You can also edit files directly inside the work directory reported by `scratchpad_status`. No project source tree is automatically mirrored. Exports are independent snapshots; review and copy chosen scripts into work before syncing them.

For another port, change `--port` and the panel port together. Use a separate port for each simultaneously running bridge. Plugin settings are saved locally; after changing token/port, restart a playtest so its plugin contexts pick up the settings. A busy port causes startup to fail instead of terminating another process.

## Execution and pairing with Roblox MCP

Use Roblox Studio MCP to inspect the scene, manage playtests, access assets and take screenshots. Use Scratchpad MCP for file-based script work and its captured execution results. Scratchpad `peer_id` values and Roblox MCP `studio_id` values are separate; there is no shared selection or automatic identity mapping.

`scratchpad_execute` accepts `peer_id`, `code` and a 1–120 second `timeout`. The result contains `ok`, captured `output`, stringified `returns`, and an `error` when execution fails. Each command targets one connected peer. A disconnected target fails immediately.

Edit commands support `freshRequire(module)` to compile current editor source instead of using the edit-mode module cache. This is not a full replacement for Roblox `require`: cyclic modules and nil/false returns are not faithfully supported. Server and client-relay peers appear during a playtest if Studio loads the plugin in those contexts. The client relay uses the first player; multi-client targeting is not implemented.

Arbitrary Luau runs with plugin permissions and is not sandboxed. A timeout expires a queued command, but **cannot interrupt code already dispatched**. A timed-out result reports whether it may still be running. Do not automatically retry mutations. Non-yielding code can freeze Studio. `LoadStringEnabled` is not required by this server; the plugin retains a ModuleScript compilation fallback for play contexts. Keep that setting off when publishing games.

## Files, exports and limits

- Paths use `/`, begin with a supported Roblox service, and end in `.luau`, `.server.luau`, or `.client.luau`. New scripts need existing parent instances. File deletion does not delete a Studio script.
- Exports read editor source via `ScriptEditorService:GetEditorSource`. They include scripts below Workspace, ReplicatedFirst, ReplicatedStorage, ServerScriptService, ServerStorage, StarterGui, StarterPack and StarterPlayer. No game-specific paths are excluded.
- Snapshots live in `.scratchpad-bridge/exports/<unique-id>/`. Existing source/work files are not overwritten by export. Empty exports are valid. Script names that cannot be represented safely as portable file paths cause the export to fail.
- This is a script-content workflow, not a complete place serializer. Properties, attributes, RunContext/class distinctions, disabled state and non-script instances are not preserved. A Client RunContext Script exports with the LocalScript suffix.
- Sources/commands are limited to 512 KiB; export chunks to 600 KiB of encoded JSON; complete exports to 32 MiB and 200 chunks. Sync transport responses are bounded. Compile failures are acknowledged and logged; fix or re-save through the write tool to retry.
- The bridge retains 500 log events. Commands/results are in memory and do not survive restart. A plugin restart generates a new peer ID and requires selecting it again. Switching edit peers replays existing work files into the new selected window when Sync is on; review work files first.

## Local security

The listener binds only to `127.0.0.1`. All HTTP routes require `X-Scratchpad-Token`; requests with an Origin header are rejected. There is no general-purpose file server. Paths reject drive escapes, backslashes, traversal, Windows device names, alternate data streams and links. This protects against accidental exposure and unauthenticated localhost callers; it is not isolation from a malicious process running as your OS user. Protect the project and token using normal OS permissions. Plugin settings store the token locally, not in the place file.

Add `.scratchpad-bridge/` to your **game project's** `.gitignore` as well. Do not publish pairing tokens, exported game code, `.env` files or logs. One bridge supports one MCP connection at a time; do not launch multiple copies on the same port.

## Development and release

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
python -m scratchpad_mcp --build-plugin scratchpad_plugin/ScratchpadBridge.rbxmx
python -m pip install build
python -m build
```

Canonical plugin source is `scratchpad_mcp/plugin/ScratchpadBridge.server.luau`; the `.rbxmx` is generated. Package builds include this source so plugin installation works from a wheel. CI runs the Python tests, checks the generated plugin, and builds distributions on Windows and Linux. Studio integration requires manual validation; see [analysis and release checklist](docs/ANALYSIS.md).

Original `push_server.py`, movement-animation helpers and their paths remain local archival files and are excluded by `.gitignore` and the package file list. Do not use `git add -f` or publish the original folder wholesale. The new protocol and plugin must be used together; the old push server is incompatible with this plugin.

Release identity is `DevelopmentStatus`; project metadata contains no email. Use your verified GitHub no-reply email locally before committing. A license has deliberately not been assigned: confirm ownership of the original plugin and choose a license before advertising this as an open-source release.
