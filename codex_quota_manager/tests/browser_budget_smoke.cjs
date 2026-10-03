const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');

// Reuse an installed Playwright package; keep browser profiles and output in this project.
const { chromium } = require(process.argv[2] || 'playwright');
const executablePath = process.argv[3];
const port = Number(process.argv[4] || 8791);
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'output', 'playwright');
fs.mkdirSync(output, { recursive: true });
const server = spawn('python', ['-B', 'tests/budget_ui_fixture.py', '--port', String(port)], {
  cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
});
let serverOutput = '';
server.stdout.on('data', data => { serverOutput += data; });
server.stderr.on('data', data => { serverOutput += data; });
const base = `http://127.0.0.1:${port}`;
let browser;

async function checkLayout(page) {
  const problems = await page.evaluate(() => {
    const errors = [];
    if (document.documentElement.scrollWidth > innerWidth) errors.push('horizontal page overflow');
    const telemetry = document.querySelector('.telemetry-card').getBoundingClientRect();
    for (const node of document.querySelectorAll('.telemetry-grid strong')) {
      if (node.getBoundingClientRect().bottom > telemetry.bottom - 2) errors.push('telemetry value clipped');
    }
    for (const row of document.querySelectorAll('.task-row')) {
      const box = row.getBoundingClientRect();
      const items = [...row.children].map(node => ({ node, rect: node.getBoundingClientRect() }));
      for (const { node, rect } of items) {
        if (rect.left < box.left || rect.right > box.right + 1 || rect.bottom > box.bottom + 1) {
          errors.push(`${node.className}: outside task row`);
        }
      }
      for (const node of row.querySelectorAll('.budget-status strong, .budget-status span')) {
        if (node.scrollWidth > node.clientWidth + 1) errors.push(`budget text clipped: ${node.textContent}`);
      }
      for (let a = 0; a < items.length; a++) for (let b = a + 1; b < items.length; b++) {
        const x = items[a].rect, y = items[b].rect;
        if (Math.min(x.right, y.right) > Math.max(x.left, y.left) + 1 &&
            Math.min(x.bottom, y.bottom) > Math.max(x.top, y.top) + 1) {
          // Mobile priority is positioned in padding reserved within the primary cell.
          if ([items[a].node.className, items[b].node.className].includes('task-primary') &&
              [items[a].node.className, items[b].node.className].includes('priority-control')) {
            const primary = items[a].node.className === 'task-primary' ? items[a].node : items[b].node;
            const text = primary.querySelector('.task-text').getBoundingClientRect();
            const priority = items[a].node.className === 'priority-control' ? x : y;
            if (text.right <= priority.left) continue;
          }
          errors.push(`task controls overlap: ${items[a].node.className}/${items[b].node.className}`);
        }
      }
    }
    return errors;
  });
  assert.deepEqual(problems, []);
}

async function setScenario(page, scenario) {
  await page.request.post(`${base}/fixture/scenario/${scenario}`);
  await page.evaluate(() => { document.activeElement?.blur(); return fetchStatus(); });
}

(async () => {
  try {
    for (let attempt = 0; attempt < 40; attempt++) {
      if (server.exitCode != null) throw new Error(serverOutput);
      try { if ((await fetch(`${base}/health`)).ok) break; } catch (_) {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    browser = await chromium.launchPersistentContext(path.join(root, 'runtime', 'browser-smoke-profile'), {
      executablePath, headless: true, viewport: { width: 1366, height: 768 },
    });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(`${base}/display`);
    await page.waitForSelector('.task-row');
    assert.equal(await page.locator('#active-count').textContent(), '3');
    assert.equal(await page.locator('.task-row').count(), 5);
    assert.match(await page.locator('[data-task-id="parallel-a"] .budget-status').textContent(), /可用估算.*五小时已用 40万.*分钟耗尽/);
    assert.match(await page.locator('[data-task-id="waiting"] .budget-status').textContent(), /等待中/);
    assert.equal(await page.locator('[data-task-id="idle"] .budget-status strong').textContent(), '无活动预算');
    const before = await page.locator('[data-task-id="parallel-a"] .budget-status strong').textContent();
    const input = page.locator('[data-task-id="parallel-a"] .budget-edit input');
    await input.fill('5');
    await input.press('Tab');
    await page.waitForFunction(() => state.snapshot.tasks.find(t => t.id === 'parallel-a').preference.manual_cap_percent === 5);
    await page.waitForFunction(() => document.querySelector('[data-task-id="parallel-a"] .budget-edit input')?.value === '5' &&
      document.querySelector('[data-task-id="parallel-a"] .budget-status strong')?.textContent === '可用估算 50万');
    assert.equal(await page.locator('[data-task-id="parallel-a"] .budget-edit input').inputValue(), '5');
    assert.notEqual(before, await page.locator('[data-task-id="parallel-a"] .budget-status strong').textContent());
    await page.locator('[data-task-id="parallel-a"] .budget-edit button').click();
    await page.waitForFunction(() => state.snapshot.tasks.find(t => t.id === 'parallel-a').preference.manual_cap_percent === null);
    await page.evaluate(() => { document.activeElement.blur(); return fetchStatus(); });
    await page.waitForFunction(() => document.querySelector('[data-task-id="parallel-a"] .budget-edit input')?.value === '');
    const priority = page.locator('[data-task-id="parallel-a"] select');
    await priority.selectOption('5');
    await page.evaluate(() => document.activeElement.blur());
    await page.waitForFunction(() => state.snapshot.tasks.find(t => t.id === 'parallel-a').preference.priority === 5);
    await page.locator('[data-task-id="parallel-a"] .task-title').click();
    assert.match(await page.locator('#task-detail-dialog').textContent(), /非 Codex 官方 Token 配额/);
    assert.match(await page.locator('#task-detail-dialog').textContent(), /五小时已用/);
    await page.locator('#task-detail-close').click();
    for (const [width, height, theme] of [[1366,768,'dark'],[1920,1080,'light'],[768,1024,'dark'],[390,844,'dark'],[320,740,'light'],[1366,650,'dark']]) {
      await page.setViewportSize({ width, height });
      await page.evaluate(theme => applyTheme(theme, false), theme);
      await checkLayout(page);
      await page.screenshot({ path: path.join(output, `budget-${width}x${height}-${theme}.png`), fullPage: true });
    }
    for (const [scenario, expected] of [['calibrating','可用估算 校准中'],['stale','可用估算 等待额度'],['zero','建议预算已用尽'],['unknown_rate','速度校准中'],['after_reset','刷新前充足']]) {
      await setScenario(page, scenario);
      assert.ok((await page.locator('[data-task-id="parallel-a"] .budget-status').textContent()).includes(expected));
      if (scenario === 'calibrating') assert.equal(await page.locator('#available-budget').textContent(), '校准中');
    }
    await setScenario(page, 'many');
    assert.equal(await page.locator('#active-count').textContent(), '7');
    assert.equal(await page.locator('.task-row').count(), 7);
    assert.equal(await page.locator('.task-list.many-active').count(), 1);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ result: 'passed', viewports: 6, scenarios: 7, manualAndPriority: true, screenshots: output }));
  } finally {
    if (browser) await browser.close();
    if (server.exitCode == null) {
      server.kill();
      await new Promise(resolve => server.once('exit', resolve));
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
