/* Trial Knowledge — reading aids (2.6), progressive enhancement.
 * 1. Sources pill ("מקורות · N"): the list opens on hover (CSS), keyboard focus (CSS :focus-within)
 *    and tap/click (here: aria-expanded toggles .is-open; Escape or a click elsewhere closes it).
 * 2. Collapsible transcript pages (<details>): "open all" / "close all", "only this page", and a deep
 *    link to a passage (#su_… or #page-N) opens its page before scrolling to it. */
(function () {
	'use strict';

	// ---- sources pills
	function closeAll(except) {
		document.querySelectorAll('[data-tk-srcs].is-open').forEach(function (el) {
			if (el !== except) {
				el.classList.remove('is-open');
				var b = el.querySelector('.tk-srcs__btn');
				if (b) { b.setAttribute('aria-expanded', 'false'); }
			}
		});
	}
	document.addEventListener('click', function (ev) {
		var btn = ev.target.closest && ev.target.closest('.tk-srcs__btn');
		if (btn) {
			ev.preventDefault();
			var pill = btn.closest('[data-tk-srcs]');
			var open = !pill.classList.contains('is-open');
			closeAll(pill);
			pill.classList.toggle('is-open', open);
			btn.setAttribute('aria-expanded', open ? 'true' : 'false');
			if (open) { place(pill); }
			return;
		}
		if (!(ev.target.closest && ev.target.closest('[data-tk-srcs]'))) { closeAll(null); }
	});
	document.addEventListener('keydown', function (ev) {
		if (ev.key === 'Escape') { closeAll(null); }
	});
	// keep the list inside the viewport: open towards the side with more room
	function place(pill) {
		var r = pill.getBoundingClientRect();
		pill.classList.toggle('tk-srcs--flip', r.left < 300 && window.innerWidth - r.right > r.left);
	}
	document.addEventListener('mouseover', function (ev) {
		var pill = ev.target.closest && ev.target.closest('[data-tk-srcs]');
		if (pill && !pill.dataset.tkPlaced) { pill.dataset.tkPlaced = '1'; place(pill); }
	});

	// ---- collapsible transcript
	function pagesOf(root) { return Array.prototype.slice.call(root.querySelectorAll('details.tk-tpage')); }
	document.querySelectorAll('[data-tk-transcript]').forEach(function (root) {
		var pages = pagesOf(root);
		if (!pages.length) { return; }
		root.querySelectorAll('.tk-transcript__tools, .tk-tpage__only').forEach(function (el) { el.hidden = false; });
		root.addEventListener('click', function (ev) {
			var t = ev.target.closest ? ev.target.closest('[data-tk-pages], [data-tk-only]') : null;
			if (!t) { return; }
			ev.preventDefault();
			if (t.hasAttribute('data-tk-only')) {
				var mine = t.closest('details');
				pages.forEach(function (d) { d.open = d === mine; });
				mine.scrollIntoView({ block: 'start' });
			} else {
				var open = t.getAttribute('data-tk-pages') === 'open';
				pages.forEach(function (d) { d.open = open; });
			}
		});
	});
	function openTarget() {
		var id = decodeURIComponent((location.hash || '').slice(1));
		if (!id) { return; }
		var el = document.getElementById(id);
		if (!el) { return; }
		var d = el.tagName === 'DETAILS' ? el : el.closest('details.tk-tpage');
		if (d && !d.open) {
			d.open = true;
			el.scrollIntoView({ block: el === d ? 'start' : 'center' });
		}
		if (el.classList.contains('tk-u')) { el.classList.add('is-target'); }
	}
	// after the tabs script has shown the right panel
	setTimeout(openTarget, 0);
	window.addEventListener('hashchange', openTarget);
}());
