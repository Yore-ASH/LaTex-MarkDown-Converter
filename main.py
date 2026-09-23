"""LaTeX MarkDown Converter —— 程序入口。

两种用法：

* 直接运行（或双击）打开图形界面：
      python main.py
      python main.py 文档.md
* 命令行批量转换，便于脚本调用：
      python main.py --cli 文档.md [--css 样式.css] [--out 输出目录]
                      [--no-svg] [--toc] [--footer] [--title 标题]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.converter import ConversionEngine, ConversionOptions  # noqa: E402

APP_NAME = "ASH Markdown Converter"
APP_VERSION = "2.0"
STATIC_ROOT = ROOT / "static"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="把含 LaTeX、SVG 的 Markdown 转换成单个自包含 HTML。",
    )
    parser.add_argument("files", nargs="*", help="要转换的 Markdown 文件")
    parser.add_argument("--cli", action="store_true", help="不打开界面，直接转换")
    parser.add_argument("--css", help="样式表路径，默认用 static 下 NoteStyle 中最新的一份")
    parser.add_argument("--out", help="输出目录，默认与源文件同目录")
    parser.add_argument("--title", help="覆盖页面标题，默认取文件名")
    parser.add_argument("--no-svg", action="store_true", help="不内联 SVG，保留图片引用")
    parser.add_argument("--toc", action="store_true", help="在正文开头生成目录")
    parser.add_argument("--footer", action="store_true", help="在页面底部附加署名")
    parser.add_argument("--quiet", action="store_true", help="只输出错误信息")
    parser.add_argument("--gui", action="store_true", help="强制打开图形界面")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser


def default_css() -> Path | None:
    from core.css import default_theme

    theme = default_theme(STATIC_ROOT)
    return theme.path if theme else None


def run_cli(args: argparse.Namespace) -> int:
    if not args.files:
        print("没有指定要转换的文件。用 --help 查看用法。", file=sys.stderr)
        return 2

    css_path = Path(args.css) if args.css else default_css()
    if css_path is not None and not css_path.is_file():
        print(f"样式表不存在：{css_path}", file=sys.stderr)
        return 2

    output_dir = Path(args.out) if args.out else None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0
    with ConversionEngine() as engine:
        for name in args.files:
            source = Path(name)
            if not source.is_file():
                print(f"跳过（找不到文件）：{source}", file=sys.stderr)
                exit_code = 1
                continue

            options = ConversionOptions(
                source=source,
                output=(output_dir / f"{source.stem}.html")
                if output_dir
                else source.with_suffix(".html"),
                css_path=css_path,
                embed_svg=not args.no_svg,
                document_title=args.title,
                add_footer=args.footer,
                add_toc=args.toc,
            )
            try:
                result = engine.convert(
                    options,
                    logger=None
                    if args.quiet
                    else lambda message, level="info": print(f"  {message}"),
                )
            except Exception as exc:  # noqa: BLE001 - 命令行逐个文件继续
                print(f"转换失败 {source.name}：{exc}", file=sys.stderr)
                exit_code = 1
                continue

            if not args.quiet:
                print(
                    f"完成 {result.output_path.name}："
                    f"公式 {result.math_inline + result.math_display} 处"
                    f"（失败 {result.math_failed}），"
                    f"SVG {result.svg_embedded} 个，"
                    f"{result.html_chars / 1024:.0f} KiB，"
                    f"{result.duration:.2f} 秒"
                )
            for warning in result.warnings:
                print(f"  提示：{warning}", file=sys.stderr)

    return exit_code


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    # 有文件参数且显式要求命令行时直接转换，避免在脚本里弹出窗口
    if args.cli:
        return run_cli(args)

    try:
        from gui import run_gui
    except ImportError as exc:
        print(f"无法加载图形界面（{exc}），改用命令行模式。", file=sys.stderr)
        return run_cli(args)

    return run_gui([sys.argv[0], *argv])


if __name__ == "__main__":
    raise SystemExit(main())
