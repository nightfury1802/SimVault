import hashlib
from pathlib import Path


def get_namespace(project_root: Path) -> str:
    return hashlib.md5(str(project_root.resolve()).encode()).hexdigest()[:8]


def with_namespace(node_id: str, ns: str) -> str:
    return f"{ns}::{node_id}"


def strip_namespace(namespaced_id: str) -> str:
    return namespaced_id.split("::", 1)[-1]
