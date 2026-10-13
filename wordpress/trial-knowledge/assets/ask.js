/* Ask the Trial — front end. The answer HTML is rendered and escaped
 * server-side (TK_Render::answer) from a published-only AnswerEnvelope. */
(function () {
	'use strict';
	function init(root) {
		var form = root.querySelector('.tk-ask__form');
		var out = root.querySelector('.tk-ask__out');
		var q = root.querySelector('.tk-ask__q');
		var btn = root.querySelector('.tk-ask__btn');
		root.querySelectorAll('.tk-ask__ex').forEach(function (b) {
			b.addEventListener('click', function () {
				q.value = b.getAttribute('data-q') || '';
				if (form.requestSubmit) { form.requestSubmit(); } else { form.dispatchEvent(new Event('submit', { cancelable: true })); }
			});
		});
		form.addEventListener('submit', function (ev) {
			ev.preventDefault();
			var question = (q.value || '').trim();
			if (question.length < 2) { q.focus(); return; }
			btn.disabled = true;
			out.setAttribute('aria-busy', 'true');
			out.textContent = 'מחפש בחומר שפורסם…';
			fetch(root.getAttribute('data-endpoint'), {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ question: question })
			}).then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
				.then(function (res) {
					if (res.status === 200 && res.body.html) {
						out.innerHTML = res.body.html; // server-escaped
						var first = out.querySelector('.tk-answer__short');
						if (first) { first.setAttribute('tabindex', '-1'); first.focus(); }
					} else {
						out.textContent = (res.body && res.body.error) || 'לא ניתן לענות כרגע.';
					}
				})
				.catch(function () { out.textContent = 'לא ניתן לענות כרגע.'; })
				.then(function () { btn.disabled = false; out.setAttribute('aria-busy', 'false'); });
		});
	}
	document.querySelectorAll('.tk-ask').forEach(init);
}());
