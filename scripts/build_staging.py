from __future__ import annotations

import argparse
import hashlib
import json
import zipapp
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("dist/ocr-inbound-staging.pyz"))
    args = parser.parse_args()
    source = Path("src")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    zipapp.create_archive(source, target=args.out, main="ocr_inbound.__main__:main", compressed=True)
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    manifest = {"package": args.out.name, "sha256": digest, "bytes": args.out.stat().st_size, "entrypoint": "ocr_inbound.__main__:main", "environment": "staging", "live_ada_default": False, "production_save_default": False}
    args.out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
