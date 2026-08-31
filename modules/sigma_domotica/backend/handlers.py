from .homeassistant_server import HomeAssistantMCPServer

def register_mcp(mcp_hub):
    """Register HomeAssistant MCP server with the hub."""
    server = HomeAssistantMCPServer()
    mcp_hub.register_server(server)
    return server
