import sys
from unittest.mock import MagicMock

# Mock the mcp package since it requires python >= 3.10 and we are running tests on 3.9
mock_mcp = MagicMock()
mock_fastmcp = MagicMock()
mock_fastmcp.FastMCP.return_value.tool = lambda: lambda f: f
mock_mcp.server.fastmcp = mock_fastmcp
sys.modules['mcp'] = mock_mcp
sys.modules['mcp.server'] = mock_mcp.server
sys.modules['mcp.server.fastmcp'] = mock_fastmcp
