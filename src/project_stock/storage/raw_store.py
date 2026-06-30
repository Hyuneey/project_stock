from __future__ import annotations

from pathlib import Path


class RawStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, doc_id: str, suffix: str = ".txt") -> Path:
        return self.root / f"{doc_id}{suffix}"
