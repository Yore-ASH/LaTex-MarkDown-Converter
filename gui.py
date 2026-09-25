"""图形界面（PySide6）。

界面只负责收集参数与展示进度，转换逻辑全部在 core 包里，
因此命令行与图形界面走的是同一条代码路径。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, QUrl, Signal, Qt
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.converter import ConversionEngine, ConversionOptions
from core.css import Theme, default_theme, discover_themes, read_css
from core.katex import find_node

APP_NAME = "ASH Markdown Converter"
APP_VERSION = "2.0"
ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"


class ConversionWorker(QObject):
    """在后台线程里跑一次转换。"""

    progress = Signal(str)
    message = Signal(str, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, options: ConversionOptions):
        super().__init__()
        self.options = options

    def run(self) -> None:
        engine = ConversionEngine()
        try:
            result = engine.convert(
                self.options,
                progress=self.progress.emit,
                logger=lambda message, level="info": self.message.emit(message, level),
            )
        except Exception as exc:  # noqa: BLE001 - 交给界面统一提示
            import traceback

            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
        else:
            self.finished.emit(result)
        finally:
            engine.close()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("ASH", "MarkdownConverter")
        self.themes: list[Theme] = discover_themes(STATIC_ROOT)
        self.worker_thread: QThread | None = None
        self.worker: ConversionWorker | None = None
        self.last_output: Path | None = None

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(880, 620)
        self.setAcceptDrops(True)

        self._build_actions()
        self._build_ui()
        self._restore_settings()
        self._report_environment()

    # ------------------------------------------------------------- 界面构建

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")

        open_action = QAction("打开 Markdown(&O)", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.pick_markdown)
        file_menu.addAction(open_action)

        css_action = QAction("选择样式表(&S)", self)
        css_action.triggered.connect(self.pick_css)
        file_menu.addAction(css_action)

        out_action = QAction("选择输出目录(&D)", self)
        out_action.triggered.connect(self.pick_output_dir)
        file_menu.addAction(out_action)

        file_menu.addSeparator()

        convert_action = QAction("开始转换(&R)", self)
        convert_action.setShortcut(QKeySequence("Ctrl+Return"))
        convert_action.triggered.connect(self.start_conversion)
        file_menu.addAction(convert_action)

        reveal_action = QAction("打开输出位置", self)
        reveal_action.triggered.connect(self.reveal_output)
        file_menu.addAction(reveal_action)

        file_menu.addSeparator()
        quit_action = QAction("退出(&Q)", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        env_action = QAction("检查运行环境", self)
        env_action.triggered.connect(self.show_environment)
        help_menu.addAction(env_action)

        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(10)

        layout.addWidget(self._build_io_group())
        layout.addWidget(self._build_output_group())

        buttons = QHBoxLayout()
        self.convert_button = QPushButton("开始转换")
        self.convert_button.setMinimumHeight(38)
        self.convert_button.setMinimumWidth(150)
        self.convert_button.clicked.connect(self.start_conversion)
        buttons.addWidget(self.convert_button)

        self.open_button = QPushButton("打开结果")
        self.open_button.setMinimumHeight(38)
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_result)
        buttons.addWidget(self.open_button)

        self.reveal_button = QPushButton("打开输出目录")
        self.reveal_button.setMinimumHeight(38)
        self.reveal_button.setEnabled(False)
        self.reveal_button.clicked.connect(self.reveal_output)
        buttons.addWidget(self.reveal_button)

        buttons.addStretch(1)
        layout.addLayout(buttons)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._build_log_group())
        splitter.addWidget(self._build_help_group())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.setCentralWidget(central)

        status = QStatusBar(self)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedWidth(160)
        status.addPermanentWidget(self.progress)
        self.setStatusBar(status)

    def _build_io_group(self) -> QGroupBox:
        group = QGroupBox("输入")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)

        self.markdown_edit = QLineEdit()
        self.markdown_edit.setPlaceholderText("选择或拖入 .md / .markdown / .txt 文件")
        markdown_row = QHBoxLayout()
        markdown_row.addWidget(self.markdown_edit, 1)
        markdown_row.addWidget(self._small_button("浏览", self.pick_markdown))
        form.addRow("Markdown", self._wrap(markdown_row))

        self.css_edit = QLineEdit()
        self.css_edit.setPlaceholderText("留空则使用下拉框中选择的样式")
        css_row = QHBoxLayout()
        css_row.addWidget(self.css_edit, 1)
        css_row.addWidget(self._small_button("浏览", self.pick_css))
        css_row.addWidget(self._small_button("清除", lambda: self.css_edit.setText("")))
        form.addRow("自定义样式", self._wrap(css_row))

        self.theme_combo = QComboBox()
        for theme in self.themes:
            self.theme_combo.addItem(theme.label, theme)
        if not self.themes:
            self.theme_combo.addItem("使用内置基础样式", None)
        form.addRow("内置样式", self.theme_combo)

        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("输出与选项")
        layout = QVBoxLayout(group)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("留空表示与 Markdown 文件同目录")
        output_row.addWidget(QLabel("输出目录"))
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self._small_button("浏览", self.pick_output_dir))
        output_row.addWidget(self._small_button("跟随源文件", lambda: self.output_edit.setText("")))
        layout.addLayout(output_row)

        options = QGridLayout()
        self.embed_svg_box = QCheckBox("内联 SVG 图形")
        self.embed_svg_box.setChecked(True)
        self.embed_svg_box.setToolTip("把 ![](x.svg) 的图形内容直接写进 HTML")
        options.addWidget(self.embed_svg_box, 0, 0)

        self.embed_chem_box = QCheckBox("渲染结构式")
        self.embed_chem_box.setChecked(True)
        self.embed_chem_box.setToolTip(
            "把 ```smiles 代码块与 \\smiles{...} 渲染成骨架式（键线式）"
        )
        options.addWidget(self.embed_chem_box, 0, 1)

        self.auto_open_box = QCheckBox("转换后自动打开")
        self.auto_open_box.setChecked(True)
        options.addWidget(self.auto_open_box, 0, 2)

        self.footer_box = QCheckBox("页脚署名")
        self.footer_box.setToolTip("在页面底部附加文件名与生成工具说明")
        options.addWidget(self.footer_box, 1, 0)

        self.toc_box = QCheckBox("生成目录")
        self.toc_box.setToolTip("在正文开头插入标题目录")
        options.addWidget(self.toc_box, 1, 1)

        layout.addLayout(options)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._small_button("清空", self.clear_log))
        toolbar.addWidget(self._small_button("复制全部", self.copy_log))
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        log_font = QFont("Cascadia Mono", 10)
        log_font.setStyleHint(QFont.Monospace)
        log_font.setFamilies(["Cascadia Mono", "Consolas", "Courier New"])
        self.log_view.setFont(log_font)
        layout.addWidget(self.log_view)
        return group

    def _build_help_group(self) -> QGroupBox:
        group = QGroupBox("说明")
        layout = QVBoxLayout(group)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(
            """
            <style>
              body { font-family: "Microsoft YaHei UI", sans-serif; font-size: 13px; }
              code { background: #f2f2f2; padding: 1px 4px; }
              li { margin: 3px 0; }
            </style>
            <ul>
              <li><b>公式</b>：支持 <code>$...$</code> 与 <code>$$...$$</code>；
                  公式在转换时由 KaTeX 预渲染成 HTML 并内嵌字体，
                  生成的页面断网也能正常显示。</li>
              <li><b>编号</b>：在公式里写 <code>\\tag{1.1}</code>，编号会排在公式右侧。</li>
              <li><b>化学方程式</b>：用 <code>\\ce{2H2 + O2 -> 2H2O}</code>。
                  箭头标注写成 <code>\\ce{A ->[{上方}][{下方}] B}</code>，
                  <b>不要</b>用 <code>\\overset</code>/<code>\\underset</code>，
                  mhchem 不支持，写了会渲染成源码。</li>
              <li><b>结构式（键线式）</b>：用 SMILES 描述，例如
                  <code>```smiles # 阿司匹林</code> 代码块，或行内
                  <code>\\smiles{CC(=O)O}</code>。手性用 <code>@</code>，
                  顺反用 <code>/</code> 与 <code>\\</code>。</li>
              <li><b>SVG</b>：<code>![说明](figure.svg)</code> 会把图形内联到页面中，
                  路径相对 Markdown 文件或输出目录解析。</li>
              <li><b>美元符号</b>：写作 <code>\\$</code> 可避免被当作公式起始；
                  <code>$100</code> 这类金额会被自动识别。</li>
              <li><b>分隔线</b>：单独一行写 <code>---</code> 会输出为分隔线，
                  不会被误认成标题。</li>
              <li><b>拖拽</b>：把 Markdown 文件直接拖到窗口即可载入。</li>
            </ul>
            """
        )
        layout.addWidget(browser)
        return group

    @staticmethod
    def _wrap(layout) -> QWidget:
        holder = QWidget()
        holder.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return holder

    def _small_button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setMaximumWidth(96)
        button.clicked.connect(slot)
        return button

    # ------------------------------------------------------------- 设置读写

    def _restore_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.markdown_edit.setText(self.settings.value("last_markdown", "", str))
        self.output_edit.setText(self.settings.value("output_dir", "", str))
        self.auto_open_box.setChecked(self.settings.value("auto_open", True, bool))
        self.embed_svg_box.setChecked(self.settings.value("embed_svg", True, bool))
        self.embed_chem_box.setChecked(self.settings.value("embed_structures", True, bool))
        self.footer_box.setChecked(self.settings.value("add_footer", False, bool))

        saved_css = self.settings.value("css_path", "", str)
        if saved_css and Path(saved_css).is_file():
            self.css_edit.setText(saved_css)

        theme_path = self.settings.value("theme_path", "", str)
        if theme_path:
            for index in range(self.theme_combo.count()):
                theme = self.theme_combo.itemData(index)
                if theme is not None and str(theme.path) == theme_path:
                    self.theme_combo.setCurrentIndex(index)
                    break
        elif self.themes:
            preferred = default_theme(STATIC_ROOT)
            if preferred is not None:
                for index in range(self.theme_combo.count()):
                    theme = self.theme_combo.itemData(index)
                    if theme is not None and theme.path == preferred.path:
                        self.theme_combo.setCurrentIndex(index)
                        break

    def _save_settings(self) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("last_markdown", self.markdown_edit.text())
        self.settings.setValue("output_dir", self.output_edit.text())
        self.settings.setValue("auto_open", self.auto_open_box.isChecked())
        self.settings.setValue("embed_svg", self.embed_svg_box.isChecked())
        self.settings.setValue("embed_structures", self.embed_chem_box.isChecked())
        self.settings.setValue("add_footer", self.footer_box.isChecked())
        self.settings.setValue("css_path", self.css_edit.text())
        theme = self.theme_combo.currentData()
        self.settings.setValue("theme_path", str(theme.path) if theme is not None else "")

    # ------------------------------------------------------------- 交互

    def pick_markdown(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Markdown 文件",
            self.markdown_edit.text() or str(Path.home()),
            "Markdown (*.md *.markdown *.txt);;所有文件 (*)",
        )
        if path:
            self.set_markdown_path(path)

    def set_markdown_path(self, path: str) -> None:
        self.markdown_edit.setText(path)
        self.log(f"已载入：{Path(path).name}", "success")

    def pick_css(self) -> None:
        start = self.css_edit.text() or str(STATIC_ROOT)
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 CSS 样式表", start, "CSS (*.css);;所有文件 (*)"
        )
        if path:
            self.css_edit.setText(path)
            self.log(f"已选择样式表：{Path(path).name}", "info")

    def pick_output_dir(self) -> None:
        start = self.output_edit.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", start)
        if path:
            self.output_edit.setText(path)

    def clear_log(self) -> None:
        self.log_view.clear()

    def copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())

    def log(self, message: str, level: str = "info") -> None:
        colors = {
            "info": "#1a1a1a",
            "success": "#1a7f37",
            "warning": "#9a6700",
            "error": "#b42318",
        }
        color = colors.get(level, "#1a1a1a")
        escaped = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        self.log_view.appendHtml(f'<span style="color:{color}">{escaped}</span>')
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    # ------------------------------------------------------------- 拖拽

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and path.lower().endswith((".md", ".markdown", ".txt")):
                self.set_markdown_path(path)
                event.acceptProposedAction()
                return
        self.log("拖入的文件不是 Markdown 文件", "warning")

    # ------------------------------------------------------------- 转换

    def _collect_options(self) -> ConversionOptions | None:
        source_text = self.markdown_edit.text().strip()
        if not source_text:
            QMessageBox.warning(self, "缺少输入", "请先选择要转换的 Markdown 文件。")
            return None
        source = Path(source_text)
        if not source.is_file():
            QMessageBox.critical(self, "文件不存在", f"找不到文件：\n{source}")
            return None

        output_dir_text = self.output_edit.text().strip()
        output = None
        if output_dir_text:
            output = Path(output_dir_text) / f"{source.stem}.html"
        else:
            output = source.with_suffix(".html")

        css_path = None
        custom = self.css_edit.text().strip()
        if custom:
            candidate = Path(custom)
            if candidate.is_file():
                css_path = candidate
            else:
                self.log(f"自定义样式不存在，改用内置样式：{custom}", "warning")
        if css_path is None:
            theme = self.theme_combo.currentData()
            if theme is not None:
                css_path = theme.path

        return ConversionOptions(
            source=source,
            output=output,
            css_path=css_path,
            embed_svg=self.embed_svg_box.isChecked(),
            add_footer=self.footer_box.isChecked(),
        )

    def start_conversion(self) -> None:
        if self.worker_thread is not None and self.worker_thread.isRunning():
            self.log("正在转换中，请稍候", "warning")
            return

        options = self._collect_options()
        if options is None:
            return

        self.log(f"开始转换：{options.source.name}", "info")
        self.convert_button.setEnabled(False)
        self.progress.setVisible(True)
        self.statusBar().showMessage("正在转换…")

        self.worker_thread = QThread(self)
        self.worker = ConversionWorker(options)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.message.connect(self.log)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    def _cleanup_worker(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
        self.worker = None
        self.worker_thread = None
        self.convert_button.setEnabled(True)
        self.progress.setVisible(False)

    def _on_progress(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _on_finished(self, result) -> None:
        self.last_output = Path(result.output_path)
        self.open_button.setEnabled(True)
        self.reveal_button.setEnabled(True)

        self.log(
            f"完成：{self.last_output.name}"
            f"（公式 {result.math_inline + result.math_display} 处"
            + (f"，结构式 {result.structures} 个" if result.structures else "")
            + (f"，SVG {result.svg_embedded} 个" if result.svg_embedded else "")
            + f"，用时 {result.duration:.2f} 秒）",
            "success",
        )
        self.log(
            f"体积：源 {result.markdown_chars / 1024:.0f} KiB → "
            f"HTML {result.html_chars / 1024:.0f} KiB",
            "info",
        )
        if result.math_failed:
            self.log(
                f"有 {result.math_failed} 处公式未能预渲染，页面中显示原始写法", "warning"
            )
        self.statusBar().showMessage(f"转换完成：{self.last_output.name}")

        if self.auto_open_box.isChecked():
            self.open_result()

    def _on_failed(self, message: str) -> None:
        self.log(f"转换失败：{message}", "error")
        self.statusBar().showMessage("转换失败")
        QMessageBox.critical(self, "转换失败", message)

    def open_result(self) -> None:
        if self.last_output and self.last_output.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def reveal_output(self) -> None:
        target = self.last_output or Path(self.markdown_edit.text().strip() or ".")
        folder = target if target.is_dir() else target.parent
        if not folder.is_dir():
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", str(folder)], creationflags=0x08000000)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------- 帮助

    def _report_environment(self) -> None:
        from core.chem import find_browser

        node = find_node()
        self.log(f"{APP_NAME} {APP_VERSION} 已就绪", "info")
        if node:
            self.log(f"公式预渲染引擎：{node}", "info")
        else:
            self.log("未找到 node，公式将改用在线渲染，请保持联网", "warning")

        browser = find_browser()
        if browser:
            self.log(f"结构式渲染浏览器：{Path(browser).name}", "info")
        else:
            self.log("未找到 Edge / Chrome，结构式将显示 SMILES 原文", "warning")

        if not self.themes:
            self.log("static 目录下没有找到样式表，将使用内置基础样式", "warning")

    def show_environment(self) -> None:
        from core.assets import find_katex_dir
        from core.chem import check_environment as check_chem_environment, find_browser
        from core.converter import check_katex_environment

        katex_dir = find_katex_dir()
        lines = [f"Python：{sys.version.split()[0]}", f"程序目录：{ROOT}"]
        lines.append(f"Node：{find_node() or '未找到'}")
        lines.append(f"KaTeX：{katex_dir or '未找到'}")
        ok, detail = check_katex_environment(katex_dir)
        lines.append(f"公式预渲染自检：{'通过' if ok else '失败'}")
        if not ok:
            lines.append(f"原因：{detail}")

        lines.append(f"结构式浏览器：{find_browser() or '未找到'}")
        chem_ok, chem_detail = check_chem_environment()
        lines.append(f"结构式渲染自检：{'通过' if chem_ok else '未启用'}")
        if not chem_ok:
            lines.append(f"原因：{chem_detail}")

        if self.themes:
            lines.append("可用样式：")
            lines.extend(f"  · {theme.label}（{theme.path.name}）" for theme in self.themes)
        QMessageBox.information(self, "运行环境", "\n".join(lines))

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            f"<b>{APP_NAME}</b> {APP_VERSION}<br><br>"
            "把带 LaTeX、化学式与 SVG 的 Markdown 转成单个自包含 HTML。<br>"
            "数学公式在转换阶段预渲染并内嵌字体，页面离线可用；<br>"
            "SMILES 结构式（骨架式/键线式）由本机浏览器无头渲染成 SVG。<br><br>"
            "作者：Yore.ASH<br>"
            "技术栈：Python · PySide6 · Python-Markdown · KaTeX · mhchem · smiles-drawer",
        )

    # ------------------------------------------------------------- 生命周期

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self.worker_thread is not None and self.worker_thread.isRunning():
            answer = QMessageBox.question(
                self,
                "仍在转换",
                "转换尚未结束，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.worker_thread.quit()
            self.worker_thread.wait(3000)
        self._save_settings()
        event.accept()


def run_gui(argv: list[str]) -> int:
    from PySide6.QtGui import QFontDatabase

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    available = set(QFontDatabase.families())
    for family in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC"):
        if family in available:
            font = QFont(family, 10)
            app.setFont(font)
            break

    window = MainWindow()
    window.show()

    for argument in argv[1:]:
        if argument.lower().endswith((".md", ".markdown", ".txt")):
            window.set_markdown_path(argument)
            break

    return app.exec()


__all__ = ["MainWindow", "run_gui", "APP_NAME", "APP_VERSION"]
