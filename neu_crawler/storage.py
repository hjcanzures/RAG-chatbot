"""Reading/writing documents and the manifest. Every write is a no-op in dry-run mode."""
import json
import os
from pathlib import Path


class Storage:
    def __init__(self, root, dry_run=False):
        self.root = Path(root)
        self.dry_run = dry_run
        self.manifest_path = self.root / "manifest.jsonl"

    def load_manifest(self):
        manifest = {}
        if self.manifest_path.exists():
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    manifest[entry["url"]] = entry
        return manifest

    def save_manifest(self, manifest):
        if self.dry_run:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            for url in sorted(manifest):
                f.write(json.dumps(manifest[url], ensure_ascii=False) + "\n")
        os.replace(tmp, self.manifest_path)

    def write(self, rel_path, text):
        if self.dry_run:
            return
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def remove(self, rel_path):
        if not self.dry_run:
            (self.root / rel_path).unlink(missing_ok=True)

    def exists(self, rel_path):
        return bool(rel_path) and (self.root / rel_path).is_file()

    def read_body(self, rel_path):
        """Document text without front matter and without the leading '# Title' line."""
        text = (self.root / rel_path).read_text(encoding="utf-8")
        if text.startswith("---\n"):
            end = text.find("\n---\n", 4)
            if end != -1:
                text = text[end + 5:]
        text = text.lstrip()
        if text.startswith("# "):
            text = text.split("\n", 1)[1] if "\n" in text else ""
        return text.strip()