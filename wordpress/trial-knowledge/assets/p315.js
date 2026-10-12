/* Trial Knowledge — "315 האירועים" page (2.6), progressive enhancement.
 * Without JS: the full list is shown and the charts are static.
 * With JS: tooltips on the 315 cells and the monthly columns, filters (class, year, search)
 * with paging, legend links that filter, and cell clicks that open the event in the list. */
(function () {
	'use strict';
	var root = document.querySelector('.tk315');
	if (!root) { return; }
	var PAGE = 40;

	// ---- shared tooltip
	var tip = document.createElement('div');
	tip.className = 'tk315-tip';
	tip.setAttribute('role', 'tooltip');
	tip.hidden = true;
	document.body.appendChild(tip);
	function showTip(el, lines) {
		tip.textContent = '';
		lines.forEach(function (l, i) {
			var p = document.createElement(i === 0 ? 'strong' : 'span');
			p.textContent = l;
			tip.appendChild(p);
		});
		tip.hidden = false;
		var r = el.getBoundingClientRect();
		var w = tip.offsetWidth, h = tip.offsetHeight;
		var x = r.left + r.width / 2 - w / 2;
		x = Math.max(8, Math.min(x, window.innerWidth - w - 8));
		var y = r.top - h - 8;
		if (y < 8) { y = r.bottom + 8; }
		tip.style.left = (x + window.scrollX) + 'px';
		tip.style.top = (y + window.scrollY) + 'px';
	}
	function hideTip() { tip.hidden = true; }

	// ---- list items
	var items = Array.prototype.slice.call(root.querySelectorAll('.tk315-item'));
	var byN = {};
	items.forEach(function (li) {
		var n = li.id.replace('p315-', '');
		byN[n] = li;
		li._q = (n + ' ' + li.textContent).replace(/\s+/g, ' ').toLowerCase();
	});
	function itemLines(n) {
		var li = byN[n];
		if (!li) { return ['אירוע ' + n]; }
		var date = li.querySelector('time'), dem = li.querySelector('.tk315-item__demand'), v = li.querySelector('.tk315-verdict');
		var d = dem ? dem.textContent : '';
		if (d.length > 140) { d = d.slice(0, 137) + '…'; }
		return ['אירוע ' + n + (date ? ' · ' + date.textContent : ''), d, v ? v.textContent : ''];
	}

	// waffle cells
	var waffle = root.querySelector('.tk315-waffle');
	if (waffle) {
		waffle.addEventListener('mouseover', function (ev) {
			var c = ev.target.closest('.tk315-cell');
			if (c) { showTip(c, itemLines(c.getAttribute('data-n'))); }
		});
		waffle.addEventListener('mouseleave', hideTip);
		waffle.addEventListener('click', function (ev) {
			var c = ev.target.closest('.tk315-cell');
			if (!c) { return; }
			ev.preventDefault();
			hideTip();
			reveal(c.getAttribute('data-n'));
		});
	}

	// monthly columns: hover and keyboard focus
	root.querySelectorAll('.tk315-col').forEach(function (col) {
		var lines = (col.getAttribute('data-tip') || '').split('\n');
		col.addEventListener('mouseenter', function () { showTip(col, lines); });
		col.addEventListener('mouseleave', hideTip);
		col.addEventListener('focus', function () { showTip(col, lines); });
		col.addEventListener('blur', hideTip);
	});
	window.addEventListener('scroll', hideTip, { passive: true });

	// ---- filters and paging
	var form = root.querySelector('.tk315-filters');
	var chips = form ? Array.prototype.slice.call(form.querySelectorAll('.tk315-chip')) : [];
	var year = form ? form.querySelector('[data-tk315-year]') : null;
	var q = form ? form.querySelector('[data-tk315-q]') : null;
	var count = form ? form.querySelector('.tk315-count') : null;
	var moreWrap = root.querySelector('.tk315-more');
	var moreBtn = root.querySelector('[data-tk315-more]');
	var state = { cat: '', year: '', q: '', shown: PAGE };
	if (form) { form.hidden = false; }

	function matches(li) {
		if (state.cat && li.getAttribute('data-c') !== state.cat) { return false; }
		if (state.year && li.getAttribute('data-y') !== state.year) { return false; }
		if (state.q && li._q.indexOf(state.q) < 0) { return false; }
		return true;
	}
	function apply() {
		var total = 0, shown = 0;
		items.forEach(function (li) {
			var ok = matches(li);
			if (ok) { total++; }
			var vis = ok && total <= state.shown;
			li.hidden = !vis;
			if (vis) { shown++; }
		});
		if (count) {
			count.textContent = total === items.length && !state.q && !state.year && !state.cat
				? 'כל ' + items.length + ' האירועים' + (shown < total ? ' (מוצגים ' + shown + ')' : '')
				: total + ' אירועים מתאימים' + (shown < total ? ' (מוצגים ' + shown + ')' : '');
		}
		if (moreWrap) { moreWrap.hidden = shown >= total; }
		chips.forEach(function (c) {
			var on = c.getAttribute('data-tk315-cat') === state.cat;
			c.classList.toggle('is-on', on);
			c.setAttribute('aria-pressed', on ? 'true' : 'false');
		});
	}
	chips.forEach(function (c) {
		c.addEventListener('click', function () { state.cat = c.getAttribute('data-tk315-cat'); state.shown = PAGE; apply(); });
	});
	if (year) { year.addEventListener('change', function () { state.year = year.value; state.shown = PAGE; apply(); }); }
	if (q) {
		var t;
		q.addEventListener('input', function () {
			clearTimeout(t);
			t = setTimeout(function () { state.q = q.value.trim().toLowerCase(); state.shown = PAGE; apply(); }, 150);
		});
	}
	if (moreBtn) { moreBtn.addEventListener('click', function () { state.shown += PAGE; apply(); }); }

	// legend links in the overview filter the list
	root.querySelectorAll('.tk315-legend__a').forEach(function (a) {
		a.addEventListener('click', function (ev) {
			ev.preventDefault();
			state.cat = a.getAttribute('data-tk315-cat') || '';
			state.year = ''; state.q = ''; state.shown = PAGE;
			if (year) { year.value = ''; }
			if (q) { q.value = ''; }
			apply();
			form.scrollIntoView({ block: 'start', behavior: 'smooth' });
		});
	});

	// open one event in the list (from a cell or a #p315-N link)
	function reveal(n) {
		var li = byN[n];
		if (!li) { return; }
		state.cat = ''; state.year = ''; state.q = '';
		if (year) { year.value = ''; }
		if (q) { q.value = ''; }
		state.shown = Math.max(PAGE, items.indexOf(li) + 1);
		apply();
		items.forEach(function (x) { x.classList.remove('is-target'); });
		li.classList.add('is-target');
		li.scrollIntoView({ block: 'center', behavior: 'smooth' });
		if (history.replaceState) { history.replaceState(null, '', '#p315-' + n); }
	}
	apply();
	var m = /^#p315-(\d+)$/.exec(location.hash || '');
	if (m) { reveal(m[1]); }
}());
