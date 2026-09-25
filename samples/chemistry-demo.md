# 有机化学笔记

这份文件演示本程序的化学写法，可以直接编译看看效果：

```
python main.py --cli samples/chemistry-demo.md
```

## 反应方程式

mhchem 语法，写在 `$...$` 或 `$$...$$` 里。

酸碱中和：

$$
\ce{HCl + NaOH -> NaCl + H2O}
$$

燃烧与沉淀：

$$
\ce{CH4 + 2O2 -> CO2 + 2H2O}
$$

$$
\ce{SO4^2- + Ba^2+ -> BaSO4 v}
$$

同位素与电荷：

$$
\ce{^{14}C} \quad \ce{SO4^2-} \quad \ce{[Cu(NH3)4]^2+}
$$

### 箭头上标注条件

箭头**上方**用第一个方括号，**下方**用第二个方括号。
花括号 `{}` 里是**正体文本**（比如中文），要写数学（上下标、`\circ`）得再用 `$...$` 包一层：

$$
\ce{CH3CH2OH ->[{浓硫酸}][{$170^\circ$C}] CH2=CH2 ^ + H2O}
$$

可逆反应：

$$
\ce{N2 + 3H2 <=>[{催化剂}][{高温高压}] 2NH3}
$$

带斜体数学变量的标注用 `$...$`：

$$
\ce{A ->[$\Delta$] B}
$$

> **两个常见错误**：
> 1. `\ce{A \overset{cat}-> B}` 或 `\ce{\underset{x}{C}O2}` —— mhchem 不支持
>    `\overset` / `\underset`，会直接解析失败；
> 2. `\ce{A ->[\text{cat}] B}` 与 `\ce{A ->[{170^\circ C}] B}` —— 箭头标注里
>    不能再套 `\text{}`，花括号内的 `^` `_` `\circ` 也不当数学处理，会报错或渲染成乱码。
>
> 以上三种写法程序都会在转换日志里点名提醒，并给出替换写法。

## 结构式（骨架式 / 键线式）

用 SMILES 描述分子。SMILES 是一行文本，程序会画出骨架式。

```smiles # 乙酸
CC(=O)O
```

```smiles # 苯
c1ccccc1
```

```smiles # 阿司匹林
CC(=O)Oc1ccccc1C(=O)O
```

```smiles # 葡萄糖（吡喃环）
OCC1OC(O)C(O)C(O)C1O
```

```smiles # 咖啡因
Cn1cnc2c1c(=O)n(C)c(=O)n2C
```

### 行内结构式

写法是 `\smiles{SMILES}`，例如苯环 `\smiles{c1ccccc1}` 和乙酸 `\smiles{CC(=O)O}`。

### 立体化学

`@` 与 `@@` 表示手性中心的两种构型：

```smiles # L-丙氨酸
C[C@H](N)C(=O)O
```

```smiles # D-丙氨酸
C[C@@H](N)C(=O)O
```

`/` 与 `\` 表示双键两侧的顺反关系：

```smiles # 反-2-丁烯
C/C=C/C
```

```smiles # 顺-2-丁烯
C/C=C\C
```

## 常用 SMILES 速查

| 结构 | SMILES |
| --- | --- |
| 甲烷 | `C` |
| 乙醇 | `CCO` |
| 乙酸 | `CC(=O)O` |
| 丙酮 | `CC(=O)C` |
| 乙酸乙酯 | `CCOC(=O)C` |
| 乙胺 | `CCN` |
| 苯 | `c1ccccc1` |
| 甲苯 | `Cc1ccccc1` |
| 苯酚 | `Oc1ccccc1` |
| 苯甲酸 | `OC(=O)c1ccccc1` |
| 萘 | `c1ccc2ccccc2c1` |
| 吡啶 | `c1ccncc1` |
| 呋喃 | `c1ccoc1` |
| 噻吩 | `c1ccsc1` |
| 环己烷 | `C1CCCCC1` |

写法要点：

* **原子**：`C` `N` `O` `S` `Cl` `Br` 直接写元素符号，芳香环用小写 `c` `n` `o` `s`。
* **键**：单键省略，双键 `=`，三键 `#`；支链放圆括号里，如 `CC(C)C`。
* **成环**：用数字配对，如 `C1CCCCC1` 表示六元环。
* **氢**：一般不用写，程序按价键自动补齐；`[NH4+]` 这类需要显式写。
* **电荷**：`[O-]`、`[Na+]`、`[Cu+2]`。

## 导出图片插进 Word

Word 的公式编辑器是 OMML，不认 LaTeX，也不支持 mhchem，
所以化学内容进 Word 最稳的做法是**导出成图片再插入**：

```bash
# 单张结构式（PNG，3 倍分辨率）
python tools/chem/make_image.py "CC(=O)Oc1ccccc1C(=O)O" -o 阿司匹林.png --png --scale 4

# 批量：smiles.txt 每行一个 SMILES
python tools/chem/make_image.py --file smiles.txt -o out\ --png --scale 4

# 也可以要矢量图，插进 Word 后可无损缩放
python tools/chem/make_image.py "c1ccccc1" -o 苯.svg
```

`samples/chemistry/` 里已经放了一批生成好的 PNG，可以直接拖进 Word。
