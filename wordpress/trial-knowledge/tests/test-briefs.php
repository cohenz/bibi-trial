<?php
// 2.4 document briefs: lists, document page, witness appearances, timeline hearing days, webhooks.
$bsu  = 'su_' . str_repeat( '6', 26 );
$bsv  = 'sv_' . str_repeat( '7', 26 );
$bsv2 = 'sv_' . str_repeat( '8', 26 );
$bsv3 = 'sv_' . str_repeat( '9', 26 );
$bcit = array( 'source_unit_id' => $bsu, 'source_version_id' => $bsv, 'page' => 2, 'line_start' => 1, 'line_end' => 9, 'speaker' => 'בית המשפט', 'quote' => null, 'court_record_status' => 'filed', 'permalink' => 'https://api.test/x' );
$bws  = array(
	array( 'slug' => 'w_aaaaaaaaaa', 'name' => 'אילנית פילבר', 'label' => null, 'hearing_count' => 0, 'appearance_count' => 2, 'side' => 'defense', 'first_date' => '2026-04-20', 'last_date' => '2026-04-21', 'cases' => array(), 'has_guide' => false ),
	array( 'slug' => 'w_72da315abb', 'name' => 'בנימין נתניהו', 'label' => 'נאשם 1', 'hearing_count' => 3, 'appearance_count' => 1, 'side' => null, 'first_date' => '2024-12-10', 'last_date' => '2026-04-22', 'cases' => array(), 'has_guide' => false ),
);

// --- document list with briefs, procedural badge and the hidden toggle
$list = array(
	'items' => array(
		array( 'source_version_id' => $bsv, 'title' => 'החלטה: שניתנה ע"י <b>x</b>', 'display_title' => 'דחיית בקשה <i>לעיון</i> חוזר', 'significance' => 'substantive', 'source_type' => 'decision', 'document_date' => '2026-07-26', 'page_count' => 2,
			'brief' => array( 'title' => 'דחיית בקשה לעיון חוזר', 'summary' => 'בית המשפט דחה את <script>הבקשה</script>.', 'significance' => 'substantive', 'significance_reason' => null, 'hearing_days' => array() ) ),
		array( 'source_version_id' => $bsv2, 'title' => 'החלטה: על בקשה', 'display_title' => 'החלטה: על בקשה', 'significance' => null, 'source_type' => 'decision', 'document_date' => '2026-07-20', 'page_count' => 1, 'brief' => null ),
	),
);
$dl = TK_Render::documents( $list, array( 'mode' => 'substantive', 'hidden_count' => 4, 'show_url' => '/decisions/?tk_all=1', 'hide_url' => '/decisions/' ) );
TK_T::ok( false !== strpos( $dl, '>דחיית בקשה &lt;i&gt;לעיון&lt;/i&gt; חוזר</a>' ) && false === strpos( $dl, 'שניתנה ע' ), 'docs list: display_title is the link text, escaped; archive title not shown' );
TK_T::ok( false !== strpos( $dl, 'class="tk-documents__summary">בית המשפט דחה את &lt;script&gt;' ), 'docs list: one-line brief summary under the title, escaped' );
TK_T::ok( false !== strpos( $dl, '>החלטה: על בקשה</a>' ) && 1 === substr_count( $dl, 'tk-documents__summary' ), 'docs list: document without a brief keeps its title, no summary' );
TK_T::ok( false !== strpos( $dl, 'הצגת גם מסמכים פרוצדורליים (4)' ) && false !== strpos( $dl, 'href="/decisions/?tk_all=1"' ), 'docs list: toggle link shows the hidden count, works without JS' );
TK_T::ok( false !== strpos( $dl, '26.7.2026' ) && false !== strpos( $dl, '2 עמודים' ) && false !== strpos( $dl, '/trial/document/' . $bsv . '/' ), 'docs list: date, pages and document link' );
TK_T::ok( false === strpos( $dl, 'tk-badge--procedural' ), 'docs list: no procedural badge on substantive items' );
$list['items'][] = array( 'source_version_id' => $bsv3, 'title' => 'החלטה', 'display_title' => 'תיקון פרוטוקול', 'significance' => 'procedural', 'source_type' => 'decision', 'document_date' => '2026-07-01', 'page_count' => 1,
	'brief' => array( 'title' => 'תיקון פרוטוקול', 'summary' => 'תמלול מחדש.', 'significance' => 'procedural', 'significance_reason' => 'עניין טכני', 'hearing_days' => array() ) );
