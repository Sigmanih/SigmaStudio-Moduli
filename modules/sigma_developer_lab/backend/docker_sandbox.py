import subprocess
import json

class DockerSandbox:
    def __init__(self):
        pass
    def status(self):
        return {"status": "online", "version": "20.10.0", "containers": 0}
    def list_containers(self):
        return []
    def create_container(self, image):
        pass
    def stop_container(self, container_id):
        pass
    def run_code(self, code, lang="python"):
        pass
