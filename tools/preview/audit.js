// Contrast audit: every button/link in normal, hover and focus states, with the theme's global button/link styles.
const { chromium } = require('playwright');
const fs = require('fs');
const pages = process.argv.slice(2).length ? process.argv.slice(2) : ['start','witnesses','witness','documents','hearing','glossary','timeline','ask'].filter(n => fs.existsSync(__dirname + '/' + n + '.html'));
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--headless=new'] });
  const bad = {};
  for (const name of pages) {
    const p = await b.newPage({ viewport: { width: 1200, height: 900 } });
    await p.goto('file://' + __dirname + '/' + name + '.html');
    await p.waitForTimeout(300);
    const n = await p.evaluate(() => {
      const els = [...document.querySelectorAll('button, a, [role=button], summary, label.tk-tl__chip, .tk-tl__chip')]
        .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (e.innerText || '').trim(); });
      els.forEach((e, i) => e.setAttribute('data-audit', i));
      return els.length;
    });
    const measure = async (i) => p.evaluate((i) => {
      const e = document.querySelector(`[data-audit="${i}"]`);
      const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return [0,0,0,0]; const v = m[1].split(',').map(Number); return [v[0],v[1],v[2],v.length>3?v[3]:1]; };
      const lum = ([r,g,b]) => { const f = x => { x/=255; return x<=0.03928? x/12.92 : Math.pow((x+0.055)/1.055,2.4); }; return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b); };
      let bg = [255,255,255,0], el = e;
      const stack = [];
      while (el && el.nodeType === 1) { const c = parse(getComputedStyle(el).backgroundColor); if (c[3] > 0) stack.push(c); if (c[3] >= 1) break; el = el.parentElement; }
      let base = [255,255,255];
      for (const c of stack.reverse()) base = base.map((v,k) => v*(1-c[3]) + c[k]*c[3]);
      // the text colour of the deepest text-bearing element
      let t = e; const walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); let tn; while ((tn = walker.nextNode())) { if (tn.textContent.trim()) { t = tn.parentElement; break; } }
      const fg = parse(getComputedStyle(t).color);
      const L1 = lum(fg), L2 = lum(base);
      const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
      return { ratio: Math.round(ratio*100)/100, fg: getComputedStyle(t).color, bg: 'rgb(' + base.map(Math.round).join(',') + ')',
               sig: e.tagName.toLowerCase() + '.' + [...e.classList].join('.'), text: (e.innerText||'').trim().slice(0,30) };
    }, i);
    for (let i = 0; i < Math.min(n, 600); i++) {
      // toggles (aria-pressed): also the other position, under the pointer, focused, and at rest
      const toggle = await p.evaluate((i) => document.querySelector(`[data-audit="${i}"]`).hasAttribute('aria-pressed'), i).catch(() => false);
      if (toggle) {
        try {
          const loc = p.locator(`[data-audit="${i}"]`);
          await loc.click({ timeout: 800 });
          for (const st of ['toggled+hover', 'toggled+focus', 'toggled']) {
            if (st === 'toggled+focus') await p.mouse.move(0, 0);
            if (st === 'toggled') await p.evaluate(() => document.activeElement && document.activeElement.blur());
            const m = await measure(i);
            if (m.ratio < 4.5) { const k = name + ' | ' + m.sig + ' | ' + st; (bad[k] = bad[k] || { n: 0, ex: m }).n++; }
          }
          await loc.click({ timeout: 800 });
          await p.mouse.move(0, 0); await p.evaluate(() => document.activeElement && document.activeElement.blur());
        } catch (err) { }
      }
      for (const state of ['normal','hover','focus']) {
        try {
          const loc = p.locator(`[data-audit="${i}"]`);
          if (state === 'hover') await loc.hover({ timeout: 500, force: true });
          if (state === 'focus') await loc.focus({ timeout: 500 });
          const m = await measure(i);
          if (m.ratio < 4.5) { const k = name + ' | ' + m.sig + ' | ' + state; (bad[k] = bad[k] || { n: 0, ex: m }).n++; }
          if (state !== 'normal') { await p.mouse.move(0, 0); await p.evaluate(() => document.activeElement && document.activeElement.blur()); }
        } catch (err) { }
      }
    }
    console.error(name, n);
    await p.close();
  }
  for (const [k, v] of Object.entries(bad).sort()) console.log(`${k} | x${v.n} | ${v.ex.ratio} | ${v.ex.fg} on ${v.ex.bg} | "${v.ex.text}"`);
  await b.close();
})();
