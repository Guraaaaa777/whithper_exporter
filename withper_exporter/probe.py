"""取得元フォルダを下調べして、設定の当たりを付けるための診断。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from .sources.whisperdir import SUPPORTED_SUFFIXES

MAX_SCAN = 2000


def probe_path(path: Path, limit: int = 5) -> str:
    path = Path(path).expanduser()
    lines: list[str] = [f"調査対象: {path}"]

    if not path.exists():
        lines.append("→ 見つかりません。パスを確認してください。")
        return "\n".join(lines)

    files = _collect(path)
    if not files:
        lines.append("→ ファイルが1つもありません。")
        return "\n".join(lines)

    suffixes = Counter(p.suffix.lower() for p in files)
    supported = [p for p in files if p.suffix.lower() in SUPPORTED_SUFFIXES]
    stats = sorted(((p, p.stat().st_mtime) for p in files), key=lambda x: x[1])

    lines.append(f"ファイル数: {len(files)}" + ("（先頭2000件まで）" if len(files) >= MAX_SCAN else ""))
    lines.append("拡張子: " + ", ".join(f"{s or '(なし)'}={n}" for s, n in suffixes.most_common()))
    lines.append(f"whisperdir で拾える数: {len(supported)}")
    lines.append(f"更新時刻の範囲: {_fmt(stats[0][1])} 〜 {_fmt(stats[-1][1])}")

    lines.append("")
    lines.append(f"最近のファイル（最大{limit}件）:")
    for file_path, mtime in stats[-limit:][::-1]:
        lines.append(f"  {_fmt(mtime)}  {file_path.name}  ({_size(file_path)})")
        preview = _preview(file_path)
        if preview:
            lines.append(f"      {preview}")

    lines.append("")
    lines.append("設定の目安:")
    lines.append("  [source]")
    lines.append('  type = "whisperdir"')
    lines.append(f"  path = '{path}'")
    if suffixes and not supported:
        lines.append("  [source.options]")
        lines.append(
            "  suffixes = ["
            + ", ".join(f'"{s}"' for s, _ in suffixes.most_common(3) if s)
            + "]  # 既定の拡張子に該当なし。必要なら指定"
        )
    return "\n".join(lines)


def _collect(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files: list[Path] = []
    for candidate in path.rglob("*"):
        if candidate.is_file():
            files.append(candidate)
            if len(files) >= MAX_SCAN:
                break
    return files


def _fmt(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def _size(path: Path) -> str:
    size = path.stat().st_size
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}MB"


def _preview(path: Path, length: int = 70) -> str:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read(400)
    except OSError:
        return ""
    flat = " ".join(text.split())
    if not flat:
        return "(空)"
    return flat[:length] + ("…" if len(flat) > length else "")