$da = TK_Render::documents( $list, array( 'mode' => 'with_procedural', 'show_url' => '/decisions/?tk_all=1', 'hide_url' => '/decisions/' ) );
TK_T::ok( 1 === substr_count( $da, 'tk-badge--procedural' ) && false !== strpos( $da, '>פרוצדורלי<' ) && false !== strpos( $da, 'tk-documents__item--procedural' ), 'docs list: procedural badge when all documents are shown' );
TK_T::ok( false !== strpos( $da, 'הסתרת מסמכים פרוצדורליים' ) && false !== strpos( $da, 'href="/decisions/"' ) && false === strpos( $da, 'הצגת גם' ), 'docs list: link back to the substantive view' );
$d0 = TK_Render::documents( $list, array( 'mode' => 'substantive', 'hidden_count' => 0, 'show_url' => '/x/?tk_all=1' ) );
TK_T::ok( false === strpos( $d0, 'tk-doctoggle' ), 'docs list: no toggle when nothing is hidden' );
$dn = TK_Render::documents( $list, array( 'mode' => 'substantive', 'hidden_count' => null, 'show_url' => '/x/?tk_all=1' ) );
TK_T::ok( false !== strpos( $dn, '>הצגת גם מסמכים פרוצדורליים</a>' ), 'docs list: toggle without a number when the count is unknown' );
TK_T::ok( false === strpos( TK_Render::documents( $list, array( 'mode' => 'all' ) ), 'tk-doctoggle' ), 'docs list: procedural="show" has no toggle' );
TK_T::ok( false !== strpos( TK_Render::documents( array( 'items' => array() ), array( 'mode' => 'substantive', 'hidden_count' => 3, 'show_url' => '/x/?tk_all=1' ) ), 'אין מסמכים מהותיים להצגה' ), 'docs list: only procedural documents → message + toggle' );

