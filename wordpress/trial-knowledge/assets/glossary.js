/* Trial Knowledge — glossary tooltips.
 * Inside elements with class "tk-glossable", the first occurrence (per section) of every
 * glossary term or alias becomes a button that opens a small popover with a one-line
 * explanation and a link to the glossary entry (or to the case page). Whole-word matching
 * only; never inside links, buttons, headings, citation chips or badges.
 * Data: window.TKGlossary = {terms: [{id, term, aliases, short, url, more}], note, label, close}. */
(function () {
	'use strict';
	var G = window.TKGlossary;
	if (!G || !G.terms || !G.terms.length || !document.querySelector('.tk-glossable')) { return; }

	var LETTERS = 'א-תA-Za-z0-9';
	function norm(s) { return s.replace(/״/g, '"').replace(/׳/g, "'").replace(/[־‐-–]/g, '-'); }
	function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

	var byForm = {};
	G.terms.forEach(function (t) {
		[t.term].concat(t.aliases || []).forEach(function (f) {
			f = norm(String(f || '').trim());
			if (f.length > 1 && !byForm[f]) { byForm[f] = t; }
		});
	});
	var forms = Object.keys(byForm).sort(function (a, b) { return b.length - a.length; });
	if (!forms.length) { return; }
	var alt = forms.map(function (f) {
		return esc(f).replace(/"/g, '["״]').replace(/'/g, "['׳]").replace(/-/g, '[-־‐-–]').replace(/ /g, '\\s+');
	}).join('|');
	var RE = new RegExp('(^|[^' + LETTERS + '])(' + alt + ')(?=$|[^' + LETTERS + '])', 'g');
	var SKIP = 'a, button, h1, h2, h3, h4, h5, h6, strong, .tk-chip, .tk-chips, .tk-badge, .tk-case-badge, .tk-gl, .tk-labelled__label, .tk-charges__who, .tk-people__name, .tk-qa__who, code, pre, script, style, label, textarea, input, select, time';

	var seenByScope = typeof WeakMap === 'function' ? new WeakMap() : null;
	var counter = 0;

	function mark(root) {
		var scope = root.closest('section, article') || root;
		var seen = seenByScope ? (seenByScope.get(scope) || {}) : {};
		if (seenByScope) { seenByScope.set(scope, seen); }
		var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
			acceptNode: function (n) {
				if (!n.nodeValue || n.nodeValue.length < 2) { return NodeFilter.FILTER_REJECT; }
				var p = n.parentElement;
				return p && !p.closest(SKIP) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
			}
		});
		var nodes = [];
		while (walker.nextNode()) { nodes.push(walker.currentNode); }
		nodes.forEach(function (node) {
			var text = node.nodeValue, last = 0, m, frag = null;
			RE.lastIndex = 0;
			while ((m = RE.exec(text)) !== null) {
				var word = m[2];
				var term = byForm[norm(word).replace(/\s+/g, ' ')];
				var start = m.index + m[1].length;
				if (!term || seen[term.id]) { continue; }
				seen[term.id] = true;
				frag = frag || document.createDocumentFragment();
				frag.appendChild(document.createTextNode(text.slice(last, start)));
				var b = document.createElement('button');
				b.type = 'button';
				b.className = 'tk-gl';
				b.textContent = word;
				b.setAttribute('aria-expanded', 'false');
				b.setAttribute('aria-haspopup', 'dialog');
				b.setAttribute('data-term', term.id);
				b.setAttribute('aria-label', word + ' — ' + (G.label || 'הסבר מונח'));
				frag.appendChild(b);
				last = start + word.length;
			}
			if (frag) {
				frag.appendChild(document.createTextNode(text.slice(last)));
				node.parentNode.replaceChild(frag, node);
			}
		});
	}

	var termById = {};
	G.terms.forEach(function (t) { termById[t.id] = t; });

	var pop = null, opener = null;
	function close(returnFocus) {
		if (!pop) { return; }
		pop.parentNode.removeChild(pop);
		pop = null;
		if (opener) {
			opener.setAttribute('aria-expanded', 'false');
			if (returnFocus) { opener.focus(); }
		}
		opener = null;
	}
	function open(btn) {
		var t = termById[btn.getAttribute('data-term')];
		if (!t) { return; }
		close(false);
		opener = btn;
		var id = 'tk-gl-pop-' + (++counter);
		pop = document.createElement('div');
		pop.className = 'tk-gl-pop';
		pop.id = id;
		pop.setAttribute('role', 'dialog');
		pop.setAttribute('aria-labelledby', id + '-t');
		pop.setAttribute('tabindex', '-1');
		pop.setAttribute('dir', 'rtl');
		pop.setAttribute('lang', 'he');
		var h = document.createElement('p');
		h.className = 'tk-gl-pop__t';
		h.id = id + '-t';
		h.textContent = t.term;
		var p = document.createElement('p');
		p.textContent = t.short;
		var more = document.createElement('a');
		more.href = t.url;
		more.textContent = t.more || 'עוד';
		var x = document.createElement('button');
		x.type = 'button';
		x.className = 'tk-gl-pop__x';
		x.setAttribute('aria-label', G.close || 'סגירה');
		x.textContent = '×';
		x.addEventListener('click', function () { close(true); });
		pop.appendChild(h);
		pop.appendChild(p);
		var pm = document.createElement('p');
		pm.appendChild(more);
		pop.appendChild(pm);
		if (G.note) {
			var n = document.createElement('p');
			n.className = 'tk-gl-pop__note';
			n.textContent = G.note;
			pop.appendChild(n);
		}
		pop.appendChild(x);
		document.body.appendChild(pop);
		btn.setAttribute('aria-expanded', 'true');
		btn.setAttribute('aria-controls', id);
		var r = btn.getBoundingClientRect();
		var w = pop.offsetWidth;
		var vw = document.documentElement.clientWidth;
		var left = Math.min(Math.max(16, r.right - w), vw - w - 16);
		pop.style.left = (left + window.pageXOffset) + 'px';
		pop.style.top = (r.bottom + window.pageYOffset + 6) + 'px';
		pop.focus();
	}

	document.addEventListener('click', function (ev) {
		var b = ev.target.closest && ev.target.closest('.tk-gl');
		if (b) {
			if (opener === b) { close(true); } else { open(b); }
			return;
		}
		if (pop && !pop.contains(ev.target)) { close(false); }
	});
	document.addEventListener('keydown', function (ev) {
		if (ev.key === 'Escape' && pop) { close(true); }
	});
	document.addEventListener('focusin', function (ev) {
		if (pop && !pop.contains(ev.target) && ev.target !== opener) { close(false); }
	});

	document.querySelectorAll('.tk-glossable').forEach(mark);
	// content inserted later (Ask answers) is not marked; expose for callers
	window.TKGlossaryMark = mark;
}());
