/* Visitors' questions (2.7.8): topic chips filter the list; opening a question is counted (once a day per visitor,
 * server-side), which orders the list by what readers care about; #q-<id> in the address opens that question. */
(function () {
	'use strict';
	function init(root) {
		var chips = root.querySelectorAll('.tk-qs__chip');
		var items = root.querySelectorAll('.tk-q');
		var endpoint = root.getAttribute('data-endpoint') || '';
		chips.forEach(function (c) {
			c.addEventListener('click', function () {
				var t = c.getAttribute('data-topic') || '';
				chips.forEach(function (o) { o.setAttribute('aria-pressed', o === c ? 'true' : 'false'); });
				items.forEach(function (q) { q.hidden = !!t && q.getAttribute('data-topic') !== t; });
			});
		});
		items.forEach(function (q) {
			var counted = false;
			q.addEventListener('toggle', function () {
				if (!q.open || counted || !endpoint) { return; }
				counted = true;
				try {
					fetch(endpoint + encodeURIComponent(q.getAttribute('data-id')) + '/open', { method: 'POST', keepalive: true })
						.catch(function () {});
				} catch (e) { /* counting is best effort */ }
			});
		});
		var h = (location.hash || '').replace('#', '');
		if (h) {
			var target = document.getElementById(h);
			if (target && target.classList.contains('tk-q')) { target.open = true; target.scrollIntoView({ block: 'start' }); }
		}
	}
	document.querySelectorAll('.tk-qs').forEach(init);
}());
