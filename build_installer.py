"""Собрать один самораспаковывающийся установщик из исходников рядом со скриптом."""
import base64
import hashlib
import io
from pathlib import Path
import tarfile


def build(destination):
    root = Path(__file__).resolve().parent
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for name in ("archmon", "tests", "docs", "README.md", "CHANGES.md", "LICENSE.md", "THIRD-PARTY.md"):
            path = root / name
            archive.add(path, arcname=name, filter=lambda info: None if
                        "__pycache__" in Path(info.name).parts or info.name.endswith(".pyc") else info)
    data = payload.getvalue()
    header = (root / "installer-header.sh").read_text().replace("@PAYLOAD_SHA256@", hashlib.sha256(data).hexdigest())
    encoded = base64.b64encode(data).decode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(header + "#__PAYLOAD__\n" +
                           "\n".join(encoded[i:i+100] for i in range(0, len(encoded), 100)) + "\n")
    destination.chmod(0o755)


if __name__ == "__main__":
    build(Path(__file__).resolve().parent / "install-archmon.sh")
