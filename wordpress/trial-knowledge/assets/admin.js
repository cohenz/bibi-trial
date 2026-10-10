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
			var log = document.getElementById('tk-upload-log');
			Array.prototype.reduce.call(files, function (p, file) {
				return p.then(function () { return uploadOne(file, date, crs, log); });
			}, Promise.resolve()).then(loadJobs);
		});
	}

	function uploadOne(file, date, crs, log) {
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
			return post('tk_create_job', A.nonces.upload, { upload_id: up.upload_id, title: file.name.replace(/\.pdf$/i, ''), hearing_date: date, crs: crs });
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
			box.appendChild(cols);
			box.appendChild(section('שערים', pre(d.gate_report)));
			box.appendChild(section('מודלים והנחיות', pre(d.model_runs)));
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
}());
