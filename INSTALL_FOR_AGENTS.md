# Install Roblox Scratchpad MCP for the user

This is an executable setup playbook for a local AI coding agent such as Codex or Claude Code. When the user supplies this repository and asks you to install it, carry out the steps below. Complete the installation and verification instead of only explaining the steps.

**User prompt to share with this GitHub repository:**

> Install this repository as a local MCP server by following INSTALL_FOR_AGENTS.md. Install its Python dependencies and Roblox Studio plugin, register it with the AI client I am using, and verify the connection. Use my current Roblox project when available. Preserve my existing MCP servers. Handle everything you can automatically and tell me only the remaining actions that require me.

Reading a GitHub URL alone does not run an installer. The agent needs permission to run local commands and write the selected client's configuration. A remote/cloud agent cannot install into the user's desktop unless it has a local executor on that machine.

## 1. Establish the local installation

- This automatic installation path targets **Windows with Roblox Studio installed**. If operating in WSL, a container, or a cloud environment, use an available Windows-side executor. Do not install into the remote environment and claim the desktop was configured.
- Use the repository URL actually supplied by the user. Do not invent its GitHub owner, repository name, branch, or release URL.
- Reuse a complete existing checkout when it will remain on disk. Otherwise clone into a persistent directory, such as `%LOCALAPPDATA%/RobloxScratchpadMCP/repo`. Never register a server executable inside a temporary extraction folder or disposable worktree.
- The bridge project directory is the user's current Roblox game project if known. If no project is available, create `%LOCALAPPDATA%/RobloxScratchpadMCP/workspace` as an empty bridge workspace. This does not require creating or modifying a Roblox place.
- Select the client the user is currently using. Configure both clients only if requested. If the client cannot be determined from the session or installed applications, ask that one question while continuing package installation.
- Use the existing Roblox Studio MCP connection alongside this server. This repository installs **Scratchpad MCP and its own Studio plugin**; it does not bundle the separate Roblox Studio MCP server, Roblox Studio, Claude, or Codex.

In the following PowerShell commands, assign real absolute paths to `$BridgeRepo` and `$BridgeProject` using those rules. Do not leave placeholder paths in configuration.

```powershell
# Examples of persistent defaults when no existing checkout/project is known:
$BridgeRepo = Join-Path $env:LOCALAPPDATA 'RobloxScratchpadMCP/repo'
$BridgeProject = Join-Path $env:LOCALAPPDATA 'RobloxScratchpadMCP/workspace'
New-Item -ItemType Directory -Force -Path $BridgeProject | Out-Null
```

If cloning is necessary, use `git clone` with the user-supplied URL and `$BridgeRepo`. If Git is unavailable, download a source archive from that same repository, extract into a persistent directory, and locate its `pyproject.toml`. Do not overwrite an unrelated existing directory.

## 2. Find Python and install the package

Find an existing Python **3.11 or newer**, checking `py -3`, `python`, and `python3` as available. Confirm its version; do not assume the Windows Store alias is a working interpreter. Prefer an existing compatible runtime rather than changing the user's default Python.

If Python is missing and the local agent is authorized to install prerequisites, use the available trusted OS package manager to locate and install an official supported Python distribution, then detect it again. Otherwise report that specific missing prerequisite. Do not install AI clients or change unrelated software as part of this bridge setup.

Create a dedicated environment in the persistent checkout. With a verified Python executable assigned to `$BridgeBootstrapPython`:

```powershell
& $BridgeBootstrapPython -m venv (Join-Path $BridgeRepo '.venv')
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the bridge environment' }

$BridgePython = Join-Path $BridgeRepo '.venv/Scripts/python.exe'
& $BridgePython -m pip install $BridgeRepo
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Scratchpad MCP' }

& $BridgePython -m scratchpad_mcp --help
if ($LASTEXITCODE -ne 0) { throw 'Installed bridge entry point failed' }
```

