from fastapi import APIRouter
from .developer_server import DeveloperMCPServer

router = APIRouter()

@router.get("/docker/status")
def docker_status():
    return {"status": "ok"}

@router.get("/docker/containers")
def docker_containers():
    return []

@router.post("/docker/create")
def docker_create():
    return {"status": "created"}

@router.post("/docker/stop")
def docker_stop():
    return {"status": "stopped"}

@router.post("/run_code")
def run_code():
    return {"output": "ok"}

@router.post("/pytest")
def run_pytest():
    return {"results": "ok"}

@router.get("/git_status")
def git_status():
    return {"status": "clean"}

def register_mcp(mcp_hub):
    mcp_hub.register(DeveloperMCPServer())