// --- document page with a brief and a hearing day
$doc = array(
	'source_version_id' => $bsv, 'title' => 'הודעה: בדבר עדים', 'source_type' => 'notice',
	'brief'             => array(
		'title'              => 'עדות אילנית פילבר <u>ביום</u> 20.4.2026',
		'summary'            => 'בית המשפט הודיע…',
		'significance'       => 'substantive',
		'significance_reason' => null,
		'summary_sentences'  => array( array( 'text' => 'בית המשפט הודיע על <b>העדה</b>.', 'citation_ids' => array( $bsu ) ) ),
		'title_citation_ids' => array( $bsu ),
		'citations'          => array( $bcit ),
		'hearing_days'       => array( array( 'hearing_date' => '2026-04-20', 'next_hearing_date' => '2026-04-26', 'citation_ids' => array( $bsu ),
			'witnesses' => array( array( 'name' => 'אילנית פילבר', 'side' => 'defense', 'description' => 'מנכ"לית לשעבר' ), array( 'name' => 'נאשם 1 — בנימין נתניהו', 'side' => 'unknown', 'description' => '' ), array( 'name' => 'עד לא מוכר', 'side' => 'prosecution', 'description' => '' ) ) ) ),
	),
);
$bh = TK_Render_Guides::document_brief( $doc, TK_Guides::slug_map( $bws ) );
TK_T::ok( false !== strpos( $bh, '<h1 class="tk-brief__title">עדות אילנית פילבר &lt;u&gt;ביום&lt;/u&gt; 20.4.2026</h1>' ), 'doc page: brief title as H1, escaped' );
TK_T::ok( false !== strpos( $bh, 'שם במסמך:' ) && false !== strpos( $bh, 'הודעה: בדבר עדים' ), 'doc page: archive title kept as a subtitle' );
TK_T::ok( false !== strpos( $bh, 'בית המשפט הודיע על &lt;b&gt;העדה&lt;/b&gt;.' ) && false !== strpos( $bh, '>עמ׳ 2<' ), 'doc page: summary sentences with citation chips' );
TK_T::ok( false === strpos( $bh, 'מסמך פרוצדורלי' ), 'doc page: no significance note for substantive documents' );
TK_T::ok( false !== strpos( $bh, 'class="tk-hday"' ) && false !== strpos( $bh, '20.4.2026' ) && false !== strpos( $bh, 'הדיון הבא' ) && false !== strpos( $bh, '26.4.2026' ), 'doc page: hearing day box with date and next hearing' );
TK_T::ok( false !== strpos( $bh, 'href="https://site.test/trial/witness/w_aaaaaaaaaa/"' ) && false !== strpos( $bh, 'עד/ת הגנה' ) && false !== strpos( $bh, 'מנכ&quot;לית לשעבר' ), 'doc page: witness linked by slug, side and description' );
TK_T::ok( false !== strpos( $bh, '/trial/witness/w_72da315abb/' ) && false !== strpos( $bh, 'tk-badge--label">נאשם 1<' ), 'doc page: defendant label stripped for the slug' );
TK_T::ok( false !== strpos( $bh, 'עד לא מוכר' ) && false !== strpos( $bh, 'עד/ת תביעה' ) && 2 === substr_count( $bh, '/trial/witness/' ), 'doc page: unknown witness shown without a link; unknown side has no label' );
$doc['brief']['significance']        = 'procedural';
$doc['brief']['significance_reason'] = 'ארכה <i>להגשה</i>';
$doc['brief']['hearing_days']        = array();
$bp = TK_Render_Guides::document_brief( $doc, array() );
TK_T::ok( false !== strpos( $bp, 'מסמך פרוצדורלי: ארכה &lt;i&gt;להגשה' ) && false === strpos( $bp, 'tk-hday' ), 'doc page: procedural note with reason; no box without hearing days' );
TK_T::eq( '', TK_Render_Guides::document_brief( array( 'title' => 'x', 'brief' => null ) ), 'doc page: without a brief nothing is added (page looks as before)' );
TK_T::eq( 'החלטה', TK_Render::display_title( array( 'title' => 'החלטה', 'brief' => null ) ), 'display_title falls back to the archive title' );

// --- witness with appearances only
$wa = array(
	'slug' => 'w_aaaaaaaaaa', 'name' => 'אילנית פילבר', 'label' => null, 'artifact_id' => null, 'blocks' => array(), 'cases' => array(), 'side' => 'defense', 'hearings' => array(), 'notable_exchanges' => array(), 'citations' => array(),
	'appearances' => array(
		array( 'date' => '2026-04-21', 'side' => 'defense', 'description' => 'חקירה <b>נגדית</b>', 'source_version_id' => $bsv, 'document_title' => 'עדות אילנית פילבר', 'has_transcript' => false ),
		array( 'date' => '2026-04-20', 'side' => 'defense', 'description' => 'חקירה ראשית', 'source_version_id' => $bsv2, 'document_title' => 'הודעה', 'has_transcript' => true ),
	),
);
$wh = TK_Render_Guides::witness_page( $wa, $bws );
TK_T::ok( false !== strpos( $wh, 'ימי עדות לפי הודעות בית המשפט' ) && false !== strpos( $wh, '/trial/document/' . $bsv . '/' ) && false !== strpos( $wh, 'חקירה &lt;b&gt;נגדית' ), 'witness: appearances with description and the notice link' );
TK_T::ok( strpos( $wh, '20.4.2026' ) < strpos( $wh, '21.4.2026' ), 'witness: appearances in date order' );
TK_T::ok( 1 === substr_count( $wh, 'יש תמלול' ) && false !== strpos( $wh, 'עד/ת הגנה' ), 'witness: transcript mark and side label' );
TK_T::ok( false === strpos( $wh, 'הדיונים שבהם העיד/ה' ) && false === strpos( $wh, 'בינתיים מוצגים כאן עיקרי הדיונים' ) && false === strpos( $wh, 'ב־0 דיונים' ), 'witness: no hearings section or hearing-based note without hearings' );
TK_T::ok( false !== strpos( $wh, 'עדיין לא פורסם תמלול של העדות' ) && false !== strpos( $wh, 'יום עדות אחד לפי הודעת בית המשפט' ), 'witness: appearance-only note and header count' );
$wl = TK_Render_Guides::witnesses_list( $bws );
TK_T::ok( false !== strpos( $wl, 'tk-badge--defense' ) && false !== strpos( $wl, '>הגנה<' ), 'witness list: side badge' );
TK_T::ok( false !== strpos( $wl, '3 דיונים מתומללים · יום עדות נוסף אחד' ) && false !== strpos( $wl, '2 ימי עדות לפי הודעות בית המשפט' ), 'witness list: transcribed hearings and notice-only days' );

