from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.main import app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the FastAPI OpenAPI document deterministically.")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "frontend" / "openapi.json",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.write_bytes(rendered.encode("utf-8"))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
