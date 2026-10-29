# Analysis and release assessment

Analyzed the supplied project on October 28, 2026. The original consists of a Python HTTP/CLI/session-hook bridge, a Studio plugin embedded in XML, and game-specific animation helpers. There was no Git repository, README, package manifest, license, tests or MCP protocol implementation.

## What is valuable

The Studio plugin is already the useful part of a companion tool: editor script updates, compile-before-apply, ChangeHistory recordings, export, captured print/warn/returns, edit-time fresh module loading, and playtest client relay. Keep this as a separate workflow server beside Roblox MCP rather than reproducing asset generation, scene navigation and screenshots.

MCP hosts connect to servers; one server need not become a plugin inside the other. The implementation now uses the official Python SDK's stdio transport and exposes eight narrowly named tools. The Studio-facing HTTP API remains a separate internal transport. SDK v1 is constrained to `mcp>=1.27.1,<2` because that is the API used and tested in this workspace; an SDK v2 migration is separate work.

## Findings in the original

| Severity | Finding | Treatment in the new MCP implementation |
| --- | --- | --- |
| High | No authentication for local HTTP command execution, results, export, or file access | Pairing token on every route, browser Origin rejection, no general file serving |
| High | Export rejects forward-slash traversal but not Windows backslash/drive/ADS paths | Centralized portable path validation and containment/link checks |
| High | Export deletes `src/` before replacement; partial failure or empty exports can lose files | New immutable-by-convention snapshot directories; never replace project source |
| High | Commands are consumed by any peer in a target queue, including another Studio window | Explicit peer addressing and separate edit-peer selection for work sync/export |
| Medium | Plugin installation references a `.server.luau` source missing from the supplied folder | Recovered source from XML; canonical bundled Luau and reproducible XML build |
| Medium | Polling consumes the global sync baseline before Studio confirms applying changes | Revision acknowledgements; retry transport delivery until acknowledged |
| Medium | Multipart export chunks share one unkeyed dictionary | Export batch IDs, peer binding, part validation and resource limits |
| Medium | Queued commands can run after caller timeout; returned results accumulate | Queued command expiry, bounded retained state, no automatic replay; explicit uncertainty after dispatch |
| Medium | Startup takes a port from a previous session by killing its listener | MCP lifespan owns listener; startup fails on conflict |
| Medium | Export reads `.Source` and may miss current editor buffers | Use `ScriptEditorService:GetEditorSource` |
| Release | Claude-specific temporary folders, hook assumptions, game-specific exclusions and hardcoded machine paths | New runtime is host-neutral; original helpers excluded from release inputs |

The original `push_server.py` is retained locally for reference and has not been hardened. Do not distribute or run it as the new MCP server.

## Remaining limits and release gates

The Python tests verify stdio tool discovery/calls, HTTP pairing/origin enforcement, path rejection, peer binding, acknowledged sync, snapshot export isolation, command delivery/result matching and queued timeouts. The generated plugin is parsed as XML. These tests cannot establish that Studio will load the plugin in every edit/server/client context.

Before publishing a release:

- Install the generated plugin into Studio and verify pairing, permission prompts and panel rendering.
- In a disposable place, sync an existing script and a new script, reject invalid Luau, and verify Undo. Check that unsaved editor source exports correctly.
- Open two Studio windows and demonstrate that work sync/export/commands affect the selected peer only. Verify re-selection behavior with old staged work files.
- Exercise edit/server/client commands in a playtest with LoadStringEnabled off. Confirm first-player relay and teardown. Multi-client selection is not implemented.
- The client relay is inherited from the original and must be validated in the current Studio version. If plugin contexts or ModuleScript evaluation do not work, mark those targets unavailable rather than claiming support.
- Choose an open-source license after verifying authorship and redistribution rights. Confirm `developmentstatus` is the intended maintainer name.
- The public source repository is [DevelopmentStatus/roblox-scratchpad-mcp](https://github.com/DevelopmentStatus/roblox-scratchpad-mcp). Git uses a repository-local GitHub no-reply identity, and only reviewed release files are tracked. A tagged GitHub release has not been created; complete the Studio checks and license decision before tagging one.

Potential follow-ups: structured values with explicit Roblox type encoding, change-conflict detection, export metadata for Script/LocalScript/RunContext round trips, exact client selection, command cancellation where Studio can support it, configurable export roots, SDK v2 support, and installer UX. None is required to demonstrate the alpha edit-mode workflow, but they should not be represented as existing capabilities.

## References

- [Official MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x): transport, lifespan and tool APIs.
- [Roblox ScriptEditorService](https://create.roblox.com/docs/reference/engine/classes/ScriptEditorService): editor-aware source access and updates.
