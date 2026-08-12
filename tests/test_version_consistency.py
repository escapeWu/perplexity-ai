import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_python_and_web_versions_stay_in_sync():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version_match = re.search(
        r'(?m)^version\s*=\s*"(?P<version>[^"]+)"\s*$',
        pyproject,
    )
    assert version_match is not None, "pyproject.toml is missing project.version"

    package = json.loads((ROOT / "perplexity/server/web/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (ROOT / "perplexity/server/web/package-lock.json").read_text(encoding="utf-8")
    )

    versions = {
        "pyproject.toml": version_match.group("version"),
        "package.json": package["version"],
        "package-lock.json": package_lock["version"],
        "package-lock root package": package_lock["packages"][""]["version"],
    }
    assert len(set(versions.values())) == 1, f"Version metadata drifted: {versions}"


def test_curl_cffi_has_current_browser_fingerprints():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"curl_cffi>=0.15.0,<0.16.0"' in pyproject
