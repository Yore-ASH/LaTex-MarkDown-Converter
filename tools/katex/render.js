/*
 * KaTeX 渲染桥
 *
 * 协议：stdin 每行一个 JSON 对象 {"id": <任意值>, "text": "<LaTeX>", "display": true|false}
 *       stdout 每行一个 JSON 对象 {"id": <原样回传>, "html": "<渲染结果>", "error": null|"<错误信息>"}
 *       id 为 null 并带 fatal 字段表示桥自身不可用。
 *
 * 输出使用 \n 转义，保证与 stdin 的行边界一一对应。
 */

'use strict';

const readline = require('readline');

let katex = null;
let initError = null;

try {
    katex = require('katex');
    // 化学方程式支持（mhchem）。KaTeX 的 contrib 模块在部分发行版中缺失，缺失时不应影响主流程。
    try {
        require('katex/contrib/mhchem');
    } catch (err) {
        process.stderr.write('mhchem 未加载: ' + err.message + '\n');
    }
} catch (err) {
    initError = err.message;
}

function emit(payload) {
    process.stdout.write(JSON.stringify(payload) + '\n');
}

if (initError) {
    emit({ id: null, fatal: '无法加载 katex 模块: ' + initError });
    process.exit(0);
}

emit({ id: null, ready: true });

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

rl.on('line', function (line) {
    const trimmed = line.trim();
    if (!trimmed) {
        return;
    }

    let request;
    try {
        request = JSON.parse(trimmed);
    } catch (err) {
        emit({ id: null, error: '请求不是合法 JSON: ' + err.message });
        return;
    }

    const id = request.id;
    const text = typeof request.text === 'string' ? request.text : '';

    try {
        const html = katex.renderToString(text, {
            displayMode: request.display === true,
            throwOnError: true,
            errorColor: '#c7254e',
            strict: false,
            trust: false,
            // 公式编号由 Python 侧接管，这里关闭 KaTeX 自己的编号逻辑。
            leqno: false,
            fleqn: false,
            macros: request.macros && typeof request.macros === 'object' ? request.macros : {}
        });
        emit({ id: id, html: html, error: null });
    } catch (err) {
        emit({ id: id, html: null, error: String(err && err.message ? err.message : err) });
    }
});

rl.on('close', function () {
    process.exit(0);
});