// --- timeline: significance, hearing_day kind, procedural hidden in the fallback
$btl = array(
	'events'    => array(
		array( 'id' => 'hd_' . $bsv . '_2026-04-20', 'track' => 'trial', 'date' => '2026-04-20', 'date_precision' => 'day', 'title' => 'יום דיון: עדות אילנית פילבר (עד/ת הגנה)', 'text' => 'לפי הודעת בית המשפט. הדיון הבא נקבע ל־2026-04-26', 'case_keys' => array(), 'kind' => 'hearing_day', 'significance' => 'substantive', 'link' => array( 'type' => 'document', 'id' => $bsv ), 'citation_ids' => array() ),
		array( 'id' => $bsv3, 'track' => 'trial', 'date' => '2026-07-01', 'date_precision' => 'day', 'title' => 'תיקון פרוטוקול', 'text' => 'תמלול מחדש.', 'case_keys' => array(), 'kind' => 'decision', 'significance' => 'procedural', 'link' => array( 'type' => 'document', 'id' => $bsv3 ), 'citation_ids' => array() ),
		array( 'id' => 'hr_' . str_repeat( 'c', 26 ), 'track' => 'trial', 'date' => '2026-03-01', 'date_precision' => 'day', 'title' => 'דיון', 'text' => null, 'case_keys' => array(), 'kind' => 'hearing', 'significance' => 'substantive', 'notice_witnesses' => array( 'דובי שרצר', 'דובי שרצר' ), 'link' => array( 'type' => 'hearing', 'id' => 'hr_' . str_repeat( 'c', 26 ) ), 'citation_ids' => array() ),
	),
	'citations' => array(),
);
$bth = TK_Render_Guides::timeline( $btl, '', array( 'show_url' => '/trial/timeline/?tk_all=1' ) );
preg_match( '#<script type="application/json" class="tk-tl__data">(.*?)</script>#s', $bth, $bm );
$bpl = isset( $bm[1] ) ? json_decode( $bm[1], true ) : array();
TK_T::eq( 'hearing_day', $bpl['events'][0]['kind'] ?? '', 'timeline JSON: hearing_day kind kept' );
TK_T::eq( 'יום דיון (לפי הודעה)', $bpl['kinds']['hearing_day'] ?? '', 'timeline JSON: hearing_day label' );
TK_T::eq( array( 'substantive', 'procedural', 'substantive' ), array_column( $bpl['events'] ?? array(), 'sig' ), 'timeline JSON: significance per event' );
TK_T::eq( 'https://site.test/trial/document/' . $bsv . '/', $bpl['events'][0]['url'] ?? '', 'timeline JSON: hearing day links the notice document' );
TK_T::eq( 'תמלול מחדש.', $bpl['events'][1]['text'] ?? '', 'timeline JSON: document event carries the brief summary' );
TK_T::eq( array( 'דובי שרצר' ), $bpl['events'][2]['nw'] ?? null, 'timeline JSON: notice witnesses of a transcribed hearing' );
TK_T::ok( false !== strpos( $bth, 'data-all="0"' ) && false === strpos( $bth, '>תיקון פרוטוקול</a>' ) && false !== strpos( $bth, 'הצגת גם מסמכים פרוצדורליים (1)' ), 'timeline fallback: procedural hidden by default, no-JS toggle link' );
TK_T::ok( false !== strpos( $bth, 'tk-tl__fitem--notice' ) && false !== strpos( $bth, 'tk-badge--notice' ), 'timeline fallback: hearing day marked as known from a notice' );
$btha = TK_Render_Guides::timeline( $btl, '', array( 'all' => true, 'hide_url' => '/trial/timeline/' ) );
TK_T::ok( false !== strpos( $btha, 'data-all="1"' ) && false !== strpos( $btha, '>תיקון פרוטוקול</a>' ) && false !== strpos( $btha, 'tk-badge--procedural' ), 'timeline fallback: ?tk_all=1 shows procedural documents with a badge' );

