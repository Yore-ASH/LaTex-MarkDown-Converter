"""HTML 模板：生成单文件、可离线打开的 HTML。"""

from __future__ import annotations

import html as _html

# 预渲染失败时用于兜底的客户端渲染脚本。仅在确实存在未渲染公式时才写入页面。
CLIENT_FALLBACK = r"""
<script>
(function () {
    var nodes = document.querySelectorAll('.math-inline .math-raw, .math-display .math-raw');
    if (!nodes.length) { return; }

    function showRaw() {
        for (var i = 0; i < nodes.length; i++) {
            nodes[i].title = '公式未预渲染，且离线兜底不可用';
        }
    }

    function load(src, onload, onerror) {
        var script = document.createElement('script');
        script.src = src;
        script.onload = onload;
        script.onerror = onerror;
        document.head.appendChild(script);
    }

    function renderAll() {
        if (typeof katex === 'undefined') { showRaw(); return; }
        for (var i = 0; i < nodes.length; i++) {
            var node = nodes[i];
            var holder = node.closest('.math-inline, .math-display');
            if (!holder) { continue; }
            var tex = holder.getAttribute('data-tex') || '';
            // data-tex 保存的是带定界符的原文，渲染前去掉 $ / $$
            tex = tex.replace(/^\$\$?/, '').replace(/\$\$?$/, '');
            try {
                katex.render(tex, holder, {
                    displayMode: holder.classList.contains('math-display'),
                    throwOnError: false,
                    strict: false
                });
            } catch (err) {
                node.title = String(err && err.message ? err.message : err);
            }
        }
    }

    load(
        'https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.js',
        function () {
            load(
                'https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/contrib/mhchem.min.js',
                renderAll,
                renderAll
            );
        },
        showRaw
    );
})();
</script>
"""


def _escape_title(title: str) -> str:
    return _html.escape(title, quote=True)


def build_document(
    body: str,
    title: str,
    theme_css: str,
    katex_css: str = "",
    fallback_script: str = "",
    header: str = "",
    footer: str = "",
    toc: str = "",
) -> str:
    """拼装最终 HTML。

    ``katex_css`` 为已内嵌字体的 KaTeX 样式；为空表示本次输出没有公式，
    此时页面完全不依赖任何外部资源。
    """
    katex_section = ""
    if katex_css:
        katex_section = (
            "/* ==== KaTeX 渲染样式（字体已内嵌，可离线使用） ==== */\n"
            f"{katex_css}\n"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="generator" content="ASH Markdown Converter">
    <title>{_escape_title(title)}</title>
    <style>
{katex_section}/* ==== 文档主题样式 ==== */
{theme_css}
    </style>
</head>
<body>
{header}<article class="markdown-body">
{toc}{body}
</article>
{footer}{fallback_script}
</body>
</html>
"""
