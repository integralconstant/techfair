"""Stable, non-secret identity for a local installation (no model imports)."""

import hashlib
import os
from pathlib import Path

SERVICE_ID = "scalp-ai-demo"


def installation_id(root: Path) -> str:
    normalized = os.path.normcase(str(Path(root).resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
