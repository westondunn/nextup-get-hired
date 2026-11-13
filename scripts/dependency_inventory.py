"""Offline lockfile origin/hash review; this is not a vulnerability database scan."""

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory(root=ROOT):
    python_lock = root / "backend/uv.lock"
    node_lock = root / "frontend/package-lock.json"
    python = []
    for package in tomllib.loads(python_lock.read_text())["package"]:
        if package["source"].get("virtual") == ".":
            continue
        assert package["source"].get("registry") == "https://pypi.org/simple", package["name"]
        artifacts = package.get("wheels", []) + ([package["sdist"]] if "sdist" in package else [])
        assert artifacts, f"No hashed artifacts for {package['name']}"
        for artifact in artifacts:
            assert artifact["url"].startswith("https://files.pythonhosted.org/")
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["hash"])
        python.append({"name": package["name"], "version": package["version"]})
    node = []
    for path, package in json.loads(node_lock.read_text())["packages"].items():
        if not path:
            continue
        assert package.get("resolved", "").startswith("https://registry.npmjs.org/"), path
        assert package.get("integrity", "").startswith("sha512-"), path
        node.append({"path": path, "version": package["version"], "dev": package.get("dev", False)})
    return {
        "scope": "Offline origin/hash inventory only; CVE status not checked",
        "lock_hashes": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (python_lock, node_lock)
        },
        "python": python,
        "node": node,
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), indent=2))
