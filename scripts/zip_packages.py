"""Zip build/<function>/ into build/<function>.zip for Lambda (called by `make package`).

Why zips: on Windows without Docker, `sam build` drops the Linux .so files from the prebuilt
packages (observed with SAM CLI 1.161.1), which would break numpy/shapely in Lambda. The template's
CodeUri points at these zips and `make deploy` runs `sam deploy` without `sam build`.
Files get mode 0644 and directories 0755 so Lambda can read them.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

BUILD = Path(__file__).resolve().parent.parent / "build"


def zip_dir(src: Path, dest: Path) -> tuple[int, int]:
    n_files = n_so = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(src.rglob("*")):
            rel = p.relative_to(src).as_posix()
            if p.is_dir():
                info = zipfile.ZipInfo(rel + "/")
                info.external_attr = (0o40755 << 16) | 0x10
                z.writestr(info, b"")
                continue
            info = zipfile.ZipInfo(rel, date_time=(2026, 10, 10, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
            n_files += 1
            n_so += ".so" in p.name
    return n_files, n_so


def main(functions: list[str]) -> int:
    for fn in functions:
        src = BUILD / fn
        if any(src.rglob("*.pyd")) or any(src.rglob("*.dll")):
            print(f"{fn}: Windows binaries found in the package; refusing to zip")
            return 1
        n, so = zip_dir(src, BUILD / f"{fn}.zip")
        size = (BUILD / f"{fn}.zip").stat().st_size / 1e6
        print(f"build/{fn}.zip: {n} files, {so} Linux .so, {size:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["scan", "api", "draft"]))