Reusing this environment is fine on a repeat installation. Do not remove it or recreate it blindly. If updating the package, install from the selected checkout again. Keep the installed environment after setup; the MCP host will launch its Python executable directly, so shell activation is unnecessary.

## 3. Install the Studio plugin

If `%LOCALAPPDATA%/Roblox/Plugins/ScratchpadBridge.rbxmx` already exists, save a copy under a private backup directory outside the Plugins folder before replacing it. Avoid leaving backup `.rbxmx` files in Plugins, where Studio could load both copies.

```powershell
& $BridgePython -m scratchpad_mcp --install-plugin
if ($LASTEXITCODE -ne 0) { throw 'Studio plugin installation failed' }
```

Verify that the installed file exists and parses as XML. Do not silently close an open Studio window, discard unsaved work, or stop another bridge process. If Studio is open, finish the other setup steps, then report that Studio must be restarted to load the installed plugin.

## 4. Choose the port and initialize local state

The Studio HTTP link defaults to **35006**. Check whether it is already in use before starting another copy. Reuse a matching existing installation when appropriate. If another process owns the port, choose a free port from 35007 upward and use that same value in the client registration and Studio panel. Never terminate an existing listener just to free the port.

Assign that integer to `$BridgePort`. Create local pairing state without leaving a server running:

```powershell
$BridgePort = 35006 # replace if occupied
& $BridgePython -c "import sys; from pathlib import Path; from scratchpad_mcp.bridge import Bridge; Bridge(Path(sys.argv[1]), int(sys.argv[2])); print('Pairing state initialized')" $BridgeProject $BridgePort
if ($LASTEXITCODE -ne 0) { throw 'Failed to initialize bridge state' }
```

Append `.scratchpad-bridge/` to the bridge project's `.gitignore` if it is not already ignored. Preserve the existing file's contents. Never add the token or exported game scripts to Git. Do not print the pairing token into chat, include it in client configuration, or place it in the repository's plugin source.

## 5. Register with the selected MCP client

Use an absolute executable path and absolute project path. Inspect the client's existing entry named `roblox-scratchpad` first. If it already launches this interpreter with this project and port, keep it. If it belongs to another project, use a distinct descriptive server name instead of overwriting it. Preserve every other server and existing setting.

Client CLI syntax may change. Check the installed CLI's `mcp --help` / `mcp add --help` if a documented command is rejected. Use native registration commands when available instead of rewriting whole configuration files.

### Codex

Inspect `codex mcp get roblox-scratchpad --json` or `codex mcp list`. A missing entry is expected on a first installation. Register the stdio server:

```powershell
codex mcp add roblox-scratchpad -- $BridgePython -m scratchpad_mcp --project $BridgeProject --port $BridgePort
if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed' }
codex mcp get roblox-scratchpad --json
```

