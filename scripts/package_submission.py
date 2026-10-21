"""Build a source/evidence-only ZIP; never copy dependency trees or Docker volumes."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("app", "tests", "scripts", "docs", "diagnostics", "experiments", "grafana", "filebeat",
               "proto", "client", "grpc_server")
FILES = ("README.md", "requirements.txt", "Dockerfile", "docker-compose.yml",
         "docker-compose.experiment.yml", "prometheus.yml", ".gitignore", ".dockerignore", "Assignment-1.pdf")
BLOCKED = {".venv", "venv", "env", "node_modules", "site-packages", "__pycache__", ".pytest_cache",
           ".git", ".vscode", "data", "volumes", "volume-backups", "submission"}
SUFFIXES = {".py", ".js", ".cjs", ".css", ".html", ".md", ".tex", ".json", ".yml", ".yaml",
            ".txt", ".log", ".ndjson", ".kql", ".png", ".jpg", ".jpeg", ".svg", ".pdf"}


def main():
    assert (ROOT / "experiments/control/latency.txt").read_text().strip() == "DISABLED", "Disable the latency fault before packaging"
    files = [ROOT / name for name in FILES]
    for dirname in DIRECTORIES:
        for path in (ROOT / dirname).rglob("*"):
            relative = path.relative_to(ROOT)
            if (path.is_file() and not path.is_symlink() and ROOT in path.resolve().parents
                    and not any(part in BLOCKED or part.endswith(".egg-info") or part.startswith(".env") for part in relative.parts)
                    and path.suffix.lower() in SUFFIXES):
                files.append(path)
    destination = ROOT / "submission"
    destination.mkdir(exist_ok=True)
    archive = destination / "assignment1.zip"
    manifest = []
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(set(files)):
            relative = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            output.writestr(relative, data)
            manifest.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    with zipfile.ZipFile(archive) as output:
        assert output.testzip() is None
        for name in output.namelist():
            assert not any(part in BLOCKED for part in Path(name).parts)
            assert Path(name).suffix.lower() not in {".db", ".sqlite", ".sqlite3", ".pyc", ".whl", ".vhdx", ".tar", ".gz"}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"archive": str(archive), "files": len(manifest), "compressed_bytes": archive.stat().st_size,
                      "archive_integrity": "PASS", "dependency_and_runtime_exclusions": "PASS"}, indent=2))


if __name__ == "__main__":
    main()
