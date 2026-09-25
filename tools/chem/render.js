/*
 * 结构式渲染桥
 *
 * 协议：stdin 每行一个 JSON 请求，stdout 每行一个 JSON 响应。
 *   {"id":1,"smiles":"CC(=O)O","mode":"svg","theme":"light"}
 *   {"id":2,"smiles":"c1ccccc1","mode":"png","scale":3}
 * 响应：
 *   {"id":1,"svg":"<svg …>","width":420,"height":320,"error":null}
 *   {"id":2,"png":"<base64>","width":760,"height":560,"error":null}
 *
 * 首行是握手信息：{"id":null,"ready":true,"browser":"…"}
 * 浏览器只在第一次真正需要渲染时启动。
 */

'use strict';

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const HERE = __dirname;
const PAGE = path.join(HERE, 'page.html');
const LIBRARY = path.join(HERE, 'node_modules', 'smiles-drawer', 'dist', 'smiles-drawer.js');

const DEFAULT_BROWSERS = [
    process.env.MDCONV_BROWSER,
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    '/usr/bin/microsoft-edge',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
].filter(Boolean);

function emit(payload) {
    process.stdout.write(JSON.stringify(payload) + '\n');
}

function findBrowser() {
    for (const candidate of DEFAULT_BROWSERS) {
        try {
            if (fs.existsSync(candidate)) {
                return candidate;
            }
        } catch (err) {
            /* 忽略无权限的路径 */
        }
    }
    return null;
}

const browserPath = findBrowser();
if (!browserPath) {
    emit({ id: null, fatal: '未找到可用的浏览器（Edge / Chrome），结构式渲染不可用' });
    process.exit(0);
}
if (!fs.existsSync(LIBRARY)) {
    emit({
        id: null,
        fatal: '未安装 smiles-drawer，请在 tools/chem 下执行 npm install'
    });
    process.exit(0);
}

let puppeteer = null;
try {
    puppeteer = require('puppeteer-core');
} catch (err) {
    emit({ id: null, fatal: '未安装 puppeteer-core：' + err.message });
    process.exit(0);
}

let browser = null;
let page = null;
let pageReady = false;

async function ensurePage() {
    if (page && pageReady) {
        return page;
    }
    browser = await puppeteer.launch({
        executablePath: browserPath,
        headless: true,
        args: [
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-extensions',
            '--disable-background-networking',
            '--hide-scrollbars'
        ]
    });
    page = await browser.newPage();
    await page.setViewport({ width: 1200, height: 900, deviceScaleFactor: 1 });
    await page.goto('file:///' + PAGE.replace(/\\/g, '/'), { waitUntil: 'load' });
    // 直接注入库内容，避免依赖 <script src> 的加载时序
    await page.addScriptTag({ content: fs.readFileSync(LIBRARY, 'utf8') });
    const ready = await page.evaluate(() => Boolean(window.SmilesDrawer));
    if (!ready) {
        throw new Error('smiles-drawer 注入失败');
    }
    pageReady = true;
    return page;
}

async function closeBrowser() {
    if (browser) {
        try {
            await browser.close();
        } catch (err) {
            /* 忽略关闭异常 */
        }
    }
    browser = null;
    page = null;
    pageReady = false;
}

async function handle(request) {
    const smiles = typeof request.smiles === 'string' ? request.smiles.trim() : '';
    if (!smiles) {
        return { id: request.id, error: 'SMILES 为空' };
    }

    const current = await ensurePage();
    const options = {
        width: request.width || 420,
        height: request.height || 320,
        theme: request.theme || 'light',
        terminalCarbons: request.terminalCarbons === true,
        explicitHydrogens: request.explicitHydrogens === true,
        compactDrawing: request.compactDrawing === true,
        atomVisualization: request.atomVisualization || 'default',
        bondLength: request.bondLength || 24
    };

    const rendered = await current.evaluate(
        (text, opts) => window.__chem.render(text, opts),
        smiles,
        options
    );

    if (!rendered || !rendered.svg) {
        return { id: request.id, error: '渲染结果为空' };
    }
    if (!rendered.ok) {
        return {
            id: request.id,
            error: '无法解析这个 SMILES（可能写法有误）',
            svg: rendered.svg,
            width: rendered.width,
            height: rendered.height
        };
    }

    if ((request.mode || 'svg') === 'png') {
        // 先把视口放到目标像素尺寸，再截图，这样能得到指定倍数的高清位图
        const scale = Math.min(Math.max(Number(request.scale) || 3, 1), 6);
        const box = await current.evaluate(() => window.__chem.measure());
        await current.setViewport({
            width: Math.max(1, box.width),
            height: Math.max(1, box.height),
            deviceScaleFactor: scale
        });
        const element = await current.$('#canvas');
        const buffer = await element.screenshot({
            type: 'png',
            omitBackground: false,
            captureBeyondViewport: true
        });
        await current.evaluate(() => window.__chem.reset());
        // 还原视口，避免影响后续的 SVG 渲染
        await current.setViewport({ width: 1200, height: 900, deviceScaleFactor: 1 });
        return {
            id: request.id,
            png: buffer.toString('base64'),
            width: Math.round(box.width * scale),
            height: Math.round(box.height * scale),
            error: null
        };
    }

    await current.evaluate(() => window.__chem.reset());
    return {
        id: request.id,
        svg: rendered.svg,
        width: rendered.width,
        height: rendered.height,
        error: null
    };
}

emit({ id: null, ready: true, browser: browserPath });

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let queue = Promise.resolve();

rl.on('line', (line) => {
    const trimmed = line.trim();
    if (!trimmed) {
        return;
    }

    // 串行处理，避免共用同一个页面时互相覆盖
    queue = queue.then(async () => {
        let request;
        try {
            request = JSON.parse(trimmed);
        } catch (err) {
            emit({ id: null, error: '请求不是合法 JSON: ' + err.message });
            return;
        }
        try {
            emit(await handle(request));
        } catch (err) {
            emit({ id: request.id, error: String((err && err.message) || err) });
        }
    });
});

rl.on('close', async () => {
    await queue;
    await closeBrowser();
    process.exit(0);
});
