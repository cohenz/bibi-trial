/* Trial Knowledge — quick review (2.6).
 * One item at a time: what it is, why it waits for a person (plain words), the text with the problem marked,
 * and two answers. A decision advances at once and is sent after UNDO_MS, so it can still be taken back.
 * Keys: Y yes · N no · S / ← skip · U undo. */
(function () {
	'use strict';
	var R = window.TKReview;
	var card = document.getElementById('tk-qr-card');
	if (!R || !card) { return; }
	var toast = document.getElementById('tk-qr-toast');
	var progress = document.querySelector('.tk-qr__progress');
	var UNDO_MS = 5000;

	var TYPE_HE = { protocol: 'פרוטוקול', decision: 'החלטה', motion: 'בקשה', response: 'תגובה', notice: 'הודעה', affidavit: 'תצהיר',
		indictment: 'כתב אישום', exhibit: 'מוצג', other: 'מסמך' };
	var FLAG_HE = {
		motive_or_conspiracy: 'ייחוס מניע פוליטי, קנוניה או "תפירת תיק"',
		investigator_offense: 'ייחוס עבירה או התנהגות פסולה לחוקרים, למשטרה או לתביעה',
		witness_lied: 'קביעה שעד שיקר',
		final_legal_conclusion: 'מילים של הכרעת דין ("אשם", "הורשע", "קיבל שוחד")',
		court_determined_wording: 'ניסוח של קביעה של בית המשפט'
	};
	// the same phrases the server's risk check looks for (simplified), to mark them in the text
	var FLAG_RE = {
		motive_or_conspiracy: /מניע\s*פוליטי|קנוניה|תפירת\s*תיק|תפור|רדיפה\s*פוליטית|הפיכה\s*משפטית|ציד\s*מכשפות|להפיל\s*את/g,
		investigator_offense: /(?:החוקרים|המשטרה|הפרקליטות|הפרקליטים|התביעה)\s*(?:עבר|עברו|ביצע|ביצעו)\s*עביר\S*|שיבוש\s*הליכי\S*|עינוי|עינו|סחיטה|איימו\s*על|הדליפו/g,
		witness_lied: /שיקר\S*|שקרן\S*|עדות\s*שקר|משקר\S*/g,
		final_legal_conclusion: /אשם|הורשע\S*|זוכה|זיכוי|הרשעה|ביצע\s*(?:את\s*)?(?:ה)?עביר\S*|לקח\s*שוחד|קיבל\s*שוחד/g,
		court_determined_wording: /בית\s*המשפט\s*(?:קבע|פסק|הכריע|החליט|דחה|קיבל)|(?:השופט|השופטת|השופטים|ההרכב)\s*(?:קבע|קבעה|קבעו|פסק|פסקה|הכריע|הכריעה|החליט|החליטה)|נקבע\s*(?:כי|ש)/g
	};
	var PROBLEM_HE = {
		missing_citation: 'אין הפניה למקור',
		unknown_source_unit: 'ההפניה מובילה לקטע שלא קיים',
		unpublished_source_unit: 'ההפניה מובילה לקטע שעוד לא פורסם (יפורסם יחד עם הפריט)',
		low_lexical_support: 'הניסוח רחוק מהטקסט במקור — לוודא שהמשפט נאמן למה שנאמר',
		verifier_not_confirmed: 'בדיקת מודל נוסף לא אישרה את המשפט במלואו',
		verifier_requested_human: 'בדיקת מודל נוסף ביקשה עין אנושית',
		not_verified: 'המשפט לא עבר בדיקה של מודל נוסף',
		allegation_stated_as_fact: 'טענה מכתב האישום מנוסחת כאילו היא עובדה',
		determination_wording_without_ruling: 'ניסוח של "בית המשפט קבע" בלי החלטה במקור',
		determination_wording_without_court_text: 'ניסוח של "בית המשפט קבע" בלי דברי בית המשפט במקור',
		absolute_wording_without_status_rule: 'ניסוח מוחלט ("הוכח", "הופרך")',
		quote_not_in_source: 'ציטוט שלא נמצא במקור',
		attribution_speaker_mismatch: 'הדברים מיוחסים לדובר אחר מזה שבמקור',
		witness_not_in_cited_text: 'שם העד לא מופיע בקטע המצוטט',
		weakening_material_omitted: 'הושמט חומר שמחליש את הטענה',
		writer_verifier_disagreement: 'מחלוקת בין המודל הכותב למודל הבודק',
		sensitive_item_single_model_family: 'תוכן רגיש שנבדק רק במודל אחד',
		affirmation_not_verified: 'אישור/הכחשה שלא נבדקו',
		affirmation_must_cite_question_and_answer: 'אישור/הכחשה בלי הפניה לשאלה ולתשובה'
	};
	var BLOCK_HE = { one_line: 'בשורה אחת', overview: 'סקירה', defendants: 'הנאשמים', alleged: 'מה טוען כתב האישום', people: 'מי מעורב',
		charges: 'האישומים', events: 'ציר הזמן', role: 'מי העד', testimony: 'עיקרי העדות' };

	function el(tag, attrs, kids) {
		var n = document.createElement(tag);
		Object.keys(attrs || {}).forEach(function (k) {
			if (k === 'text') { n.textContent = attrs[k]; } else if (k === 'onclick') { n.addEventListener('click', attrs[k]); } else if (attrs[k] !== null && attrs[k] !== undefined) { n.setAttribute(k, attrs[k]); }
		});
		(kids || []).forEach(function (c) { if (c !== null && c !== undefined) { n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); } });
		return n;
	}
	function post(action, data) {
		var body = new FormData();
		body.append('action', action);
		body.append('_ajax_nonce', R.nonce);
		Object.keys(data || {}).forEach(function (k) { body.append(k, data[k]); });
		return fetch(R.ajax, { method: 'POST', credentials: 'same-origin', body: body }).then(function (r) {
			return r.json().then(function (j) { return { ok: !!(j && j.success), data: j ? j.data : null }; }, function () { return { ok: false, data: { message: 'HTTP ' + r.status } }; });
		}, function () { return { ok: false, data: { message: 'אין חיבור' } }; });
	}
	function fmtDate(iso) {
		var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
		return m ? (+m[3]) + '.' + (+m[2]) + '.' + m[1] : (iso || '');
	}

	// ---- queue
	var all = [], filter = 'all', list = [], pos = 0, cache = {}, done = 0;
	function isIssue(t) { return t.artifact_state === 'human_review_required' || (t.risk_flags || []).length > 0 || t.object_type !== 'artifact'; }
	function applyFilter() {
		list = all.filter(function (t) { return filter === 'all' || (filter === 'issue' ? isIssue(t) : !isIssue(t)); });
		pos = 0;
		document.querySelectorAll('[data-count]').forEach(function (n) {
			var k = n.getAttribute('data-count');
			n.textContent = all.filter(function (t) { return k === 'all' || (k === 'issue' ? isIssue(t) : !isIssue(t)); }).length;
		});
		document.querySelectorAll('.tk-qr__chip').forEach(function (b) { b.classList.toggle('is-on', b.getAttribute('data-filter') === filter); });
		show();
	}
	function loadQueue() {
		post('tk_review_tasks', {}).then(function (r) {
			if (!r.ok) { card.textContent = ''; card.appendChild(el('p', { class: 'tk-err', text: (r.data && r.data.message) || 'שגיאה בטעינת התור' })); return; }
			all = ((r.data && r.data.items) || []).filter(function (t) { return !t.status || t.status === 'open'; });
			applyFilter();
		});
	}
	document.querySelectorAll('.tk-qr__chip').forEach(function (b) {
		b.addEventListener('click', function () { flush(); filter = b.getAttribute('data-filter'); applyFilter(); });
	});

	function fetchCard(t) {
		if (t.object_type !== 'artifact') { return Promise.resolve({ ok: true, data: { object: t } }); }
		if (!cache[t.object_id]) { cache[t.object_id] = post('tk_review_card', { artifact_id: t.object_id }); }
		return cache[t.object_id];
	}

	// ---- why this item waits for a person
	var srcMap = {};
	function readable(txt) {
		return String(txt || '').replace(/su_[0-9a-f]{26}/g, function (id) {
			var s = srcMap[id];
			return s ? 'עמ׳ ' + s.page + ' ש׳ ' + s.line_start : 'קטע במקור';
		});
	}
	function pathLabel(p) {
		var m;
		if (!p) { return ''; }
		if ((m = /^summary_sentences\/(\d+)/.exec(p))) { return 'משפט ' + (+m[1] + 1); }
		if (/^title/.test(p)) { return 'הכותרת'; }
		if ((m = /^blocks\/(\d+)\/items\/(\d+)/.exec(p))) { return 'פריט ' + (+m[2] + 1) + ' בחלק ' + (+m[1] + 1); }
		if ((m = /^notable_exchanges\/(\d+)/.exec(p))) { return 'שאלה ותשובה ' + (+m[1] + 1); }
		return p;
	}
	function analyse(d) {
		var a = d.artifact || {}, out = { blocked: false, reasons: [], byPath: {} };
		function add(path, text) { if (path) { (out.byPath[path] = out.byPath[path] || []).push(text); } }
		((d.gate_report && d.gate_report.gates) || []).forEach(function (g) {
			if (g.passed) { return; }
			var hard = g.severity && g.severity !== 'review';
			if (hard) { out.blocked = true; }
			(g.details || [{}]).forEach(function (det) {
				var txt = PROBLEM_HE[det.problem] || det.problem || g.gate;
				if (det.overlap !== undefined) { txt += ' (חפיפה ' + Math.round(det.overlap * 100) + '%)'; }
				var paths = det.paths || (det.path ? [det.path] : []);
				paths.forEach(function (p) { add(p, txt); });
				out.reasons.push((hard ? 'חוסם: ' : '') + txt + (paths.length ? ' — ' + paths.map(pathLabel).join(', ') : ''));
			});
		});
		var v = d.verifier_output;
		((v && v.assertions) || []).forEach(function (x) {
			if (x.supported === 'yes' && x.attribution_ok !== false && !x.judicial_overstatement && !x.false_premise) { return; }
			var t = 'המודל הבודק: ' + ({ partial: 'נתמך רק בחלקו', no: 'לא נתמך' }[x.supported] || 'בעייתי') +
				(x.attribution_ok === false ? ', ייחוס שגוי' : '') + (x.judicial_overstatement ? ', מציג יותר ממה שבית המשפט קבע' : '') +
				(x.note ? ' — ' + readable(x.note) : '');
			add(x.path, t);
		});
		(a.risk_flags || []).forEach(function (f) {
			out.reasons.push('תוכן רגיש: ' + (FLAG_HE[f] || f) + '. לבדוק שהדברים מיוחסים למי שאמר אותם ולא מוצגים כעובדה.');
		});
		return out;
	}
	function whyText(d, an) {
		var a = d.artifact || {}, w = d.writer_output || {};
		if (an.blocked) { return { cls: 'block', head: 'לא ניתן לפרסם את הפריט הזה כמו שהוא', items: an.reasons }; }
		if (an.reasons.length) { return { cls: 'issue', head: 'למה זה מחכה לך', items: an.reasons }; }
		var t = w.source_type;
		var msg = a.artifact_type === 'guide' ? 'מדריכים תמיד מחכים לאישור אנושי לפני פרסום.'
			: t === 'other' ? 'סוג המסמך לא זוהה בוודאות, ולכן הוא מתפרסם רק באישור.'
			: (t && /^(exhibit|indictment|affidavit)$/.test(t)) ? 'מסמכים מסוג "' + (TYPE_HE[t] || t) + '" מתפרסמים רק באישור.'
			: t ? 'לא אומת אוטומטית שהמסמך שייך לתיק, ולכן הוא מתפרסם רק באישור.'
			: 'הפריט ממתין לאישור.';
		return { cls: 'clean', head: 'עבר את כל הבדיקות האוטומטיות', items: [msg] };
	}

	// ---- text with problems and risky words marked
	var activeFlags = [];
	function marked(text) {
		var spans = [];
		activeFlags.filter(function (k) { return FLAG_RE[k]; }).forEach(function (k) {
			FLAG_RE[k].lastIndex = 0;
			var m;
			while ((m = FLAG_RE[k].exec(text))) { spans.push([m.index, m.index + m[0].length, k]); if (!m[0].length) { break; } }
		});
		spans.sort(function (x, y) { return x[0] - y[0]; });
		var out = [], at = 0;
		spans.forEach(function (s) {
			if (s[0] < at) { return; }
			out.push(text.slice(at, s[0]));
			out.push(el('mark', { class: 'tk-qr__risk', title: FLAG_HE[s[2]] || s[2], text: text.slice(s[0], s[1]) }));
			at = s[1];
		});
		out.push(text.slice(at));
		return out;
	}
	function sourcesOf(ids, d) {
		var src = {};
		(d.sources || []).forEach(function (s) { src[s.source_unit_id] = s; });
		ids = ids || [];
		if (!ids.length) { return el('p', { class: 'tk-err', text: 'ללא הפניה למקור' }); }
		var ul = el('ul', { class: 'tk-qr__srcs' });
		ids.forEach(function (id) {
			var s = src[id];
			ul.appendChild(el('li', {}, s ? [
				el('span', { class: 'tk-qr__loc', text: 'עמ׳ ' + s.page + ', ש׳ ' + s.line_start + (s.line_end !== s.line_start ? '–' + s.line_end : '') + (s.speaker ? ' · ' + s.speaker : '') }),
				el('q', { text: (s.text || '').length > 600 ? s.text.slice(0, 600) + '…' : (s.text || '') })
			] : [el('span', { class: 'tk-err', text: id })]));
		});
		return ul;
	}
	function line(text, ids, path, d, an) {
		var probs = an.byPath[path] || [];
		var li = el('li', { class: 'tk-qr__line' + (probs.length ? ' is-flag' : '') }, [el('p', {}, marked(text || ''))]);
		if (probs.length) { li.appendChild(el('ul', { class: 'tk-qr__probs' }, probs.map(function (p) { return el('li', { text: p }); }))); }
		var det = el('details', probs.length ? { open: 'open' } : {}, [el('summary', { text: 'מקורות (' + (ids || []).length + ')' }), sourcesOf(ids, d)]);
		li.appendChild(det);
		return li;
	}
	function body(d, an) {
		var w = d.writer_output || {}, a = d.artifact || {}, box = el('div', { class: 'tk-qr__body' });
		if (a.artifact_type === 'guide') {
			(w.blocks || []).forEach(function (b, bi) {
				var ol = el('ol', { class: 'tk-qr__lines' });
				(b.items || []).forEach(function (it, ii) { ol.appendChild(line((it.label ? it.label + ': ' : '') + (it.text || ''), it.citation_ids, 'blocks/' + bi + '/items/' + ii, d, an)); });
				box.appendChild(el('h3', { text: BLOCK_HE[b.block] || b.block }));
				box.appendChild(ol);
			});
			return box;
		}
		var ol = el('ol', { class: 'tk-qr__lines' });
		(w.summary_sentences || []).forEach(function (s, i) { ol.appendChild(line(s.text, s.citation_ids, 'summary_sentences/' + i, d, an)); });
		box.appendChild(ol);
		if (w.significance === 'procedural') {
			box.appendChild(el('p', { class: 'tk-muted', text: 'סומן כמסמך פרוצדורלי' + (w.significance_reason ? ': ' + w.significance_reason : '') + ' (יוצג רק למי שיבקש לראות גם מסמכים פרוצדורליים).' }));
		}
		return box;
	}

	// ---- render one item
	function show() {
		card.textContent = '';
		if (!list.length) {
			card.appendChild(el('div', { class: 'tk-qr__empty' }, [el('p', { class: 'tk-qr__done', text: '✓' }),
				el('p', { text: filter === 'all' ? 'אין פריטים שממתינים לביקורת.' : 'אין פריטים בקבוצה הזאת.' })]));
			progress.textContent = done ? 'הוחלט על ' + done + ' פריטים בסבב הזה.' : '';
			return;
		}
		if (pos >= list.length) { pos = 0; }
		var t = list[pos];
		progress.textContent = 'פריט ' + (pos + 1) + ' מתוך ' + list.length + (done ? ' · הוחלט על ' + done : '');
		card.appendChild(el('p', { class: 'tk-muted', text: 'טוען…' }));
		fetchCard(t).then(function (r) {
			if (list[pos] !== t) { return; }
			card.textContent = '';
			if (!r.ok) {
				card.appendChild(el('p', { class: 'tk-err', text: (r.data && r.data.message) || 'שגיאה' }));
				card.appendChild(buttons(t, true));
				return;
			}
			if (t.object_type !== 'artifact') {
				card.appendChild(el('p', { class: 'tk-qr__kicker', text: t.object_type === 'qa_exchange' ? 'שאלה ותשובה' : 'דברי בית המשפט' }));
				card.appendChild(el('div', { class: 'tk-qr__why tk-qr__why--issue' }, [el('strong', { text: 'למה זה מחכה לך' }), el('p', { text: t.reason || '' })]));
				card.appendChild(buttons(t, false));
				return;
			}
			var d = r.data, a = d.artifact || {}, w = d.writer_output || {}, ctx = d.context || {};
			activeFlags = a.risk_flags || [];
			srcMap = {};
			(d.sources || []).forEach(function (s) { srcMap[s.source_unit_id] = s; });
			var an = analyse(d), why = whyText(d, an);
			var kind = a.artifact_type === 'guide' ? 'מדריך' : a.object_type === 'hearing' ? 'תקציר דיון' : 'תקציר ' + (TYPE_HE[w.source_type] || 'מסמך');
			var title = (w.title && (w.title.text || w.title)) || (a.object_type === 'hearing' ? 'דיון מיום ' + fmtDate(ctx.date) : '') || w.title || '';
			var head = el('div', { class: 'tk-qr__head' }, [
				el('p', { class: 'tk-qr__kicker' }, [kind, a.object_type === 'hearing' && ctx.date ? ' · ' + fmtDate(ctx.date) : '',
					(ctx.witnesses || []).length ? ' · ' + ctx.witnesses.join(', ') : '']),
				el('h2', { class: 'tk-qr__title' }, marked(typeof title === 'string' ? title : '')),
				ctx.url ? el('a', { href: ctx.url, target: '_blank', rel: 'noopener', class: 'tk-qr__open', text: 'פתיחת המקור באתר ↗' }) : null
			]);
			card.appendChild(head);
			card.appendChild(el('div', { class: 'tk-qr__why tk-qr__why--' + why.cls }, [el('strong', { text: why.head }),
				el('ul', {}, why.items.map(function (x) { return el('li', { text: x }); }))]));
			if (an.byPath.title) { card.appendChild(el('ul', { class: 'tk-qr__probs' }, an.byPath.title.map(function (p) { return el('li', { text: 'הכותרת: ' + p }); }))); }
			card.appendChild(buttons(t, an.blocked));
			card.appendChild(body(d, an));
			card.focus({ preventScroll: true });
			var nx = list[pos + 1];
			if (nx) { fetchCard(nx); }  // ready before it is needed
		});
	}
	function buttons(t, blocked) {
		var yes = el('button', { type: 'button', class: 'button button-primary button-hero tk-qr__yes', text: 'כן, לפרסם (Y)', onclick: function () { decide('yes'); } });
		if (blocked) { yes.disabled = true; yes.title = 'לא ניתן לפרסם עד שהבעיה החוסמת תתוקן'; }
		return el('div', { class: 'tk-qr__actions' }, [yes,
			el('button', { type: 'button', class: 'button button-hero tk-qr__no', text: 'לא לפרסם (N)', onclick: function () { decide('no'); } }),
			el('button', { type: 'button', class: 'button-link tk-qr__skip', text: 'דלג (S)', onclick: skip })]);
	}

	// ---- decisions: sent after UNDO_MS; U takes the last one back
	var pending = null;
	function send(p) {
		var t = p.task;
		var data = t.object_type === 'artifact' ? { kind: 'artifact', artifact_id: t.object_id, decision: p.decision } : { kind: t.object_type, object_id: t.object_id, decision: p.decision };
		return post('tk_review_decide', data).then(function (r) {
			if (!r.ok) {
				say('לא נשמר: ' + ((r.data && r.data.message) || 'שגיאה') + '. הפריט הוחזר לתור.', null);
				all.unshift(t); list.splice(pos, 0, t); done--; show();
			}
		});
	}
	function flush() {
		if (!pending) { return; }
		clearTimeout(pending.timer);
		var p = pending; pending = null;
		send(p);
	}
	function decide(decision) {
		if (!list.length) { return; }
		flush();
		var t = list[pos];
		var btn = card.querySelector('.tk-qr__yes');
		if (decision === 'yes' && btn && btn.disabled) { return; }
		list.splice(pos, 1);
		all.splice(all.indexOf(t), 1);
		done++;
		pending = { task: t, decision: decision, at: pos, timer: setTimeout(function () { var p = pending; pending = null; if (p) { send(p); } hideSay(); }, UNDO_MS) };
		say(decision === 'yes' ? 'פורסם' : 'לא יפורסם', undo);
		applyCounts();
		show();
	}
	function undo() {
		if (!pending) { return; }
		clearTimeout(pending.timer);
		var p = pending; pending = null;
		all.unshift(p.task); list.splice(p.at, 0, p.task); pos = p.at; done--;
		hideSay(); applyCounts(); show();
	}
	function skip() { if (list.length) { pos = (pos + 1) % list.length; show(); } }
	function applyCounts() {
		document.querySelectorAll('[data-count]').forEach(function (n) {
			var k = n.getAttribute('data-count');
			n.textContent = all.filter(function (t) { return k === 'all' || (k === 'issue' ? isIssue(t) : !isIssue(t)); }).length;
		});
	}
	function say(text, onUndo) {
		toast.textContent = '';
		toast.appendChild(el('span', { text: text }));
		if (onUndo) { toast.appendChild(el('button', { type: 'button', class: 'button-link', text: 'ביטול (U)', onclick: onUndo })); }
		toast.hidden = false;
	}
	function hideSay() { toast.hidden = true; }
	window.addEventListener('beforeunload', function () {
		if (!pending) { return; }
		var p = pending, t = p.task, body = new FormData();
		body.append('action', 'tk_review_decide'); body.append('_ajax_nonce', R.nonce); body.append('decision', p.decision);
		body.append('kind', t.object_type === 'artifact' ? 'artifact' : t.object_type);
		body.append(t.object_type === 'artifact' ? 'artifact_id' : 'object_id', t.object_id);
		navigator.sendBeacon(R.ajax, body);
	});
	document.addEventListener('keydown', function (ev) {
		if (ev.ctrlKey || ev.metaKey || ev.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test((ev.target && ev.target.tagName) || '')) { return; }
		var c = ev.code;
		if (c === 'KeyY') { ev.preventDefault(); decide('yes'); }
		else if (c === 'KeyN') { ev.preventDefault(); decide('no'); }
		else if (c === 'KeyS' || c === 'ArrowLeft') { ev.preventDefault(); skip(); }
		else if (c === 'KeyU') { ev.preventDefault(); undo(); }
	});
	loadQueue();
}());