// --- start page: latest hearing day newer than the latest transcribed hearing
$lday = TK_Render_Guides::latest_hearing_day( $btl, '2026-03-01' );
TK_T::eq( '2026-04-20', $lday['date'] ?? '', 'start: latest hearing day after the latest transcript' );
TK_T::eq( null, TK_Render_Guides::latest_hearing_day( $btl, '2026-05-01' ), 'start: no hearing day when the transcript is newer' );
$sg = array( 'cases' => array(), 'indictment' => null, 'witnesses' => $bws, 'latest_hearing' => null, 'counts' => array( 'hearings' => 1, 'documents' => array( 'decision' => 3 ) ) );
$sh = TK_Render_Guides::start( $sg, array( 'latest_day' => $lday, 'latest_docs' => $list['items'] ) );
TK_T::ok( false !== strpos( $sh, 'יום הדיון האחרון שידוע עליו:' ) && false !== strpos( $sh, '>עדות אילנית פילבר (עד/ת הגנה)</a>' ) && false !== strpos( $sh, '/trial/document/' . $bsv . '/' ), 'start: latest hearing day line links the notice' );
TK_T::ok( false !== strpos( $sh, 'האחרונים:' ) && false !== strpos( $sh, 'דחיית בקשה &lt;i&gt;לעיון' ), 'start: documents entry lists the newest documents by brief title' );
TK_T::ok( false === strpos( TK_Render_Guides::start( $sg ), 'יום הדיון האחרון' ), 'start: no hearing-day line without timeline data' );

// --- webhooks: a published/unpublished document brief purges lists, the document page, timeline and guides
$bt = TK_Webhooks::tags_for( array( 'event' => 'artifact.published', 'payload' => array( 'artifact_type' => 'summary', 'object_type' => 'document', 'object_id' => $bsv ) ) );
TK_T::ok( in_array( 'document:' . $bsv, $bt, true ) && in_array( 'documents', $bt, true ) && in_array( 'timeline', $bt, true ) && in_array( 'guide', $bt, true ) && in_array( 'lists', $bt, true ), 'webhook: document brief purges document page, lists, timeline, guides' );
$bt = TK_Webhooks::tags_for( array( 'event' => 'artifact.unpublished', 'payload' => array( 'artifact_type' => 'summary', 'object_type' => 'document', 'object_id' => $bsv ) ) );
TK_T::ok( in_array( 'document:' . $bsv, $bt, true ) && in_array( 'timeline', $bt, true ), 'webhook: unpublished brief purges too' );
tk_test_reset_store();
TK_Cache::remember( TK_Paths::document( $bsv, 1 ), function () { return array( 'x' => 1 ); } );
TK_Cache::purge( TK_Webhooks::tags_for( array( 'event' => 'artifact.published', 'payload' => array( 'artifact_type' => 'summary', 'object_type' => 'document', 'object_id' => $bsv ) ) ) );
TK_Sync::run_refresh();
TK_T::eq( array( TK_Paths::document( $bsv, 1 ) ), tk_api()->calls, 'webhook: document page refetched after its brief is published' );
