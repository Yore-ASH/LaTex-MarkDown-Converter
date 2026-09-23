/*
 * 用 DevTools 协议在无头 Edge 中打开生成的 HTML，收集控制台报错与渲染结果。
 *
 * 用法: node tools/verify/render_check.js <file-url> [浏览器可执行文件]
 * 输出: 一行 JSON
 */

'use strict';

const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');

const target = process.argv[2];
const browser = process.argv[3] || process.env.MDCONV_BROWSER || '';
const port = 17000 + Math.floor(Math.random() * 2000);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'mdconv-verify-'));

if (!target) {
    console.log(JSON.stringify({ fatal: '缺少目标 URL' }));
    process.exit(0);
}

const child = spawn(
    browser,
    [
        '--headless=new',
        '--disable-gpu',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-extensions',
        '--allow-file-access-from-files',
        '--user-data-dir=' + profile,
        '--remote-debugging-port=' + port,
        'about:blank'
    ],
    { stdio: 'ignore' }
);

const report = {
    navigated: false,
    consoleErrors: [],
    renderErrors: [],
    counts: {},
    title: null
};

function finish() {
    try { child.kill(); } catch (err) { /* 忽略 */ }
    console.log(JSON.stringify(report));
    process.exit(0);
}

const deadline = setTimeout(() => {
    report.fatal = '超时';
    finish();
}, 45000);

function getJson(url) {
    return new Promise((resolve, reject) => {
        http.get(url, (res) => {
            let body = '';
            res.setEncoding('utf8');
            res.on('data', (chunk) => { body += chunk; });
            res.on('end', () => {
                try { resolve(JSON.parse(body)); } catch (err) { reject(err); }
            });
        }).on('error', reject);
    });
}

async function waitForDevTools() {
    for (let attempt = 0; attempt < 60; attempt += 1) {
        try {
            return await getJson('http://127.0.0.1:' + port + '/json/version');
        } catch (err) {
            await new Promise((r) => setTimeout(r, 300));
        }
    }
    throw new Error('DevTools 端口未就绪');
}

(async () => {
    let version;
    try {
        version = await waitForDevTools();
    } catch (err) {
        report.fatal = err.message;
        clearTimeout(deadline);
        finish();
        return;
    }
    report.browser = version.Browser;

    // ws 安装在 tools/katex 下，按绝对路径解析，避免受工作目录影响
    const WebSocket = require(path.join(__dirname, '..', 'katex', 'node_modules', 'ws'));
    const socket = new WebSocket(version.webSocketDebuggerUrl, { perMessageDeflate: false });
    let nextId = 1;
    const pending = new Map();

    const send = (method, params, sessionId) => new Promise((resolve, reject) => {
        const id = nextId++;
        pending.set(id, { resolve, reject });
        socket.send(JSON.stringify({ id, method, params: params || {}, sessionId }));
    });

    socket.on('message', (raw) => {
        let message;
        try { message = JSON.parse(raw.toString()); } catch (err) { return; }

        if (message.id && pending.has(message.id)) {
            const entry = pending.get(message.id);
            pending.delete(message.id);
            if (message.error) {
                entry.reject(new Error(message.error.message));
            } else {
                entry.resolve(message.result);
            }
            return;
        }

        if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
            report.consoleErrors.push(
                (message.params.args || [])
                    .map((arg) => arg.value || arg.description || arg.type)
                    .join(' ')
                    .slice(0, 300)
            );
        }
        if (message.method === 'Runtime.exceptionThrown') {
            const details = message.params.exceptionDetails || {};
            report.consoleErrors.push(
                String(details.exception && details.exception.description || details.text || '').slice(0, 300)
            );
        }
        if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
            report.consoleErrors.push(String(message.params.entry.text).slice(0, 300));
        }
    });

    await new Promise((resolve, reject) => {
        socket.on('open', resolve);
        socket.on('error', reject);
    });

    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const attached = await send('Target.attachToTarget', { targetId, flatten: true });
    const sessionId = attached.sessionId;

    await send('Runtime.enable', {}, sessionId);
    await send('Log.enable', {}, sessionId);
    await send('Page.enable', {}, sessionId);

    const loaded = new Promise((resolve) => {
        const handler = (raw) => {
            const message = JSON.parse(raw.toString());
            if (message.method === 'Page.loadEventFired') {
                socket.off('message', handler);
                resolve();
            }
        };
        socket.on('message', handler);
    });

    await send('Page.navigate', { url: target }, sessionId);
    report.navigated = true;
    await Promise.race([loaded, new Promise((r) => setTimeout(r, 20000))]);
    await new Promise((r) => setTimeout(r, 1500));

    const expression = `(() => {
        const q = (sel) => document.querySelectorAll(sel).length;
        const errors = Array.from(document.querySelectorAll('.katex-error, .math-error'))
            .map((node) => (node.textContent || '').trim().slice(0, 120));
        return {
            title: document.title,
            katex: q('.katex'),
            katexDisplay: q('.katex-display'),
            katexError: q('.katex-error'),
            mathRaw: q('.math-raw'),
            mathInline: q('.math-inline'),
            mathDisplay: q('.math-display'),
            tagBox: q('.tag-box'),
            headings: q('h1') + q('h2') + q('h3') + q('h4') + q('h5') + q('h6'),
            invalidParagraphDiv: q('p > div'),
            svgInline: q('svg'),
            bodyText: (document.body.innerText || '').length,
            dollarInText: ((document.body.innerText || '').match(/\\$\\$/g) || []).length,
            errors: errors
        };
    })()`;

    const evaluated = await send(
        'Runtime.evaluate',
        { expression, returnByValue: true },
        sessionId
    );
    const value = evaluated.result && evaluated.result.value;
    if (value) {
        report.title = value.title;
        report.counts = {
            katex: value.katex,
            katexDisplay: value.katexDisplay,
            katexError: value.katexError,
            mathRaw: value.mathRaw,
            mathInline: value.mathInline,
            mathDisplay: value.mathDisplay,
            tagBox: value.tagBox,
            headings: value.headings,
            invalidParagraphDiv: value.invalidParagraphDiv,
            svgInline: value.svgInline,
            bodyText: value.bodyText,
            dollarInText: value.dollarInText
        };
        report.renderErrors = value.errors;
    }

    clearTimeout(deadline);
    finish();
})().catch((err) => {
    report.fatal = String(err && err.message ? err.message : err);
    clearTimeout(deadline);
    finish();
});
