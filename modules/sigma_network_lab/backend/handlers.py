from fastapi import APIRouter
from .network_server import NetworkMCPServer

router = APIRouter()

@router.get("/search")
def search():
    return {"results": []}

@router.post("/request")
def make_request():
    return {"status": "ok"}

@router.get("/dns")
def get_dns():
    return {"records": []}

@router.get("/ping")
def ping():
    return {"status": "alive"}

def register_mcp(mcp_hub):
    mcp_hub.register(NetworkMCPServer())
