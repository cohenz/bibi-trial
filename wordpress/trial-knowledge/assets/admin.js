/* Trial Knowledge — admin screens (vanilla JS, no build step).
 * Untrusted text is always inserted with textContent, never innerHTML. */
(function () {
	'use strict';
	if (typeof window.TKAdmin === 'undefined') { return; }
	var A = window.TKAdmin;

	function el(tag, attrs, children) {
		var e = document.createElement(tag);
		Object.keys(attrs || {}).forEach(function (k) {
			if (k === 'text') { e.textContent = attrs[k]; }
			else if (k === 'class') { e.className = attrs[k]; }
			else if (k.indexOf('on') === 0) { e.addEventListener(k.slice(2), attrs[k]); }
			else { e.setAttribute(k, attrs[k]); }
		});
		(children || []).forEach(function (c) { if (c) { e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); } });
		return e;
	}

	function post(action, nonce, data) {
		var body = new FormData();
		body.append('action', action);
		body.append('_ajax_nonce', nonce);
		Object.keys(data || {}).forEach(function (k) { body.append(k, data[k]); });
		return fetch(A.ajax, { method: 'POST', body: body, credentials: 'same-origin' })
			.then(function (r) { return r.json().then(function (j) { return { ok: r.ok && j.success, data: j.data }; }); });
	}

	// ------------------------------------------------------------- settings
	var testBtn = document.getElementById('tk-test-connection');
	if (testBtn) {
		testBtn.addEventListener('click', function () {
			var out = document.getElementById('tk-test-result');
			out.textContent = '…';
			post('tk_test_connection', A.nonces.test).then(function (r) { out.textContent = JSON.stringify(r.data, null, 2); });
		});
	}

	// ------------------------------------------------------------- sources
	function sha256Hex(file) {
		return file.arrayBuffer().then(function (buf) { return crypto.subtle.digest('SHA-256', buf); }).then(function (h) {
			return Array.prototype.map.call(new Uint8Array(h), function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
		});
	}

	function logLine(log, text, cls) {
		var li = el('li', { class: cls || '', text: text });
		log.appendChild(li);
		return li;
	}

	var form = document.getElementById('tk-upload-form');
	if (form) {
		form.addEventListener('submit', function (ev) {
			ev.preventDefault();
			var files = document.getElementById('tk-files').files;
			var date = document.getElementById('tk-date').value;
			var crs = document.getElementById('tk-crs').value;
			var kindSel = document.getElementById('tk-kind');
			var kind = kindSel ? kindSel.value : 'auto';
			var log = document.getElementById('tk-upload-log');
			Array.prototype.reduce.call(files, function (p, file) {
				return p.then(function () { return uploadOne(file, date, crs, log, kind); });
			}, Promise.resolve()).then(loadJobs);
		});
	}

	function uploadOne(file, date, crs, log, kind) {
		var line = logLine(log, file.name + ': ' + A.i18n.hashing);
		if (file.type && file.type !== 'application/pdf') {
			line.textContent = file.name + ': ' + A.i18n.failed + ' (PDF)';
			return Promise.resolve();
		}
		return sha256Hex(file).then(function (sha) {
			return post('tk_presign', A.nonces.upload, { filename: file.name, size: file.size, sha256: sha });
		}).then(function (r) {
			if (!r.ok) { throw new Error((r.data && r.data.message) || 'presign failed'); }
			var up = r.data;
			if (up.already_exists) {
				line.textContent = file.name + ': ' + A.i18n.exists;
				return up;
			}
			line.textContent = file.name + ': ' + A.i18n.uploading;
			return fetch(up.url, { method: up.method, headers: up.headers, body: file }).then(function (res) {
				if (!res.ok) { throw new Error('upload HTTP ' + res.status); }
				return up;
			});
		}).then(function (up) {
			line.textContent = file.name + ': ' + A.i18n.creating;
			return post('tk_create_job', A.nonces.upload, { upload_id: up.upload_id, title: file.name.replace(/\.pdf$/i, ''), hearing_date: date, crs: crs, kind: kind || 'auto' });
		}).then(function (r) {
			if (!r.ok) { throw new Error((r.data && r.data.message) || 'job failed'); }
			line.textContent = file.name + ': ' + A.i18n.done + ' — job ' + r.data.job_id;
			line.className = 'tk-ok';
		}).catch(function (e) {
			line.textContent = file.name + ': ' + A.i18n.failed + ' — ' + e.message;
			line.className = 'tk-err';
		});
	}

	var jobsTable = document.getElementById('tk-jobs');
	function loadJobs() {
		if (!jobsTable) { return; }
		post('tk_jobs', A.nonces.jobs).then(function (r) {
			var tbody = jobsTable.querySelector('tbody');
			tbody.textContent = '';
			((r.data && r.data.items) || []).forEach(function (j) {
				var actions = el('td', {}, [
					el('button', { type: 'button', class: 'button', text: 'פרטים', onclick: function () { showJob(j.id); } }),
					j.status === 'failed' ? el('button', { type: 'button', class: 'button', text: 'ניסיון חוזר', onclick: function () {
						post('tk_retry_job', A.nonces.jobs, { job_id: j.id }).then(loadJobs);
					} }) : null
				]);
				tbody.appendChild(el('tr', {}, [
					el('td', { text: (j.created_at || '').slice(0, 19).replace('T', ' ') }),
					el('td', { text: (j.input && j.input.document && j.input.document.title) || '' }),
					el('td', { text: j.status, class: 'tk-status-' + j.status }),
					el('td', { text: j.stage }),
					actions
				]));
			});
		});
	}
	var refresh = document.getElementById('tk-refresh-jobs');
	if (refresh) { refresh.addEventListener('click', loadJobs); loadJobs(); }

	var pollTimer = null;
	function showJob(id) {
		var box = document.getElementById('tk-job-detail');
		clearTimeout(pollTimer);
		post('tk_job', A.nonces.jobs, { job_id: id }).then(function (r) {
			box.textContent = '';
			if (!r.ok) { box.appendChild(el('p', { class: 'tk-err', text: r.data.message })); return; }
			var j = r.data;
			box.appendChild(el('h3', { text: 'job ' + j.id + ' — ' + j.status + ' (' + j.progress.done + '/' + j.progress.total + ')' }));
			var prog = el('progress', { max: String(j.progress.total), value: String(j.progress.done) });
			box.appendChild(prog);
			var ol = el('ol', { class: 'tk-stages' });
			j.stages.forEach(function (s) {
				var txt = s.stage + ': ' + s.status + (s.attempts ? ' (' + s.attempts + ')' : '');
				if (s.error) { txt += ' — ' + (s.error.code || '') + ' ' + (s.error.message || ''); }
				ol.appendChild(el('li', { class: 'tk-stage tk-stage--' + s.status, text: txt }));
			});
			box.appendChild(ol);
			if (j.status === 'running' || j.status === 'queued') {
				pollTimer = setTimeout(function () { showJob(id); }, 4000);
			}
		});
	}

	// ------------------------------------------------------------- review
	var tasks = document.getElementById('tk-tasks');
	var wrap = document.querySelector('.tk-admin[data-can-publish]');
	var canPublish = wrap && wrap.getAttribute('data-can-publish') === '1';
	function loadTasks() {
		post('tk_review_tasks', A.nonces.review).then(function (r) {
			tasks.textContent = '';
			((r.data && r.data.items) || []).forEach(function (t) {
				var label = (t.artifact_type || t.object_type) + ' · ' + (t.reason || '').slice(0, 80);
				var flags = (t.risk_flags || []).join(', ');
				tasks.appendChild(el('li', {}, [
					el('button', { type: 'button', class: 'button-link', text: label, onclick: function () {
						if (t.object_type === 'artifact') { showArtifact(t.object_id); } else { showObject(t); }
					} }),
					flags ? el('span', { class: 'tk-flags', text: ' [' + flags + ']' }) : null
				]));
			});
		});
	}
	if (tasks) {
		document.getElementById('tk-refresh-tasks').addEventListener('click', loadTasks);
		loadTasks();
	}

	function section(title, node) {
		return el('section', { class: 'tk-col' }, [el('h3', { text: title }), node]);
	}

	function pre(obj) { return el('pre', { class: 'tk-pre', text: JSON.stringify(obj, null, 2) }); }

	function showArtifact(id) {
		var box = document.getElementById('tk-artifact');
		box.textContent = '…';
		post('tk_artifact', A.nonces.review, { artifact_id: id }).then(function (r) {
			box.textContent = '';
			if (!r.ok) { box.appendChild(el('p', { class: 'tk-err', text: r.data.message })); return; }
			var d = r.data;
			box.appendChild(el('h2', { text: d.artifact.artifact_type + ' — ' + d.artifact.review_state }));
			if ((d.artifact.risk_flags || []).length) {
				box.appendChild(el('p', { class: 'tk-flags', text: 'דגלי סיכון: ' + d.artifact.risk_flags.join(', ') }));
			}
			if (d.artifact.artifact_type === 'guide') {
				box.appendChild(guideView(d));
			}
			var sources = el('ol', { class: 'tk-sources' });
			(d.sources || []).forEach(function (s) {
				sources.appendChild(el('li', {}, [
					el('strong', { text: (s.speaker || '—') + ' · עמ׳ ' + s.page + ' שורות ' + s.line_start + '–' + s.line_end + (s.judicial_level ? ' · ' + s.judicial_level : '') + (s.published ? '' : ' · לא פורסם') }),
					el('p', { text: s.text })
				]));
			});
			var cols = el('div', { class: 'tk-cols' }, [
				section('פלט הכותב', pre(d.writer_output)),
				section('פלט המאמת', pre(d.verifier_output || 'לא הופעל מאמת')),
				section('המקורות', sources)
			]);
			if (d.artifact.artifact_type === 'guide') {
				// the readable view above is what the reviewer approves; raw JSON stays one click away
				box.appendChild(el('details', { class: 'tk-raw' }, [el('summary', { text: 'נתונים גולמיים (JSON, מקורות, שערים, מודלים)' }), cols,
					section('שערים', pre(d.gate_report)), section('מודלים והנחיות', pre(d.model_runs))]));
			} else {
				box.appendChild(cols);
				box.appendChild(section('שערים', pre(d.gate_report)));
				box.appendChild(section('מודלים והנחיות', pre(d.model_runs)));
			}
			var notes = el('textarea', { rows: '3', class: 'large-text', 'aria-label': 'הערות' });
			var actions = el('p', { class: 'tk-actions' }, [
				el('button', { type: 'button', class: 'button button-primary', text: 'אישור', onclick: function () { review(id, 'approve', notes.value); } }),
				el('button', { type: 'button', class: 'button', text: 'בקשת שינויים', onclick: function () { review(id, 'request_changes', notes.value); } }),
				el('button', { type: 'button', class: 'button', text: 'דחייה', onclick: function () { review(id, 'reject', notes.value); } })
			]);
			if (canPublish) {
				actions.appendChild(el('button', { type: 'button', class: 'button', text: 'פרסום', onclick: function () { publish(id, 'publish'); } }));
				actions.appendChild(el('button', { type: 'button', class: 'button', text: 'הסרה מפרסום', onclick: function () { publish(id, 'unpublish'); } }));
			}
			box.appendChild(notes);
			box.appendChild(actions);
			box.focus();
		});
	}

	// ------------------------------------------------------------- guide review (2.3)
	var BLOCK_HE = {
		one_line: 'בשורה אחת', overview: 'סקירה', defendants: 'הנאשמים', alleged: 'מה טוען כתב האישום?', people: 'מי מעורב?',
		charges: 'האישומים', events: 'ציר הזמן של התיק', role: 'מי העד או העדה?', testimony: 'עיקרי העדות'
	};
	var GATE_HE = {
		citation: 'ציטוטים', support: 'תמיכה לשונית במקור', judicial_wording: 'ניסוח של קביעה שיפוטית', absolute_wording: 'ניסוח מוחלט',
		provenance: 'מקור המודל', allegation_framing: 'טענה שמוצגת כעובדה', verifier: 'המאמת'
	};
	var PROBLEM_HE = {
		missing_citation: 'אין ציטוט', unknown_source_unit: 'ציטוט ליחידה לא מוכרת', unpublished_source_unit: 'ציטוט ליחידה שלא פורסמה',
		low_lexical_support: 'חפיפה נמוכה בין הניסוח למקור', verifier_not_confirmed: 'המאמת לא אישר', not_verified: 'המאמת לא רץ',
		allegation_stated_as_fact: 'טענה מכתב האישום מנוסחת כעובדה'
	};
	var KIND_HE = { indictment: 'סקירת כתב האישום', case: 'מדריך לתיק', witness: 'מדריך לעד' };

	function fmtDate(it) {
		if (!it.date) { return ''; }
		var p = it.date.split('-');
		if (it.date_precision === 'year') { return p[0]; }
		if (it.date_precision === 'month') { return p[1] + '/' + p[0]; }
		return (+p[2]) + '.' + (+p[1]) + '.' + p[0];
	}

	/** path "blocks/2/items/3" → list of problems from failed gates (and the verifier's per-item verdict). */
	function problemsByPath(d) {
		var out = {};
		function add(path, text) { (out[path] = out[path] || []).push(text); }
		var gates = (d.gate_report && d.gate_report.gates) || [];
		gates.forEach(function (g) {
			if (g.passed) { return; }
			(g.details || []).forEach(function (det) {
				var label = (GATE_HE[g.gate] || g.gate) + ': ' + (PROBLEM_HE[det.problem] || det.problem || '');
				if (det.overlap !== undefined) { label += ' (חפיפה ' + Math.round(det.overlap * 100) + '%)'; }
				if (det.phrases) { label += ' — ' + [].concat(det.phrases).join(', '); }
				if (det.id) { label += ' — ' + det.id; }
				if (det.path) { add(det.path, label); }
				(det.paths || []).forEach(function (p) { add(p, label); });
			});
		});
		var v = d.verifier_output;
		((v && v.assertions) || []).forEach(function (a) {
			var bad = a.supported !== 'yes' || !a.attribution_ok || a.judicial_overstatement || a.false_premise;
			if (!bad) { return; }
			var t = 'המאמת: נתמך=' + ({ yes: 'כן', partial: 'חלקית', no: 'לא' }[a.supported] || a.supported) +
				(a.attribution_ok ? '' : ', ייחוס שגוי') + (a.judicial_overstatement ? ', הגזמה שיפוטית' : '') + (a.false_premise ? ', הנחה שגויה' : '') +
				(a.note ? ' — ' + a.note : '');
			add(a.path, t);
		});
		return out;
	}

	function gateList(d) {
		var gr = d.gate_report || {};
		var ul = el('ul', { class: 'tk-gates' });
		(gr.gates || []).forEach(function (g) {
			var n = (g.details || []).reduce(function (s, det) { return s + (det.paths ? det.paths.length : 1); }, 0);
			ul.appendChild(el('li', { class: g.passed ? 'tk-gate tk-gate--ok' : 'tk-gate tk-gate--fail tk-gate--' + (g.severity || 'error') }, [
				el('strong', { text: (g.passed ? '✓ ' : '✗ ') + (GATE_HE[g.gate] || g.gate) }),
				g.passed ? null : el('span', { text: ' — ' + n + ' בעיות' + (g.severity === 'review' ? ' (לבדיקה אנושית)' : ' (חוסם)') })
			]));
		});
		var wrap = el('div', { class: 'tk-gatebox' }, [
			el('p', { text: 'מצב: ' + (gr.state || '—') + ((gr.risk_flags || []).length ? ' · דגלים: ' + gr.risk_flags.join(', ') : '') }), ul
		]);
		var v = d.verifier_output;
		if (v && v.verdict) { wrap.appendChild(el('p', { text: 'הכרעת המאמת: ' + v.verdict })); }
		((v && v.omitted_counterevidence) || []).forEach(function (o) {
			wrap.appendChild(el('p', { class: 'tk-flags', text: 'ראיה נגדית שהושמטה: ' + (o.note || '') + ' [' + o.source_unit_ids.join(', ') + ']' }));
		});
		return wrap;
	}

	function guideView(d) {
		var g = d.writer_output || {};
		var cits = {};
		(g.citations || []).forEach(function (c) { cits[c.source_unit_id] = c; });
		var texts = {};
		(d.sources || []).forEach(function (s) { texts[s.source_unit_id] = s; });
		var probs = problemsByPath(d);
		var flagged = Object.keys(probs).length;
		var root = el('div', { class: 'tk-guide-review' }, [
			el('p', { class: 'tk-muted', text: (KIND_HE[g.kind] || g.kind || '') + (g.key ? ' · ' + g.key : '') }),
			el('h2', { text: (g.title || '') + (g.subtitle ? ' — ' + g.subtitle : '') }),
			el('p', { class: flagged ? 'tk-flags' : 'tk-ok', text: flagged ? flagged + ' פריטים מסומנים לבדיקה (מודגשים למטה).' : 'כל הפריטים עברו את השערים ואת המאמת.' }),
			section('שערים', gateList(d))
		]);
		(g.blocks || []).forEach(function (b, bi) {
			var ol = el('ol', { class: 'tk-gitems' });
			(b.items || []).forEach(function (it, ii) {
				var path = 'blocks/' + bi + '/items/' + ii;
				var p = probs[path] || [];
				var head = [it.label ? el('strong', { text: it.label + ': ' }) : null, fmtDate(it) ? el('span', { class: 'tk-gdate', text: fmtDate(it) + ' · ' }) : null, it.text || ''];
				var srcs = el('ul', { class: 'tk-gsrc' });
				(it.citation_ids || []).forEach(function (id) {
					var c = cits[id], s = texts[id];
					var loc = c ? 'עמ׳ ' + c.page + ' שורות ' + c.line_start + '–' + c.line_end : (s ? 'עמ׳ ' + s.page + ' שורות ' + s.line_start + '–' + s.line_end : id);
					var who = (s && s.speaker) || (c && c.speaker) || '';
					srcs.appendChild(el('li', {}, [
						el('span', { class: 'tk-gloc', text: loc + (who ? ' · ' + who : '') + (s && !s.published ? ' · לא פורסם' : '') }),
						s ? el('q', { text: (s.text || '').length > 500 ? s.text.slice(0, 500) + '…' : (s.text || '') }) : el('span', { class: 'tk-err', text: ' (טקסט המקור לא הוחזר)' })
					]));
				});
				if (!(it.citation_ids || []).length) { srcs.appendChild(el('li', { class: 'tk-err', text: 'ללא ציטוט' })); }
				ol.appendChild(el('li', { class: 'tk-gitem' + (p.length ? ' tk-gitem--flag' : '') }, [
					el('p', { class: 'tk-gtext' }, head),
					p.length ? el('ul', { class: 'tk-gprob' }, p.map(function (t) { return el('li', { text: t }); })) : null,
					el('details', p.length ? { open: 'open' } : {}, [el('summary', { text: 'מקורות (' + (it.citation_ids || []).length + ')' }), srcs])
				]));
			});
			root.appendChild(el('section', { class: 'tk-gblock' }, [el('h3', { text: BLOCK_HE[b.block] || b.block }), ol]));
		});
		return root;
	}

	function showObject(t) {
		var box = document.getElementById('tk-artifact');
		box.textContent = '';
		box.appendChild(el('h2', { text: t.object_type + ' ' + t.object_id }));
		box.appendChild(el('p', { text: t.reason || '' }));
		box.appendChild(el('p', { class: 'tk-actions' }, ['approve', 'request_changes', 'reject'].map(function (d) {
			return el('button', { type: 'button', class: 'button', text: { approve: 'אישור', request_changes: 'בקשת שינויים', reject: 'דחייה' }[d], onclick: function () {
				post('tk_object_review', A.nonces.review, { object_type: t.object_type, object_id: t.object_id, decision: d }).then(function (r) {
					box.appendChild(el('p', { class: r.ok ? 'tk-ok' : 'tk-err', text: r.ok ? 'נשמר' : r.data.message }));
					loadTasks();
				});
			} });
		})));
		box.focus();
	}

	function review(id, decision, notes) {
		if (!window.confirm(A.i18n.confirm)) { return; }
		post('tk_review_action', A.nonces.review, { artifact_id: id, decision: decision, notes: notes }).then(function (r) {
			window.alert(r.ok ? 'נשמר: ' + r.data.review_state : 'שגיאה: ' + r.data.message);
			loadTasks();
			showArtifact(id);
		});
	}

	function publish(id, what) {
		if (!window.confirm(A.i18n.confirm)) { return; }
		var data = { artifact_id: id, what: what };
		if (what === 'publish') { data.include_sources = window.confirm('לפרסם גם את המקורות המצוטטים שטרם פורסמו?') ? '1' : ''; }
		if (what === 'unpublish') { data.reason = window.prompt('סיבת ההסרה') || ''; }
		post('tk_publish_action', A.nonces.publish, data).then(function (r) {
			window.alert(r.ok ? 'בוצע' : 'שגיאה: ' + (r.data.code || '') + ' ' + r.data.message);
			showArtifact(id);
		});
	}

	// ------------------------------------------------------------- local copy (2.5)
	var store = document.getElementById('tk-store');
	if (store && A.nonces.store) {
		var msg = document.getElementById('tk-store-msg');
		var timer = null;
		var paint = function (d) {
			if (!d) { return; }
			['count', 'size', 'stale', 'failed', 'changes', 'next_changes', 'refresh', 'full'].forEach(function (k) {
				var node = store.querySelector('[data-tk="' + k + '"]');
				if (node && typeof d[k] !== 'undefined') { node.textContent = d[k]; }
			});
			var bar = store.querySelector('[data-tk-progress]');
			if (bar) { bar.value = d.full_pct || 0; bar.hidden = !d.full_running; }
			var kinds = document.getElementById('tk-store-kinds');
			if (kinds && d.kinds) {
				kinds.textContent = '';
				d.kinds.forEach(function (k) {
					kinds.appendChild(el('tr', {}, [el('td', { text: k.label }), el('td', { text: k.count }), el('td', { text: k.size })]));
				});
			}
			if (d.message) { msg.textContent = d.message; }
			schedule(d);
		};
		var poll = function () {
			timer = null;
			post('tk_store_status', A.nonces.store, { step: '1' }).then(function (r) { paint(r.data); });
		};
		var schedule = function (d) {
			if (timer || !d) { return; }
			if (d.busy) { timer = window.setTimeout(poll, 4000); }
		};
		store.querySelectorAll('[data-tk-store]').forEach(function (b) {
			b.addEventListener('click', function () {
				var c = b.getAttribute('data-tk-confirm');
				if (c && !window.confirm(c)) { return; }
				b.disabled = true;
				msg.textContent = '…';
				post(b.getAttribute('data-tk-store'), A.nonces.store).then(function (r) {
					b.disabled = false;
					if (!r.ok) { msg.textContent = 'שגיאה: ' + ((r.data && r.data.message) || ''); return; }
					paint(r.data);
				}, function () { b.disabled = false; msg.textContent = 'שגיאה'; });
			});
		});
		post('tk_store_status', A.nonces.store).then(function (r) { schedule(r.data); });
	}
}());
