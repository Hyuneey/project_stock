from __future__ import annotations

from pathlib import Path

import pandas as pd


class ParquetStore:
    """Small Parquet-ready adapter used by future data collectors."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_frame(self, name: str, frame: pd.DataFrame) -> Path:
        path = self.root / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        return path

    def read_frame(self, name: str) -> pd.DataFrame:
        return pd.read_parquet(self.root / f"{name}.parquet")
