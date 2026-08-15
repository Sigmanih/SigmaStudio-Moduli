import json
from fastapi import APIRouter, Request

router = APIRouter()

def register_mcp(mcp_hub):
    try:
        from .messaging_server import MessagingMCPServer
        server = MessagingMCPServer()
        mcp_hub.register_server(server)
    except Exception as e:
        print(f"Failed to register MessagingMCPServer: {e}")

def setup(app):
    app.include_router(router, prefix="/api/messaging", tags=["Messaging"])
