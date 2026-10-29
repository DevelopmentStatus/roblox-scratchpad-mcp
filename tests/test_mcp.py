"""Real stdio transport test; no live Studio or place edits."""

import asyncio
from pathlib import Path
import socket
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPTests(unittest.TestCase):
    def test_stdio_discovery_and_readonly_call(self):
        async def run():
            with tempfile.TemporaryDirectory(dir=Path.cwd()) as project:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                parameters = StdioServerParameters(command=sys.executable, args=[
                    "-m", "scratchpad_mcp", "--project", project, "--port", str(port)
                ])
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listing = await session.list_tools()
                        names = {tool.name for tool in listing.tools}
                        self.assertEqual(len(names), 8)
                        self.assertIn("scratchpad_execute", names)
                        result = await session.call_tool("scratchpad_status", {})
                        self.assertFalse(result.isError)
                        result = await session.call_tool("scratchpad_write_file", {
                            "path": "ReplicatedStorage/Test.luau", "source": "return 1"
                        })
                        self.assertTrue(result.isError)  # no selected Studio
                        self.assertFalse((Path(project) / ".scratchpad-bridge/work/ReplicatedStorage/Test.luau").exists())
                # Server lifespan must release its HTTP socket after MCP disconnect.
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", port))
        asyncio.run(asyncio.wait_for(run(), timeout=25))


if __name__ == "__main__":
    unittest.main()
