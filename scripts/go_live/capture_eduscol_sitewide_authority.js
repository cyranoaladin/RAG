const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');

const outputDir = process.env.AUTHORITY_EVIDENCE_DIR;
if (!outputDir) throw new Error('AUTHORITY_EVIDENCE_DIR is required');
const captureScript = process.env.AUTHORITY_CAPTURE_SCRIPT;
if (!captureScript) throw new Error('AUTHORITY_CAPTURE_SCRIPT is required');
fs.mkdirSync(outputDir, { recursive: true });

const sources = [
  ['eduscol_legal_notice', 'https://eduscol.education.gouv.fr/4656/mentions-legales'],
  ['etalab_2_0_licence', 'https://www.data.gouv.fr/pages/legal/licences/etalab-2.0'],
];

function sha256(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex'); }

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: 'fr-FR',
    timezoneId: 'Europe/Paris',
    viewport: { width: 1440, height: 1000 },
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
  });
  const results = [];
  try {
    for (const [name, requestedUrl] of sources) {
      const page = await context.newPage();
      const response = await page.goto(requestedUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
      await page.locator('body').waitFor({ state: 'visible', timeout: 15000 });
      const finalUrl = page.url();
      const status = response ? response.status() : null;
      const html = (await page.content()).replace(/\r\n?/g, '\n').replace(/>\s+</g, '><').trim() + '\n';
      const text = (await page.locator('body').innerText()).replace(/\r\n?/g, '\n').trim() + '\n';
      const htmlPath = path.join(outputDir, `${name}.normalized.html`);
      const textPath = path.join(outputDir, `${name}.extracted.txt`);
      const shotPath = path.join(outputDir, `${name}.png`);
      fs.writeFileSync(htmlPath, html);
      fs.writeFileSync(textPath, text);
      await page.screenshot({ path: shotPath, fullPage: true, animations: 'disabled' });
      const receipt = {
        kind: 'NEXUS_EDUSCOL_SITEWIDE_BROWSER_CAPTURE_V1',
        requested_url: requestedUrl,
        final_url: finalUrl,
        http_status: status,
        observed_at_utc: new Date().toISOString(),
        browser: 'chromium',
        browser_version: browser.version(),
        playwright_version: require('playwright/package.json').version,
        capture_script_sha256: sha256(fs.readFileSync(captureScript)),
        normalized_html_file: path.basename(htmlPath),
        normalized_html_sha256: sha256(fs.readFileSync(htmlPath)),
        extracted_text_file: path.basename(textPath),
        extracted_text_sha256: sha256(fs.readFileSync(textPath)),
        screenshot_file: path.basename(shotPath),
        screenshot_sha256: sha256(fs.readFileSync(shotPath)),
      };
      fs.writeFileSync(path.join(outputDir, `${name}.receipt.json`), JSON.stringify(receipt, null, 2) + '\n');
      results.push(receipt);
      await page.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(results, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
