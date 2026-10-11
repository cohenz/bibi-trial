/* Trial Knowledge — hearing page tabs (progressive enhancement).
 * Without JS the tab list is a list of anchors and every panel is visible.
 * With JS: ARIA tabs, arrow keys, the active tab lives in the URL hash (#tk-tab-full)
 * so it survives reloads and the transcript pager (whose links also carry ?tk_tab=full#tk-tab-full). */
(function () {
	'use strict';
	function init(root) {
		var links = Array.prototype.slice.call(root.querySelectorAll('.tk-tabs__tab'));
		var panels = Array.prototype.slice.call(root.querySelectorAll('.tk-tabs__panel'));
		if (!links.length || links.length !== panels.length) { return; }
		var list = root.querySelector('.tk-tabs__list');
		list.setAttribute('role', 'tablist');
		links.forEach(function (a, i) {
			a.parentNode.setAttribute('role', 'presentation');
			a.setAttribute('role', 'tab');
			a.setAttribute('aria-controls', panels[i].id);
			a.removeAttribute('aria-current');
			panels[i].setAttribute('role', 'tabpanel');
			panels[i].setAttribute('aria-labelledby', a.id);
			panels[i].setAttribute('tabindex', '-1');
		});
		root.classList.add('tk-tabs--js');

		function byName(name) {
			for (var i = 0; i < links.length; i++) { if (links[i].getAttribute('data-tab') === name) { return i; } }
			return -1;
		}
		function select(i, focusTab, updateHash) {
			links.forEach(function (a, j) {
				var on = j === i;
				a.setAttribute('aria-selected', on ? 'true' : 'false');
				a.setAttribute('tabindex', on ? '0' : '-1');
				panels[j].classList.toggle('is-active', on);
			});
			if (focusTab) { links[i].focus(); }
			if (updateHash && window.history && history.replaceState) {
				history.replaceState(null, '', '#' + panels[i].id);
			}
		}
		function fromHash() {
			var h = decodeURIComponent((location.hash || '').slice(1));
			if (!h) { return -1; }
			var el = document.getElementById(h);
			if (!el) { return -1; }
			for (var i = 0; i < panels.length; i++) { if (panels[i] === el || panels[i].contains(el)) { return i; } }
			return -1;
		}

		var start = fromHash();
		if (start < 0) { start = byName(root.getAttribute('data-active') || 'summary'); }
		select(start < 0 ? 0 : start, false, false);
		// a deep link to a passage (#su_…) inside the transcript: scroll to it once the panel is visible
		var target = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
		if (target && !target.classList.contains('tk-tabs__panel')) { target.scrollIntoView(); }

		links.forEach(function (a, i) {
			a.addEventListener('click', function (ev) { ev.preventDefault(); select(i, false, true); });
			a.addEventListener('keydown', function (ev) {
				var k = ev.key, n = links.length, j = -1;
				// RTL: ArrowLeft moves to the next tab
				if (k === 'ArrowLeft') { j = (i + 1) % n; }
				else if (k === 'ArrowRight') { j = (i - 1 + n) % n; }
				else if (k === 'Home') { j = 0; }
				else if (k === 'End') { j = n - 1; }
				if (j >= 0) { ev.preventDefault(); select(j, true, true); }
			});
		});
		window.addEventListener('hashchange', function () {
			var i = fromHash();
			if (i >= 0) { select(i, false, false); }
		});
	}
	document.querySelectorAll('[data-tk-tabs]').forEach(init);
}());
