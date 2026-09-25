"""结构式小工具：把 SMILES 直接导成 SVG / PNG。

用法：
    python tools/chem/make_image.py "CC(=O)O" -o 乙酸.png
    python tools/chem/make_image.py "c1ccccc1" -o 苯.svg --theme dark
    python tools/chem/make_image.py --file smiles.txt -o out/     # 每行一个 SMILES
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.chem import ChemRenderer, find_browser  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make_image.py",
        description="把 SMILES 渲染成结构式图片（SVG 或 PNG）。",
    )
    parser.add_argument("smiles", nargs="*", help="SMILES 字符串，可给多个")
    parser.add_argument("--file", help="从文件读取 SMILES，每行一个（可写 名称<TAB>SMILES）")
    parser.add_argument("-o", "--out", default="structure", help="输出文件名或目录")
    parser.add_argument("--png", action="store_true", help="输出 PNG（默认 SVG）")
    parser.add_argument("--scale", type=float, default=3, help="PNG 放大倍数，默认 3")
    parser.add_argument("--theme", default="light", choices=["light", "dark"], help="配色")
    parser.add_argument("--width", type=int, default=420)
    parser.add_argument("--height", type=int, default=320)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    items: list[tuple[str, str]] = []
    for smiles in args.smiles:
        items.append(("", smiles))
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" in line:
                name, value = line.split("\t", 1)
                items.append((name.strip(), value.strip()))
            else:
                items.append(("", line))

    if not items:
        parser.error("没有给出 SMILES")

    browser = find_browser()
    if not browser:
        print("未找到 Edge / Chrome，无法渲染结构式。", file=sys.stderr)
        return 2

    renderer = ChemRenderer(browser=browser)
    if not renderer.available:
        print(renderer.unavailable_reason, file=sys.stderr)
        return 2

    out = Path(args.out)
    is_dir = len(items) > 1 or out.is_dir() or args.out.endswith(("/", "\\"))
    if is_dir:
        out.mkdir(parents=True, exist_ok=True)

    requests = [
        {
            "smiles": smiles,
            "mode": "png" if args.png else "svg",
            "theme": args.theme,
            "width": args.width,
            "height": args.height,
            "scale": args.scale,
        }
        for _, smiles in items
    ]
    results = renderer.render_many(requests)
    renderer.close()

    exit_code = 0
    for index, ((name, smiles), data) in enumerate(zip(items, results)):
        if data.get("error") and not data.get("svg") and not data.get("png"):
            print(f"渲染失败：{smiles}（{data['error']}）", file=sys.stderr)
            exit_code = 1
            continue

        extension = "png" if args.png else "svg"
        if is_dir:
            label = name or f"structure-{index + 1}"
            safe = "".join(ch for ch in label if ch.isalnum() or ch in "._-（）()") or f"s{index + 1}"
            target = out / f"{safe}.{extension}"
        else:
            target = out.with_suffix("." + extension) if out.suffix else out.with_name(
                out.name + "." + extension
            )
            target.parent.mkdir(parents=True, exist_ok=True)

        if args.png:
            target.write_bytes(base64.b64decode(data["png"]))
        else:
            target.write_text(data["svg"], encoding="utf-8")

        if not args.quiet:
            bbox = f"{data.get('width')}x{data.get('height')}"
            print(f"已写出 {target}  {bbox}  {target.stat().st_size / 1024:.1f} KiB  ({smiles})")
        if data.get("error"):
            print(f"  注意：{data['error']}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
