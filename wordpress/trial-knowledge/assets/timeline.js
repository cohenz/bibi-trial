/* Trial Knowledge — dual-track zoomable timeline ([tk_timeline], /{slug}/timeline/).
 * Vanilla JS, no dependencies. Data: <script type="application/json" class="tk-tl__data"> rendered
 * by TK_Render_Guides::timeline() (URLs resolved server-side). Without JS the server-rendered
 * grouped list (.tk-tl__fallback) stays visible.
 *
 * Wide screens: an overview strip (periods × tracks, zoom decades/years → months → days with
 * +/− buttons, clickable period headers and a breadcrumb) above the list of events of the
 * current period, the two tracks side by side. Narrow screens: a vertical list grouped by
 * year with sticky year headers; a year expands to its months. Clicking an event opens its
 * detail panel in place (date, text, citation chips, link). All text goes through textContent.
 * 2.4: "hearing_day" events (a hearing day known from a court notice, drawn dashed/lighter than
 * transcribed hearings) and a toggle for procedural documents (off by default; ?tk_all=1 turns it on). */
(function () {
	'use strict';
	function nEv(n) { return n === 1 ? 'אירוע אחד' : n + ' אירועים'; }

	var MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];
	var MONTHS_SHORT = ['ינו׳', 'פבר׳', 'מרץ', 'אפר׳', 'מאי', 'יוני', 'יולי', 'אוג׳', 'ספט׳', 'אוק׳', 'נוב׳', 'דצמ׳'];
	var KIND_ORDER = ['indictment_fact', 'indictment', 'hearing', 'hearing_day', 'decision', 'motion', 'response', 'notice', 'affidavit', 'exhibit', 'other'];
	var KIND_PL = {
		indictment_fact: 'אירועים לפי כתב האישום', indictment: 'כתב האישום', hearing: 'דיונים', hearing_day: 'ימי דיון (לפי הודעות)', decision: 'החלטות',
		motion: 'בקשות', response: 'תגובות', notice: 'הודעות', affidavit: 'תצהירים', exhibit: 'מוצגים', other: 'מסמכים אחרים'
	};
	var TRACK = { story: 'מה קרה (לפי כתב האישום)', trial: 'המשפט' };
	var TRACK_SHORT = { story: 'לפי כתב האישום', trial: 'המשפט' };
	var CASES = ['4000', '2000', '1000'];
	var NARROW = '(max-width: 720px)';
	var uid = 0;

	function h(tag, attrs, kids) {
		var e = document.createElement(tag);
		Object.keys(attrs || {}).forEach(function (k) {
			var v = attrs[k];
			if (v === null || v === undefined || v === false) { return; }
			if (k === 'text') { e.textContent = v; }
			else if (k === 'class') { e.className = v; }
			else if (k.indexOf('on') === 0) { e.addEventListener(k.slice(2), v); }
			else { e.setAttribute(k, v === true ? '' : v); }
		});
		(kids || []).forEach(function (c) { if (c) { e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); } });
		return e;
	}
	function pad(n) { return (n < 10 ? '0' : '') + n; }
	function fmt(e) {
		if (e.p === 'year') { return String(e.y); }
		if (e.p === 'month') { return MONTHS[e.m - 1] + ' ' + e.y; }
		return e.d + '.' + e.m + '.' + e.y;
	}
	function caseClass(e) { return e.cases.length ? ' tk-case--' + e.cases[0] : ''; }
	function dotClass(e) {
		return 'tk-tl__dot' + (e.track === 'story' && !e.cases.length ? ' tk-tl__dot--story' : '') + (e.kind === 'hearing_day' ? ' tk-tl__dot--notice' : '') + caseClass(e);
	}

	function init(root) {
		var dataEl = root.querySelector('.tk-tl__data');
		if (!dataEl) { return; }
		var D;
		try { D = JSON.parse(dataEl.textContent); } catch (err) { return; }
		var events = (D.events || []).map(function (e) {
			e.y = +e.date.slice(0, 4); e.m = +e.date.slice(5, 7); e.d = +e.date.slice(8, 10);
			e.cases = e.cases || []; e.cits = e.cits || []; e.nw = e.nw || [];
			return e;
		});
		var cits = D.citations || {};
		var base = root.id || ('tk-tl-' + (++uid));
		var hasStory = events.some(function (e) { return e.track === 'story'; });
		var minY = Infinity, maxY = -Infinity;
		events.forEach(function (e) { minY = Math.min(minY, e.y); maxY = Math.max(maxY, e.y); });
		var LEVELS = (maxY - minY + 1 > 20) ? ['decade', 'year', 'month', 'day'] : ['year', 'month', 'day'];
		var kinds = KIND_ORDER.filter(function (k) { return events.some(function (e) { return e.kind === k; }); });

		var q = '';
		try { q = new URLSearchParams(window.location.search).get('tk_case') || ''; } catch (err) { q = ''; }
		var c0 = CASES.indexOf(q) >= 0 ? q : (CASES.indexOf(root.getAttribute('data-case')) >= 0 ? root.getAttribute('data-case') : '');
		var allQ = '';
		try { allQ = new URLSearchParams(window.location.search).get('tk_all') || ''; } catch (err) { allQ = ''; }
		var nProc = events.filter(function (e) { return e.sig === 'procedural'; }).length;
		var S = { cs: c0, proc: allQ === '1' || root.getAttribute('data-all') === '1', tracks: { story: true, trial: true }, kinds: {}, path: [], open: {}, openEv: null };
		kinds.forEach(function (k) { S.kinds[k] = true; });

		// ---------------------------------------------------------------- filters
		function visible(e) {
			if (!S.tracks[e.track] || !S.kinds[e.kind]) { return false; }
			if (e.sig === 'procedural' && !S.proc) { return false; }
			if (S.cs) { return e.cases.length ? e.cases.indexOf(S.cs) >= 0 : e.track === 'trial'; }
			return true;
		}
		function key(e, lv) {
			if (lv === 'decade') { return String(Math.floor(e.y / 10) * 10); }
			if (lv === 'year') { return String(e.y); }
			if (lv === 'month') { return e.p === 'year' ? e.y + '-00' : e.y + '-' + pad(e.m); }
			if (e.p === 'year') { return e.y + '-00-00'; }
			if (e.p === 'month') { return e.y + '-' + pad(e.m) + '-00'; }
			return e.date;
		}
		function inPath(e) {
			for (var i = 0; i < S.path.length; i++) { if (key(e, LEVELS[i]) !== S.path[i]) { return false; } }
			return true;
		}
		function label(lv, k, long) {
			if (lv === 'decade') { return k + '–' + (+k + 9); }
			if (lv === 'year') { return k; }
			var p = k.split('-');
			if (lv === 'month') {
				if (p[1] === '00') { return long ? 'במהלך ' + p[0] + ' (ללא חודש מדויק)' : 'כל השנה'; }
				return long ? MONTHS[+p[1] - 1] + ' ' + p[0] : MONTHS_SHORT[+p[1] - 1];
			}
			if (p[2] === '00') { return long ? (p[1] === '00' ? 'במהלך ' + p[0] : 'במהלך ' + MONTHS[+p[1] - 1] + ' ' + p[0]) : 'כל החודש'; }
			return long ? (+p[2]) + '.' + (+p[1]) + '.' + p[0] : (+p[2]) + '.' + (+p[1]);
		}
		function zoomable(lv, k) {
			return LEVELS.indexOf(lv) < LEVELS.length - 1 && !/-00$/.test(k);
		}
		function columns(lv, scope) {
			var out = [], i;
			if (lv === 'decade') {
				for (i = Math.floor(minY / 10) * 10; i <= maxY; i += 10) { out.push(String(i)); }
			} else if (lv === 'year') {
				var from = minY, to = maxY;
				if (S.path.length && LEVELS[0] === 'decade') { from = Math.max(minY, +S.path[0]); to = Math.min(maxY, +S.path[0] + 9); }
				for (i = from; i <= to; i++) { out.push(String(i)); }
			} else if (lv === 'month') {
				var y = S.path[S.path.length - 1];
				if (scope.some(function (e) { return key(e, 'month') === y + '-00'; })) { out.push(y + '-00'); }
				for (i = 1; i <= 12; i++) { out.push(y + '-' + pad(i)); }
			} else {
				var seen = {};
				scope.forEach(function (e) { seen[key(e, 'day')] = 1; });
				out = Object.keys(seen).sort();
			}
			return out;
		}

		// ---------------------------------------------------------------- chrome
		var fallback = root.querySelector('.tk-tl__fallback');
		if (fallback) { fallback.hidden = true; }
		var live = h('p', { class: 'tk-tl__note', 'aria-live': 'polite', role: 'status' });
		var caseNote = h('p', { class: 'tk-tl__note', text: 'דיונים ומסמכים שלא שויכו לתיק מסוים מוצגים בכל אחד מהתיקים.' });

		var caseBtns = [];
		function caseChip(k, text) {
			var b = h('button', { type: 'button', class: 'tk-tl__chip' + (k ? ' tk-case--' + k : ''), 'aria-pressed': String(S.cs === k), text: text, onclick: function () {
				S.cs = k; S.openEv = null;
				caseBtns.forEach(function (x) { x.setAttribute('aria-pressed', String(x._k === S.cs)); });
				syncUrl();
				render();
			} });
			b._k = k;
			caseBtns.push(b);
			return b;
		}
		var gCase = h('div', { class: 'tk-tl__group', role: 'group', 'aria-label': 'סינון לפי תיק' }, [h('span', { class: 'tk-tl__glabel', text: 'תיק' }), caseChip('', 'כל התיקים')]
			.concat(CASES.map(function (k) { return caseChip(k, 'תיק ' + k); })));
		var gTrack = h('div', { class: 'tk-tl__group', role: 'group', 'aria-label': 'מסלולים' }, [h('span', { class: 'tk-tl__glabel', text: 'מסלולים' })]
			.concat(['story', 'trial'].map(function (t) {
				return h('button', { type: 'button', class: 'tk-tl__chip', 'aria-pressed': 'true', text: TRACK[t], onclick: function (ev) {
					var on = !S.tracks[t];
					if (!on && !S.tracks[t === 'story' ? 'trial' : 'story']) { return; } // keep at least one track
					S.tracks[t] = on;
					ev.currentTarget.setAttribute('aria-pressed', String(on));
					render();
				} });
			})));
		var gKind = h('div', { class: 'tk-tl__group', role: 'group', 'aria-label': 'סוגי אירועים' }, []
			.concat(kinds.map(function (k) {
				return h('button', { type: 'button', class: 'tk-tl__chip', 'aria-pressed': 'true', text: KIND_PL[k] || k, onclick: function (ev) {
					S.kinds[k] = !S.kinds[k];
					ev.currentTarget.setAttribute('aria-pressed', String(S.kinds[k]));
					render();
				} });
			})));
		var kindBox = h('details', { class: 'tk-tl__more-filters' }, [h('summary', { text: 'סוגי אירועים' }), gKind]);
		var gProc = nProc ? h('div', { class: 'tk-tl__group', role: 'group', 'aria-label': 'מסמכים פרוצדורליים' }, [
			h('button', { type: 'button', class: 'tk-tl__chip tk-tl__chip--proc', 'aria-pressed': String(S.proc), text: 'גם מסמכים פרוצדורליים (' + nProc + ')',
				title: 'מסמכים שעוסקים רק בלוגיסטיקה של ההליך: מועדים, ארכות, הקלטות, העתקים', onclick: function (ev) {
					S.proc = !S.proc; S.openEv = null;
					ev.currentTarget.setAttribute('aria-pressed', String(S.proc));
					syncUrl();
					render(true);
				} })
		]) : null;
		var bar = h('div', { class: 'tk-tl__bar' }, [gCase, gTrack, kindBox, gProc, caseNote]);

		var zOut = h('button', { type: 'button', class: 'tk-tl__zoom', 'aria-label': 'התרחקות (תקופה רחבה יותר)', title: 'התרחקות', text: '−', onclick: function () { zoomOut(); } });
		var zIn = h('button', { type: 'button', class: 'tk-tl__zoom', 'aria-label': 'התקרבות (תקופה מצומצמת יותר)', title: 'התקרבות', text: '+', onclick: function () { zoomIn(); } });
		var crumbs = h('ol', { class: 'tk-tl__crumbs', 'aria-label': 'התקופה המוצגת' });
		var nav = h('div', { class: 'tk-tl__nav' }, [zOut, zIn, crumbs]);
		var strip = h('div', { class: 'tk-tl__scroll', tabindex: '0', role: 'region', 'aria-label': 'סקירה לפי תקופות' });
		var list = h('div', { class: 'tk-tl__listwrap' });
		var storyNote = hasStory ? null : h('p', { class: 'tk-notice tk-notice--soft', text: 'האירועים לפי כתב האישום (המסלול "מה קרה") יוצגו כאן אחרי שהמדריכים לתיקים יפורסמו. בינתיים מוצג מסלול המשפט.' });
		[bar, storyNote, nav, live, strip, list].forEach(function (n) { if (n) { root.appendChild(n); } });

		var mq = window.matchMedia ? window.matchMedia(NARROW) : null;
		function narrow() { return mq ? mq.matches : false; }
		if (mq) {
			var onChange = function () { if (narrow() && S.path.length) { S.open[S.path[LEVELS.indexOf('year')] || ''] = true; } render(); };
			if (mq.addEventListener) { mq.addEventListener('change', onChange); } else if (mq.addListener) { mq.addListener(onChange); }
		}
		if (!narrow()) { kindBox.open = true; }

		function syncUrl() {
			if (!window.history || !history.replaceState || !window.URL) { return; }
			try {
				var u = new URL(window.location.href);
				if (S.cs) { u.searchParams.set('tk_case', S.cs); } else { u.searchParams.delete('tk_case'); }
				if (S.proc) { u.searchParams.set('tk_all', '1'); } else { u.searchParams.delete('tk_all'); }
				history.replaceState(null, '', u.toString());
			} catch (err) { /* ignore */ }
		}

		// ---------------------------------------------------------------- zoom
		function zoomTo(k) {
			if (S.path.length >= LEVELS.length - 1) { return; }
			S.path.push(k);
			S.openEv = null;
			render(true);
		}
		function zoomOut() {
			if (!S.path.length) { return; }
			S.path.pop();
			render(true);
		}
		function zoomIn() {
			var lv = LEVELS[S.path.length];
			var scope = events.filter(function (e) { return visible(e) && inPath(e); });
			var target = null;
			if (S.openEv) {
				var sel = events.filter(function (e) { return e.id === S.openEv; })[0];
				if (sel && scope.indexOf(sel) >= 0) { target = key(sel, lv); }
			}
			if (!target) {
				for (var i = scope.length - 1; i >= 0; i--) { if (zoomable(lv, key(scope[i], lv))) { target = key(scope[i], lv); break; } }
			}
			if (target && zoomable(lv, target)) { zoomTo(target); }
		}

		// ---------------------------------------------------------------- events
		function linkLabel(e) {
			if (e.kind === 'indictment_fact') { return 'לעמוד התיק'; }
			if (e.kind === 'hearing') { return 'לדף הדיון'; }
			if (e.kind === 'hearing_day') { return 'להודעת בית המשפט'; }
			return 'למסמך המלא';
		}
		function detail(e, id, headingTag) {
			var meta = h('p', { class: 'tk-tl__dmeta' }, [
				h('time', { datetime: e.date, text: fmt(e) }),
				h('span', { class: 'tk-badge' + (e.kind === 'hearing_day' ? ' tk-badge--notice' : ''), text: e.track === 'story' ? TRACK_SHORT.story : ((D.kinds && D.kinds[e.kind]) || e.kind) }),
				e.sig === 'procedural' ? h('span', { class: 'tk-badge tk-badge--procedural', text: 'פרוצדורלי' }) : null
			].concat(e.cases.map(function (k) { return h('span', { class: 'tk-case-badge tk-case--' + k, text: 'תיק ' + k }); })));
			var kids = [h(headingTag, { text: e.title }), meta];
			if (e.text && e.text !== e.title) { kids.push(h('p', { class: 'tk-tl__dtext', text: e.text })); }
			if (e.kind === 'hearing' && e.nw.length) { kids.push(h('p', { class: 'tk-tl__dtext tk-muted', text: 'לפי הודעת בית המשפט העידו: ' + e.nw.join(', ') })); }
			var chips = e.cits.filter(function (c) { return cits[c]; }).map(function (c) {
				return h('a', { class: 'tk-chip', href: cits[c].url, title: cits[c].title, text: cits[c].label });
			});
			if (chips.length) { kids.push(h('p', { class: 'tk-tl__dcits' }, [h('span', { class: 'tk-muted', text: 'מקור: ' })].concat(chips))); }
			if (e.url) { kids.push(h('p', {}, [h('a', { class: 'tk-button', href: e.url, text: linkLabel(e) })])); }
			kids.push(h('button', { type: 'button', class: 'tk-tl__close', 'aria-label': 'סגירת הפרטים', text: '×', onclick: function () { toggle(e, true); } }));
			var panel = h('div', { class: 'tk-tl__detail' + caseClass(e), id: id, role: 'region', 'aria-label': e.title, tabindex: '-1' }, kids);
			panel.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { toggle(e, true); } });
			return panel;
		}
		function toggle(e, refocus) {
			S.openEv = S.openEv === e.id ? null : e.id;
			render();
			var btn = root.querySelector('[data-ev="' + CSS.escape(e.id) + '"]');
			if (S.openEv && btn) {
				var p = document.getElementById(btn.getAttribute('aria-controls'));
				if (p) { p.focus(); }
			} else if (refocus && btn) { btn.focus(); }
		}
		function evItem(e, withTrack) {
			var pid = base + '-d-' + e.id;
			var open = S.openEv === e.id;
			var btn = h('button', {
				type: 'button', class: 'tk-tl__ev tk-tl__ev--' + e.track + (e.kind === 'hearing_day' ? ' tk-tl__ev--notice' : '') + (e.sig === 'procedural' ? ' tk-tl__ev--proc' : '') + caseClass(e), 'aria-expanded': String(open), 'aria-controls': pid, 'data-ev': e.id,
				onclick: function () { toggle(e, false); }
			}, [
				withTrack && e.track === 'story' ? h('span', { class: 'tk-tl-m__track', text: TRACK_SHORT.story }) : null,
				h('span', { class: 'tk-tl__evdate', text: fmt(e) + (e.track === 'trial' && e.kind !== 'hearing' && e.kind !== 'hearing_day' ? ' · ' + ((D.kinds && D.kinds[e.kind]) || '') : '') + (e.sig === 'procedural' ? ' · פרוצדורלי' : '') }),
				e.title
			]);
			var li = h('li', {}, [btn]);
			if (open) { li.appendChild(detail(e, pid, 'h4')); }
			return li;
		}

		// ---------------------------------------------------------------- wide view
		function renderStrip(scope) {
			var lv = LEVELS[S.path.length];
			var cols = columns(lv, scope);
			var tracks = ['story', 'trial'].filter(function (t) { return S.tracks[t] && (t === 'trial' || hasStory); });
			var thead = h('tr', {}, [h('th', { scope: 'col', class: 'tk-tl__rowh' }, [h('span', { class: 'screen-reader-text', text: 'מסלול' })])].concat(cols.map(function (k) {
				var z = zoomable(lv, k);
				return h('th', { scope: 'col' }, [z
					? h('button', { type: 'button', class: 'tk-tl__colbtn', text: label(lv, k, false), 'aria-label': 'התקרבות אל ' + label(lv, k, true), onclick: function () { zoomTo(k); } })
					: h('span', { class: 'tk-tl__collabel', text: label(lv, k, false), title: label(lv, k, true) })]);
			})));
			var rows = tracks.map(function (t) {
				return h('tr', {}, [h('th', { scope: 'row', class: 'tk-tl__rowh tk-tl__rowh--' + t, text: TRACK[t] })].concat(cols.map(function (k) {
					var evs = scope.filter(function (e) { return e.track === t && key(e, lv) === k; });
					if (!evs.length) { return h('td', { class: 'tk-tl__cell' }); }
					var dots = h('span', { class: 'tk-tl__dots', 'aria-hidden': 'true' }, evs.slice(0, 12).map(function (e) {
						return h('span', { class: dotClass(e) });
					}));
					var z = zoomable(lv, k);
					return h('td', { class: 'tk-tl__cell' }, [h('button', {
						type: 'button', class: 'tk-tl__sum',
						'aria-label': label(lv, k, true) + ', ' + TRACK[t] + ': ' + nEv(evs.length) + (z ? '. התקרבות' : '. מעבר לרשימה'),
						onclick: function () { if (z) { zoomTo(k); } else { goGroup(k); } }
					}, [dots, h('span', { class: 'tk-tl__n', text: String(evs.length) })])]);
				})));
			});
			var table = h('table', { class: 'tk-tl__table' }, [
				h('caption', { class: 'screen-reader-text', text: 'מספר האירועים בכל תקופה ובכל מסלול' }),
				h('thead', {}, [thead]), h('tbody', {}, rows)
			]);
			table.style.minWidth = (6.5 + cols.length * 3) + 'rem';
			strip.textContent = '';
			strip.appendChild(table);
		}
		function goGroup(k) {
			var g = document.getElementById(base + '-g-' + k);
			if (g) { g.scrollIntoView({ block: 'start' }); g.focus(); }
		}
		function renderList(scope, lv) {
			list.textContent = '';
			var groups = {};
			var order = [];
			scope.forEach(function (e) {
				var k = key(e, lv);
				if (!groups[k]) { groups[k] = []; order.push(k); }
				groups[k].push(e);
			});
			order.sort();
			if (!order.length) {
				list.appendChild(h('p', { class: 'tk-tl__empty', text: 'אין אירועים שמתאימים לסינון בתקופה הזאת.' }));
				return;
			}
			var both = S.tracks.story && S.tracks.trial && scope.some(function (e) { return e.track === 'story'; });
			// at the widest level each period shows a few events per track; the rest is one zoom away
			var cap = (lv === 'decade' || lv === 'year') ? 3 : Infinity;
			function evList(te, withTrack, k) {
				var shown = te.slice(0, cap);
				var ol = h('ol', { class: 'tk-tl__evs' }, shown.map(function (e) { return evItem(e, withTrack); }));
				if (te.length > shown.length && zoomable(lv, k)) {
					ol.appendChild(h('li', {}, [h('button', { type: 'button', class: 'tk-tl__rest', text: 'ועוד ' + (te.length - shown.length) + ' — הצגת כל ' + label(lv, k, true),
						onclick: function () { zoomTo(k); } })]));
				}
				return ol;
			}
			order.forEach(function (k) {
				var evs = groups[k];
				var head = h('h3', { class: 'tk-tl__gh' }, [label(lv, k, true)]);
				if (zoomable(lv, k)) {
					head.appendChild(h('button', { type: 'button', class: 'tk-tl__more', text: 'התקרבות', 'aria-label': 'התקרבות אל ' + label(lv, k, true), onclick: function () { zoomTo(k); } }));
				}
				var body;
				if (both) {
					body = h('div', { class: 'tk-tl__cols' }, ['story', 'trial'].map(function (t) {
						var te = evs.filter(function (e) { return e.track === t; });
						return h('div', { class: 'tk-tl__col tk-tl__col--' + t }, [
							h('p', { class: 'tk-tl__colh', text: TRACK[t] }),
							te.length ? evList(te, false, k) : h('p', { class: 'tk-tl__empty', text: '—' })
						]);
					}));
				} else {
					body = evList(evs, true, k);
				}
				list.appendChild(h('section', { class: 'tk-tl__grp', id: base + '-g-' + k, tabindex: '-1', 'aria-label': label(lv, k, true) }, [head, body]));
			});
		}
		function renderCrumbs() {
			crumbs.textContent = '';
			var items = [{ text: 'כל השנים', depth: 0 }];
			S.path.forEach(function (k, i) { items.push({ text: label(LEVELS[i], k, true), depth: i + 1 }); });
			items.forEach(function (it, i) {
				var cur = i === items.length - 1;
				crumbs.appendChild(h('li', {}, [h('button', {
					type: 'button', class: 'tk-tl__crumb', text: it.text, 'aria-current': cur ? 'true' : null, disabled: cur ? true : null,
					onclick: function () { S.path = S.path.slice(0, it.depth); render(true); }
				})]));
			});
		}

		// ---------------------------------------------------------------- narrow view
		function renderMobile(all) {
			list.textContent = '';
			var years = {};
			var order = [];
			all.forEach(function (e) {
				var y = String(e.y);
				if (!years[y]) { years[y] = []; order.push(y); }
				years[y].push(e);
			});
			order.sort();
			if (!order.length) {
				list.appendChild(h('p', { class: 'tk-tl__empty', text: 'אין אירועים שמתאימים לסינון.' }));
				return;
			}
			if (!order.some(function (y) { return S.open[y]; })) {
				var pick = order[order.length - 1];
				if (S.cs) {
					var st = order.filter(function (y) { return years[y].some(function (e) { return e.track === 'story'; }); });
					if (st.length) { pick = st[0]; }
				}
				S.open[pick] = true;
			}
			var wrap = h('div', { class: 'tk-tl-m' });
			order.forEach(function (y) {
				var evs = years[y];
				var open = !!S.open[y];
				var pid = base + '-y-' + y;
				var btn = h('button', { type: 'button', class: 'tk-tl-m__ybtn', 'aria-expanded': String(open), 'aria-controls': pid, onclick: function () {
					S.open[y] = !S.open[y];
					render();
					var b = root.querySelector('[aria-controls="' + pid + '"]');
					if (b) { b.focus(); }
				} }, [
					h('strong', { text: y }),
					h('span', { class: 'tk-tl__dots', 'aria-hidden': 'true' }, evs.slice(0, 14).map(function (e) {
						return h('span', { class: dotClass(e) });
					})),
					h('span', { class: 'tk-tl__n', text: nEv(evs.length) })
				]);
				var sec = h('section', { class: 'tk-tl-m__year' }, [h('h3', { class: 'tk-tl-m__yh' }, [btn])]);
				var body = h('div', { id: pid, hidden: open ? null : true });
				if (open) {
					var months = {};
					var mo = [];
					evs.forEach(function (e) {
						var k = key(e, 'month');
						if (!months[k]) { months[k] = []; mo.push(k); }
						months[k].push(e);
					});
					mo.sort().forEach(function (k) {
						body.appendChild(h('h4', { class: 'tk-tl-m__month', text: label('month', k, true) }));
						body.appendChild(h('ol', { class: 'tk-tl-m__list' }, months[k].map(function (e) { return evItem(e, true); })));
					});
				}
				sec.appendChild(body);
				wrap.appendChild(sec);
			});
			list.appendChild(wrap);
		}

		// ---------------------------------------------------------------- render
		function render(announce) {
			caseNote.hidden = !S.cs;
			var vis = events.filter(visible);
			if (narrow()) {
				nav.hidden = true;
				strip.hidden = true;
				renderMobile(vis);
				live.textContent = nEv(vis.length) + (S.cs ? ' · תיק ' + S.cs : '');
				return;
			}
			nav.hidden = false;
			strip.hidden = false;
			var scope = vis.filter(inPath);
			var lv = LEVELS[S.path.length];
			zOut.disabled = !S.path.length;
			zIn.disabled = S.path.length >= LEVELS.length - 1 || !scope.some(function (e) { return zoomable(lv, key(e, lv)); });
			renderCrumbs();
			renderStrip(scope);
			renderList(scope, lv);
			var where = S.path.length ? label(LEVELS[S.path.length - 1], S.path[S.path.length - 1], true) : 'כל השנים';
			live.textContent = scope.length + ' אירועים · ' + where + (S.cs ? ' · תיק ' + S.cs : '');
			if (announce) { live.setAttribute('aria-live', 'polite'); }
		}
		render();
	}

	if (!window.CSS || !CSS.escape) {
		window.CSS = window.CSS || {};
		CSS.escape = function (s) { return String(s).replace(/[^a-zA-Z0-9_\-]/g, '\\$&'); };
	}
	document.querySelectorAll('.tk-tl').forEach(init);
}());
