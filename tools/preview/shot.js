const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--headless=new'] });
  for (const [name, w] of [['start',1200],['start',390],['witnesses',1200],['witness',1200],['documents',1200],['hearing',1200],['glossary',800]]) {
    const p = await b.newPage({ viewport: { width: w, height: 900 } });
    await p.goto('file://' + __dirname + '/' + name + '.html');
    await p.screenshot({ path: `${name}-${w}.png`, fullPage: true });
    const h = await p.evaluate(() => document.body.scrollHeight);
    console.log(name, w, h);
  }
  await b.close();
})();
