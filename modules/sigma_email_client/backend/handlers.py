import json
from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/inbox")
async def get_inbox(request: Request):
    return {"status": "success", "data": []}

@router.post("/send")
async def send_email(request: Request):
    return {"status": "success"}

@router.post("/config")
async def update_config(request: Request):
    return {"status": "success"}

def register_mcp(mcp_hub):
    try:
        from .email_server import EmailMCPServer
        server = EmailMCPServer()
        mcp_hub.register_server(server)
    except Exception as e:
        print(f"Failed to register EmailMCPServer: {e}")

def setup(app):
    app.include_router(router, prefix="/api/email", tags=["Email"])
