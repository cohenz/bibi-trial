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
			// a new answer takes about a minute: show what is being done and why (2.7.3, 2.7.8)
			var wait = progress(root, out);
			// 2.7.8: a defense-lens answer takes about a minute. If the site stops waiting first, ask once more: the
			// server then waits for the answer being written (it is not written, or paid for, twice).
			function send(attempt) {
				return fetch(root.getAttribute('data-endpoint'), {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ question: question })
				}).then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
					.then(function (res) {
						if (res.status === 503 && res.body && res.body.retry && attempt < 2) { return send(attempt + 1); }
						return res;
					});
			}
			send(0)
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
				.then(function () { wait.stop(); btn.disabled = false; out.setAttribute('aria-busy', 'false'); });
		});
	}
	/* The waiting panel: a moving bar, the steps the answer goes through (each ticks when its usual time has passed)
	 * and one line on why it takes time. Text for screen readers is announced once, not at every step. */
	function progress(root, out) {
		var n = function (a) { var v = parseInt(root.getAttribute(a) || '', 10); return v > 0 ? v.toLocaleString('he-IL') : ''; };
		var h = n('data-hearings'), w = n('data-witnesses'), d = n('data-documents');
		var scope = h ? 'בפרוטוקולים של ' + h + ' ימי דיון' + (w ? ', בסקירות של ' + w + ' עדים' : '') + (d ? ' וב־' + d + ' מסמכים' : '')
			: 'בפרוטוקולים, בסקירות העדים ובמסמכים שפורסמו';
		var steps = [
			[0, 'מחפש ' + scope],
			[4, 'בוחר את הקטעים הרלוונטיים ביותר, ובהם החקירות הנגדיות'],
			[10, 'מנסח תשובה מתוך הקטעים האלה בלבד'],
			[35, 'מודל נפרד בודק כל משפט מול המקור'],
			[60, 'מסיים את הבדיקה…']
		];
		out.textContent = '';
		var box = document.createElement('div');
		box.className = 'tk-wait';
		box.innerHTML = '<div class="tk-wait__bar" aria-hidden="true"><span></span></div><ol class="tk-wait__steps"></ol>' +
			'<p class="tk-wait__why">תשובה מקיפה לוקחת בדרך כלל כדקה: עוברים על כל החומר שפורסם, ומודל שני מאמת כל משפט מול הפרוטוקול, כך שלכל טענה בתשובה יש מקור.</p>' +
			'<p class="tk-wait__t" aria-hidden="true"></p>';
		out.appendChild(box);
		var sr = document.createElement('p');
		sr.className = 'tk-sr';
		sr.textContent = 'מחפש ומנסח תשובה. זה לוקח בדרך כלל כדקה.';
		out.appendChild(sr);
		var list = box.querySelector('.tk-wait__steps'), clock = box.querySelector('.tk-wait__t'), t0 = Date.now();
		steps.forEach(function (s) {
			var li = document.createElement('li');
			li.className = 'tk-wait__s';
			li.textContent = s[1];
			list.appendChild(li);
		});
		function tick() {
			var sec = Math.floor((Date.now() - t0) / 1000), items = list.children, cur = 0;
			steps.forEach(function (s, i) { if (sec >= s[0]) { cur = i; } });
			for (var i = 0; i < items.length; i++) {
				items[i].className = 'tk-wait__s' + (i < cur ? ' is-done' : i === cur ? ' is-now' : '');
			}
			clock.textContent = sec >= 5 ? sec + ' שניות' : '';
		}
		tick();
		var timer = setInterval(tick, 1000);
		return { stop: function () { clearInterval(timer); } };
	}
	document.querySelectorAll('.tk-ask').forEach(init);
}());
