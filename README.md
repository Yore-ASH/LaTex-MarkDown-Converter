# LaTeX MarkDown Converter

把含有 LaTeX 公式与 SVG 图形的 Markdown，转换成**一个自包含的 HTML 文件**。

> **作者**：Yore.ASH
> **版本**：2.0
> **界面**：PySide6

## 这个程序解决什么问题

Markdown 本身不认公式，很多转换工具的做法是先把 `$...$` 塞进 HTML 标签再交给
Markdown 解析器，结果常常出现三类毛病：

1. 块级公式被塞进 `<p>` 里，浏览器强行闭合标签，正文与标题层级跟着乱掉；
2. 解析器把公式里的 `_`、`*` 当成强调符号，公式源码裸露在页面上；
3. 页面靠外部 CDN 现场渲染公式，量大时卡顿、断网时直接不显示。

本程序换了一条路：**先把公式抽成占位符**，让 Markdown 解析器完全看不到 `$`；
等 Markdown 解析结束后，再把公式替换成**转换阶段就已经渲染好的 KaTeX 结果**，
并把 KaTeX 字体以 data URI 内嵌进 HTML。因此：

* 不会再有非法嵌套，标题层级稳定；
* 公式不会被 Markdown 语法咬坏；
* 生成的 HTML 双击即可打开，**断网、换机器都能正常显示**；
* 打开页面不执行任何渲染脚本，长文档也不会卡。

## 功能

| 功能 | 说明 |
| --- | --- |
| 公式 | `$...$` 行内、`$$...$$` 块级，支持 `\begin{aligned}` 等多行环境 |
| 化学式 | `\ce{2H2 + O2 -> 2H2O}`（KaTeX mhchem） |
| 公式编号 | 在公式内写 `\tag{1.1}`，编号排在公式框右侧 |
| SVG | `![说明](figure.svg)` 直接内联矢量图，自动加图注、自适应宽度 |
| 代码高亮 | Pygments（Python-Markdown codehilite） |
| 样式 | `static/css` 下内置 5 套样式（浅色 / 深色），也可用任意 CSS |
| 目录 | 可选生成标题目录 |
| 输入 | 支持拖拽文件到窗口 |
| 界面 | PySide6 图形界面 + 命令行批量转换 |

## 安装

需要 Python 3.10 以上（依赖 PySide6 的 abi3 wheel）。

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

公式预渲染需要本机有 [node](https://nodejs.org)，并把 KaTeX 装到 `tools/katex`：

```bash
cd tools/katex
npm install
```

没有 node 也能用，只是公式改为在浏览器里在线渲染（需要联网）。

## 使用

### 图形界面

```bash
python main.py
python main.py 我的文档.md        # 启动时直接载入
```

窗口里选择 Markdown 与样式，点「开始转换」。转换在后台线程执行，
长文档不会把界面卡住；日志区会给出公式数量、失败数量与耗时。

### 命令行

```bash
python main.py --cli 文档.md
python main.py --cli 文档.md --out dist --toc --footer
python main.py --cli *.md --css static/css/ServerStyle/3-0.css --quiet
```

| 参数 | 作用 |
| --- | --- |
| `--cli` | 不打开界面，直接转换 |
| `--css` | 指定样式表，默认取 `static` 下 NoteStyle 中最新的一份 |
| `--out` | 输出目录，默认与源文件同目录 |
| `--title` | 覆盖页面标题 |
| `--toc` / `--footer` | 生成目录 / 附加页脚 |
| `--no-svg` | 不内联 SVG，保留 `<img>` 引用 |
| `--quiet` | 只输出错误 |

## 写作约定

* `$100`、`US$100` 这类金额不会被当成公式；确实要显示美元符号时写 `\$`。
* 行内公式的 `$` 需要「贴着」内容：`$x$` 有效，`$ x $` 不解析为公式。
* 单独一行写 `---` 会输出为分隔线，不会再被误判成标题。
* `$$` 必须成对出现；落单的 `$$` 会按普通文本原样保留。

## 目录结构

```
main.py                 入口：参数解析、命令行模式
gui.py                  PySide6 图形界面
core/
    converter.py        转换流水线（读取 → 保护公式 → 解析 → 还原 → 出页面）
    math.py             公式占位符的拆分与还原
    katex.py            常驻 Node 渲染进程的封装
    assets.py           KaTeX 样式与字体内嵌
    svg.py              SVG 内联与清理
    css.py              样式表发现与编码嗅探
    template.py         HTML 模板
static/css/             内置样式表
tools/katex/render.js   KaTeX 渲染桥（node 侧）
tools/verify/           无头浏览器渲染自检
tests/                  回归测试
```

## 测试

```bash
python tests/run_tests.py
```

覆盖公式拆分的各种边界（代码块、转义美元、未配对定界符、行尾 `$$`）、
结构正确性（标题层级、非法嵌套）、SVG 内联与清理、KaTeX 桥批量渲染。

如果本机装了 Edge 或 Chrome，还可以用真实浏览器复核生成结果：

```bash
python main.py --cli 文档.md
node tools/verify/render_check.js "file:///绝对路径/文档.html" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

它会返回公式渲染数量、失败数量、控制台报错以及是否存在非法嵌套。

## 已知边界

* 缩进 4 空格以上的代码块内的 `$` 不做公式处理，但也因此不会保护
  跨行的行内代码段（`` ` `` 跨行的情况极少见）。
* 预渲染依赖 KaTeX 的语法支持范围；KaTeX 不支持的命令会被标记为
  `math-error`，并在日志里给出原始公式，便于定位。
* 内嵌字体后单个 HTML 约 350 KB 起步，公式越多、SVG 越多则越大。

## 许可

见 [LICENSE](LICENSE)。