Codex supports local stdio server registration through `codex mcp add`; consult the [official Codex MCP documentation](https://developers.openai.com/codex/mcp) for the installed client's current configuration behavior. If the CLI is unavailable but the app exposes MCP settings, add a local stdio server there with the same executable and arguments. If editing configuration directly is necessary, back it up, use a format-aware edit, and validate it afterward.

### Claude Code

Run registration from the selected bridge/game project so local scope belongs to the intended project. Inspect `claude mcp get roblox-scratchpad` or `claude mcp list` first.

```powershell
Push-Location $BridgeProject
try {
    claude mcp add --transport stdio --scope local roblox-scratchpad -- $BridgePython -m scratchpad_mcp --project $BridgeProject --port $BridgePort
    if ($LASTEXITCODE -ne 0) { throw 'Claude Code MCP registration failed' }
    claude mcp get roblox-scratchpad
} finally {
    Pop-Location
}
```

Use local scope by default to avoid committing machine-specific paths into a shared `.mcp.json`. See the [official Claude Code MCP documentation](https://code.claude.com/docs/en/mcp) for transport, scope and trust behavior. Do not assume Claude Desktop uses the Claude Code CLI registration.

### Another local MCP client, including Claude Desktop

Use its supported local stdio registration mechanism. The equivalent entry is:

```json
{
  "mcpServers": {
    "roblox-scratchpad": {
      "command": "ABSOLUTE_PATH_TO_CHECKOUT/.venv/Scripts/python.exe",
      "args": ["-m", "scratchpad_mcp", "--project", "ABSOLUTE_PATH_TO_PROJECT", "--port", "35006"]
    }
  }
}
```

Substitute real values and merge only this entry into the client configuration. This JSON shape is a generic example, not a promise that every client uses that file format. Verify the actual app and its documented configuration location before editing.

## 6. Verify MCP before touching the game

Reconnect the configured server using the client's supported controls. If the current agent cannot hot-load newly registered tools, verify the registration now and report the exact restart/reconnect step needed. Do not claim the current session gained tools merely because registration succeeded.

Once connected:

1. List the server's tools. Expect the eight `scratchpad_*` tools listed in README.md.
2. Call `scratchpad_status`; a result with no peers is valid before Studio is paired.
3. Confirm the reported project work directory and port match the intended installation.

If the host cannot yet connect, a temporary official-SDK stdio client may initialize the installed server, list tools and call `scratchpad_status` to validate the transport. Shut that temporary client down before reconnecting the real host, so they do not compete for the same port. Do not leave an independent background server running; the host owns the server lifecycle.

Registration, a successful CLI `--help`, and a valid plugin XML file alone do not prove the live MCP transport is working. Clearly distinguish these verification levels.

## 7. Pair Studio with the bridge

Use available local UI tools to finish this step when permitted. Otherwise give the user only the remaining exact actions:

1. Open/restart Roblox Studio without discarding unsaved work.
2. Open **Scratchpad → Bridge**.
3. Enter the selected port if it differs from 35006.
4. Read the token from `<bridge-project>/.scratchpad-bridge/token` locally, paste it into the pairing field, and press Enter. Keep it out of chat/tool logs where possible.
5. Complete any Studio localhost HTTP and script-edit permission prompts.
6. Call `scratchpad_status` again and identify the intended **edit peer** using the place metadata. If multiple windows are ambiguous, ask which one rather than guessing.

Do not enable Sync, select a different window with old staged work files, or create a test script in the user's place solely to prove installation. For a read-only smoke check, use the intended edit peer with `scratchpad_execute` and `return 1 + 1`. Expect `ok: true` and a return value of `"2"`. Enable Sync when the user starts a script-sync task, after checking staged files.

Roblox Studio permission dialogs and application reloads may require the user. A markdown file cannot bypass them, an organization's restrictions, or the agent's sandbox. Finish independent steps first and describe the specific remaining action.

## 8. Finish with a short installation report

Report:

- Installed package/environment and plugin paths.
- Configured client, server name, bridge project and port.
- Whether the MCP transport was verified, whether a Studio peer connected, and whether the read-only execution check passed.
- Only the exact actions still required, if any.

Never report "fully connected" when only the files/configuration were installed. Do not publish a repository, change Git identity/email, install unrelated plugins, alter a game, or disable security settings as part of this setup.

## Troubleshooting

| Symptom | Agent action |
| --- | --- |
| Python is missing/too old | Locate a compatible installed runtime or install the prerequisite through the supported local package manager |
| Package install fails | Inspect the actual pip error, fix that dependency/network issue, retry the failed step |
| `mcp` import fails | Use the dedicated environment's absolute Python path; confirm package installation there |
| Port is occupied | Reuse a matching installed server or choose a free port; never kill the listener automatically |
| HTTP 403 / no Studio peers | Check token, port, plugin version and Studio permission prompts |
| Tools are not visible | Check registration, reconnect/restart the host, and inspect its MCP errors |
| Old bridge is installed | Back up and replace its plugin; do not run the legacy push server against the new plugin |
| Linux/macOS/cloud only | Report that the Windows automatic Studio installation path is unavailable; do not claim desktop installation |
