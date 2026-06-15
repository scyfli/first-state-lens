#!/usr/bin/env node
/**
 * Accessibility CI gate — axe-core (WCAG 2.2 AA) over the dashboards.
 *
 * The dashboards are soft-launch password-gated client-side (sessionStorage).
 * This script reads each page's gate constants (HASH + STORAGE_KEY) straight
 * from its HTML and seeds sessionStorage so axe audits the REAL content, not
 * the gate. Fails the build on any serious/critical violation.
 *
 * Runs both locally (puppeteer-core + PUPPETEER_EXECUTABLE_PATH) and in CI
 * (puppeteer with its bundled Chrome).
 *
 *   node scripts/a11y-audit.js
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

let puppeteer;
try { puppeteer = require('puppeteer'); } catch (_) { puppeteer = require('puppeteer-core'); }
const { AxePuppeteer } = require('@axe-core/puppeteer');

const ROOT = path.resolve(__dirname, '..');
const ROUTES = ['/', '/clean-slate/', '/dgi-food-access/', '/federal/', '/spending/', '/childcare/', '/schools/'];
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const FAIL_IMPACTS = new Set(['serious', 'critical']);
const MIME = { '.html': 'text/html', '.json': 'application/json', '.geojson': 'application/json', '.csv': 'text/csv', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' };

function serve() {
  return http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p.endsWith('/')) p += 'index.html';
    const fp = path.join(ROOT, p);
    if (!fp.startsWith(ROOT) || !fs.existsSync(fp) || fs.statSync(fp).isDirectory()) { res.writeHead(404); return res.end('nf'); }
    res.writeHead(200, { 'content-type': MIME[path.extname(fp)] || 'application/octet-stream' });
    fs.createReadStream(fp).pipe(res);
  });
}

function gateConstants(route) {
  const fp = path.join(ROOT, route.replace(/\/$/, '/index.html').replace(/^\//, ''));
  if (!fs.existsSync(fp)) return null;
  const html = fs.readFileSync(fp, 'utf8');
  const hash = html.match(/const HASH\s*=\s*"([0-9a-fA-F]+)"/);
  const key = html.match(/const STORAGE_KEY\s*=\s*"([^"]+)"/);
  return hash && key ? { hash: hash[1], key: key[1] } : null;
}

(async () => {
  const server = serve();
  await new Promise(r => server.listen(8788, r));
  const launch = { headless: 'new', args: ['--no-sandbox', '--disable-setuid-sandbox'] };
  if (process.env.PUPPETEER_EXECUTABLE_PATH) launch.executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
  const browser = await puppeteer.launch(launch);

  let totalFail = 0;
  for (const route of ROUTES) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1366, height: 900 });
    const gate = gateConstants(route);
    if (gate) await page.evaluateOnNewDocument((k, h) => { try { sessionStorage.setItem(k, h); } catch (e) {} }, gate.key, gate.hash);
    await page.goto('http://localhost:8788' + route, { waitUntil: 'networkidle2', timeout: 45000 });
    // let any deferred render (map) settle
    await new Promise(r => setTimeout(r, 1500));
    const results = await new AxePuppeteer(page).withTags(WCAG_TAGS).analyze();
    const blocking = results.violations.filter(v => FAIL_IMPACTS.has(v.impact));
    const minor = results.violations.filter(v => !FAIL_IMPACTS.has(v.impact));
    console.log(`\n== ${route} ==  ${gate ? '(gate bypassed)' : '(no gate)'}`);
    console.log(`   blocking (serious/critical): ${blocking.length} · other: ${minor.length}`);
    for (const v of blocking) {
      totalFail++;
      console.log(`   ✗ [${v.impact}] ${v.id} — ${v.help}  (${v.nodes.length} node(s))`);
      console.log(`     ${v.helpUrl}`);
      v.nodes.slice(0, 2).forEach(n => console.log(`       ${n.target.join(' ')}`));
    }
    for (const v of minor) console.log(`   · [${v.impact}] ${v.id} — ${v.help} (${v.nodes.length})`);
    await page.close();
  }

  await browser.close();
  server.close();
  console.log(`\n${'='.repeat(48)}`);
  if (totalFail > 0) { console.log(`A11Y GATE: FAIL — ${totalFail} serious/critical violation(s).`); process.exit(1); }
  console.log('A11Y GATE: PASS — no serious/critical WCAG 2.2 AA violations.');
})().catch(e => { console.error('A11Y AUDIT ERROR: ' + e.message); process.exit(2); });
