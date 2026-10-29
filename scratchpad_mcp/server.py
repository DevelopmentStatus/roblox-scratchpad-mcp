"""stdio MCP entry point with an owned, authenticated Studio HTTP bridge."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from importlib.resources import files
import json
import os
from pathlib import Path
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .bridge import Bridge, atomic_write, safe_path, start_http


def build_plugin() -> str:
    source = files("scratchpad_mcp").joinpath("plugin/ScratchpadBridge.server.luau").read_text(encoding="utf-8")
    source = source.replace("]]>", "]]]]><![CDATA[>")
    return ('<roblox version="4">\n  <Item class="Script" referent="RBX0">\n'
            '    <Properties>\n      <string name="Name">ScratchpadBridge</string>\n'
            f'      <ProtectedString name="Source"><![CDATA[{source}]]></ProtectedString>\n'
            '    </Properties>\n  </Item>\n</roblox>\n')


def create_mcp(bridge: Bridge) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_server):
        try:
            http, thread = start_http(bridge)
        except OSError as exc:
            raise RuntimeError(f"Cannot bind 127.0.0.1:{bridge.port}; stop the existing bridge or choose --port") from exc
        print(f"Scratchpad Studio link: 127.0.0.1:{bridge.port}; pairing token: {bridge.state / 'token'}", file=sys.stderr)
        try:
            yield {}
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=2)

    mcp = FastMCP("Roblox Scratchpad", instructions=(
        "Companion to Roblox Studio MCP. Use the other server for scene inspection, assets and play controls. "
        "Use this server for local script files, acknowledged sync, exports and explicit-peer Luau execution. "
        "Call scratchpad_status first. Peer IDs are independent of the other server's studio_id; verify place metadata. "
        "Select the intended edit peer before syncing/exporting. Execution has full plugin permissions. "
        "A timeout cannot stop dispatched Luau. Never blindly retry a timed-out mutation."
    ), lifespan=lifespan)
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    mutation = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

    @mcp.tool(annotations=read_only)
    def scratchpad_status() -> dict:
        """List connected edit/server/client relay peers and the bound work directory."""
        return bridge.status()

    @mcp.tool(annotations=mutation)
    def scratchpad_select_studio(peer_id: str) -> dict:
        """Bind work-file sync and exports to a connected edit peer. Selecting replays existing work files."""
        return bridge.select(peer_id)

    @mcp.tool(annotations=read_only)
    def scratchpad_list_files() -> dict:
        """List local work files. These are not a complete inventory of Studio scripts."""
        with bridge.condition:
            return {"files": [p.relative_to(bridge.work).as_posix() for p in sorted(bridge.work.rglob("*.luau"))
                              if safe_path(bridge.work, p.relative_to(bridge.work).as_posix()).is_file()]}

    @mcp.tool(annotations=read_only)
    def scratchpad_read_file(path: str) -> dict:
        """Read a service-relative local work file, e.g. ReplicatedStorage/Example.luau."""
        with bridge.condition:
            return {"path": path, "source": safe_path(bridge.work, path).read_text(encoding="utf-8")}

    @mcp.tool(annotations=mutation)
    def scratchpad_write_file(path: str, source: str) -> dict:
        """Stage a work file for the selected Studio. Enable Sync in its panel; check logs for applied/error."""
        with bridge.condition:
            if bridge.selected not in bridge.active():
                raise ValueError("select a connected edit peer first")
            atomic_write(safe_path(bridge.work, path), source)
            bridge.sent.pop(path, None)
            return {"path": path, "staged": True, "applied": False,
                    "next": "Check scratchpad_logs for an applied/error acknowledgement; panel Sync must be on."}

    @mcp.tool(annotations=mutation)
    def scratchpad_execute(peer_id: str, code: str, timeout: float = 30) -> dict:
        """Run arbitrary Luau with plugin privileges on an explicit peer. Capture print/warn/returns/errors.

        Server/client peers require a running playtest. Client relay uses its first player.
        No runtime cancellation or sandbox: yielding forever can stall its command loop;
        non-yielding code can freeze Studio. freshRequire is available in edit mode.
        """
        return bridge.execute(peer_id, code, timeout)

    @mcp.tool(annotations=mutation)
    def scratchpad_export(peer_id: str, timeout: float = 60) -> dict:
        """Export selected Studio scripts into a new local snapshot without replacing project source files."""
        return bridge.execute(peer_id, "", timeout, action="export")

    @mcp.tool(annotations=read_only)
    def scratchpad_logs(since: int = 0) -> dict:
        """Read the last 500 sync/export events after an event ID; includes compile/apply errors."""
        with bridge.condition:
            return {"events": [event for event in bridge.events if event["id"] > since]}

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="local project directory")
    parser.add_argument("--port", type=int, default=35006, help="Studio HTTP link, not MCP HTTP")
    parser.add_argument("--build-plugin", type=Path, metavar="OUTPUT", help="write .rbxmx and exit")
    parser.add_argument("--install-plugin", action="store_true", help="install to Windows Roblox Plugins and exit")
    args = parser.parse_args()
    if args.build_plugin or args.install_plugin:
        destination = args.build_plugin
        if args.install_plugin:
            if sys.platform != "win32" or not os.environ.get("LOCALAPPDATA"):
                parser.error("automatic install is Windows-only; use --build-plugin and install manually")
            destination = Path(os.environ["LOCALAPPDATA"]) / "Roblox" / "Plugins" / "ScratchpadBridge.rbxmx"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(build_plugin(), encoding="utf-8", newline="\n")
        print(json.dumps({"plugin": str(destination)}))
        return
    if not args.project.is_dir():
        parser.error("--project must be an existing directory")
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be 1024..65535")
    create_mcp(Bridge(args.project, args.port)).run(transport="stdio")


if __name__ == "__main__":
    main()
