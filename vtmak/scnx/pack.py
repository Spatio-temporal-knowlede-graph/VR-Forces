"""golden 디렉터리 → `.scnx`(ZIP) 묶기.

`yewon_test/`는 VR-Forces가 풀어놓은 디렉터리다. Golden 파서는 `.scnx`(ZIP)를
읽으므로 필요할 때 여기서 묶는다. 800KB 바이너리를 저장소에 넣지 않고
디렉터리 원본만 두기 위해서다. 내용이 같으면 항상 같은 파일이 나온다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path


def ensure_golden(golden_dir, stem: str | None = None) -> Path:
    """디렉터리를 `<stem>.scnx`로 묶어 경로를 돌려준다.

    원본보다 새로우면 다시 묶는다. `.scnx`를 직접 주면 그대로 돌려준다.
    """
    p = Path(golden_dir)
    if p.is_file() and p.suffix == ".scnx":
        return p
    stem = stem or p.name
    out = p / f"{stem}.scnx"
    members = sorted(f for f in p.iterdir()
                     if f.is_file() and f.suffix != ".scnx")
    if not members:
        raise FileNotFoundError(f"golden 디렉터리가 비어 있다: {p}")
    if out.exists():
        newest = max(f.stat().st_mtime for f in members)
        if out.stat().st_mtime >= newest:
            return out
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in members:
            # 날짜를 고정해 같은 입력이면 같은 바이트가 나오게 한다.
            info = zipfile.ZipInfo(f.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    return out
