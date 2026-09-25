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
| 化学方程式 | `\ce{2H2 + O2 -> 2H2O}`（KaTeX mhchem），箭头条件用 `->[{上}][{下}]` |
| 结构式 | SMILES → 骨架式（键线式），支持手性 `@`、顺反 `/` `\`、芳香环、杂环 |
| 公式编号 | 在公式内写 `\tag{1.1}`，编号排在公式框右侧 |
| SVG | `![说明](figure.svg)` 直接内联矢量图，自动加图注、自适应宽度 |
| 代码高亮 | Pygments（Python-Markdown codehilite） |
| 样式 | `static/css` 下内置 5 套样式（浅色 / 深色），也可用任意 CSS |
| 目录 | 可选生成标题目录 |
| 输入 | 支持拖拽文件到窗口 |
| 界面 | PySide6 图形界面 + 命令行批量转换 |

## 化学内容怎么写

完整示例见 [`samples/chemistry-demo.md`](samples/chemistry-demo.md)。

### 反应方程式（mhchem）

写在 `$...$` 或 `$$...$$` 里：

```markdown
$$
\ce{2H2 + O2 -> 2H2O}
$$

$$
\ce{CH3CH2OH ->[{浓硫酸}][{$170^\circ$C}] CH2=CH2 ^ + H2O}
$$
```

几个容易踩的坑，程序都会在转换日志里点名提醒：

| 错误写法 | 为什么错 | 改成 |
| --- | --- | --- |
| `\ce{A \overset{cat}-> B}` | mhchem 不支持 `\overset` | `\ce{A ->[{cat}] B}` |
| `\ce{\underset{x}{C}O2}` | mhchem 不支持 `\underset` | 把 `\ce{}` 包进 `$...$` 后再叠 |
| `\ce{A ->[\text{cat}] B}` | 标注里不能再套 `\text{}` | `\ce{A ->[{cat}] B}` |
| `\ce{A ->[{170^\circ C}] B}` | 花括号里是正体文本，`^` 不算数学 | `\ce{A ->[{$170^\circ$C}] B}` |

> `$...$` 里是数学（斜体、可带上标），`{}` 里是正体文本（中文、单位）。
> 确实要把说明叠在结构上下方时，写成
> `$\underset{\text{还原}}{\ce{...}}$` —— `\underset` 必须在 `\ce{}` **外面**。

### 结构式（骨架式 / 键线式）

用 SMILES 一行文本描述分子，程序画出骨架式：

````markdown
```smiles # 阿司匹林
CC(=O)Oc1ccccc1C(=O)O
```

行内写法：苯环 \smiles{c1ccccc1}。
````

* 代码块标签：`smiles`（内联 SVG）或 `smiles-png`（导出 PNG 文件，便于插进 Word）。
* 图注写在 `#` 后面。
* 写在反引号里的 `` `\smiles{...}` `` 只当作语法示例，不会被渲染。

常用 SMILES：

| 结构 | SMILES | 结构 | SMILES |
| --- | --- | --- | --- |
| 乙醇 | `CCO` | 苯 | `c1ccccc1` |
| 乙酸 | `CC(=O)O` | 苯酚 | `Oc1ccccc1` |
| 丙酮 | `CC(=O)C` | 苯甲酸 | `OC(=O)c1ccccc1` |
| 乙酸乙酯 | `CCOC(=O)C` | 萘 | `c1ccc2ccccc2c1` |
| 环己烷 | `C1CCCCC1` | 吡啶 | `c1ccncc1` |
| L-丙氨酸 | `C[C@H](N)C(=O)O` | 呋喃 | `c1ccoc1` |
| 反-2-丁烯 | `C/C=C/C` | 噻吩 | `c1ccsc1` |

语法要点：单键省略，双键 `=`，三键 `#`；支链用圆括号 `CC(C)C`；
成环用数字配对 `C1CCCCC1`；芳香环用小写 `c n o s`；氢通常不用写。

### 把化学内容放进 Word

Word 的公式编辑器是 **OMML**，它不认 LaTeX，也没有 mhchem，
所以 `\ce{}` 这类写法**无法**直接在 Word 里排版；Word 原生也几乎不支持 SVG。
可行做法是导出成高清 PNG 再插入：

```bash
# 单个结构式，4 倍分辨率
python tools/chem/make_image.py "CC(=O)Oc1ccccc1C(=O)O" -o 阿司匹林.png --png --scale 4

# 批量：smiles.txt 每行一个 SMILES（可写“名称<TAB>SMILES”）
python tools/chem/make_image.py --file smiles.txt -o out\ --png --scale 4

# 矢量图（Word 版本较新时可直接插 SVG，无损缩放）
python tools/chem/make_image.py "c1ccccc1" -o 苯.svg
```

`samples/chemistry/` 下已预先生成了一批 PNG，可以直接拖进 Word 使用。

## 安装

需要 Python 3.10 以上（依赖 PySide6 的 abi3 wheel）。

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

公式预渲染需要本机有 [node](https://nodejs.org)：

```bash
cd tools/katex && npm install      # KaTeX 渲染桥
cd ../chem && npm install          # 结构式渲染桥（smiles-drawer + puppeteer-core）
```

没有 node 也能用，只是公式改为在浏览器里在线渲染（需要联网）。
结构式渲染还需要本机装有 Edge 或 Chrome（无头调用，不会弹窗）。

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
| `--no-structures` | 不渲染 SMILES 结构式，按原文保留 |
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
    converter.py        转换流水线（读取 → 结构式 → 保护公式 → 解析 → 还原 → 出页面）
    math.py             公式占位符的拆分与还原
    chem.py             SMILES 结构式渲染与占位替换
    mhchem_rules.py     化学式写法检查（\overset、标注内数学等）
    katex.py            常驻 Node 渲染进程的封装
    assets.py           KaTeX 样式与字体内嵌
    svg.py              SVG 内联与清理
    css.py              样式表发现与编码嗅探
    template.py         HTML 模板
static/css/             内置样式表
samples/                示例文档与已生成的结构式图片
tools/katex/render.js   KaTeX 渲染桥（node 侧）
tools/chem/render.js    结构式渲染桥（node 侧）
tools/chem/make_image.py 单张结构式导出工具
tools/verify/           无头浏览器渲染自检
tests/                  回归测试
```

## 测试

```bash
python tests/run_tests.py
```

覆盖公式拆分的各种边界（代码块、转义美元、未配对定界符、行尾 `$$`）、
结构正确性（标题层级、非法嵌套）、SVG 内联与清理、SMILES 结构式渲染与降级、
mhchem 写法检查、KaTeX 桥批量渲染。

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
* 结构式走的是 SMILES + 二维骨架式渲染：
  * **能画**：链状/支链、环、芳香环与杂环、官能团、手性楔形键、顺反异构、
    多环与常见药物分子；
  * **不能画**：三维构象、反应机理的弯箭头、配位键精细化、聚合物重复单元括号，
    以及名称到结构的自动转换（需要自己写 SMILES）。
* 内嵌字体后单个 HTML 约 350 KB 起步，公式越多、SVG 与结构式越多则越大。
* 结构式默认内联 SVG；用 `smiles-png` 代码块会另外在同级目录生成
  `<文档名>-assets/` 图片文件夹，方便单独拖进 Word。

## 许可

见 [LICENSE](LICENSE)。
