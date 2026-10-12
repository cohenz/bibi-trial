<?php
// 2.3 reader entry points: start page, case, witness, timeline, glossary, hearing tabs.
$su1 = 'su_' . str_repeat( '1', 26 );
$su2 = 'su_' . str_repeat( '2', 26 );
$sv  = 'sv_' . str_repeat( '3', 26 );
$hr  = 'hr_' . str_repeat( '4', 26 );
$cit = function ( $id, $page ) use ( $sv ) {
	return array( 'source_unit_id' => $id, 'source_version_id' => $sv, 'page' => $page, 'line_start' => 3, 'line_end' => 9, 'speaker' => null, 'quote' => null, 'court_record_status' => 'filed', 'permalink' => 'https://api.test/x' );
};
$witnesses = array(
	array( 'slug' => 'w_346fdfeda0', 'name' => 'אילן ישועה', 'label' => null, 'hearing_count' => 3, 'first_date' => '2021-05-10', 'last_date' => '2021-06-14', 'cases' => array( '4000' ), 'has_guide' => false ),
	array( 'slug' => 'w_72da315abb', 'name' => 'בנימין נתניהו', 'label' => 'נאשם 1', 'hearing_count' => 1, 'first_date' => '2025-09-16', 'last_date' => '2025-09-16', 'cases' => array(), 'has_guide' => false ),
);

// --- date precision
TK_T::eq( '12.3.2015', TK_Render_Guides::fmt_date( '2015-03-12', 'day' ), 'day precision → d.m.yyyy' );
TK_T::eq( 'מרץ 2015', TK_Render_Guides::fmt_date( '2015-03-01', 'month' ), 'month precision → Hebrew month + year' );
TK_T::eq( '2015', TK_Render_Guides::fmt_date( '2015-01-01', 'year' ), 'year precision → year' );
TK_T::eq( '⁦10.5.2021–14.6.2021⁩', TK_Render_Guides::date_range( '2021-05-10', '2021-06-14' ), 'date range' );
TK_T::ok( false !== strpos( TK_Render_Guides::time_tag( '2015-03-01', 'month' ), 'datetime="2015-03"' ), 'time tag datetime follows precision' );

// --- witness name helpers
TK_T::eq( array( 'בנימין נתניהו', 'נאשם 1' ), TK_Guides::split_label( 'נאשם 1 — בנימין נתניהו' ), 'defendant label stripped from hearing witness' );
$slugs = TK_Guides::slug_map( $witnesses );
TK_T::eq( 'w_72da315abb', TK_Guides::slug_for( 'נאשם 1 — בנימין נתניהו', $slugs ), 'witness slug from raw hearing name' );
TK_T::eq( '', TK_Guides::slug_for( 'מישהו אחר', $slugs ), 'unknown witness → no slug' );
$wv     = array( array( 'slug' => 'w_d1dc28ccdd', 'name' => 'אבירם אלעד', 'variants' => array( 'מר אבירם אלעד', 'מר אלעד אבירם', 'אבירם אלעד' ) ) );
$wslugs = TK_Guides::slug_map( $wv );
TK_T::eq( 'w_d1dc28ccdd', TK_Guides::slug_for( 'מר אלעד אבירם', $wslugs ), 'a printed variant maps to the one person' );
TK_T::ok( false !== strpos( TK_Render_Guides::witness_link( 'מר אלעד אבירם', $wslugs ), '>אבירם אלעד<' ), 'witness link shows the person\'s one spelling' );
$slugs = TK_Guides::slug_map( $witnesses );

// --- start page without published guides
$g0 = array(
	'indictment'     => null,
	'cases'          => array(),
	'witnesses'      => $witnesses,
	'latest_hearing' => array( 'id' => $hr, 'hearing_date' => '2026-05-25', 'witnesses' => array( 'נאשם 1 — בנימין נתניהו' ), 'summary_sentences' => array( array( 'text' => 'משפט <b>ראשון</b>', 'citation_ids' => array( $su1 ) ) ), 'citations' => array( $cit( $su1, 7 ) ) ),
	'counts'         => array( 'hearings' => 17, 'documents' => array( 'decision' => 3, 'motion' => 4 ) ),
);
$s0 = TK_Render_Guides::start( $g0, array( 'ask_html' => '<div class="tk-ask">ASK</div>' ) );
TK_T::eq( 3, substr_count( $s0, 'המדריך לתיק בהכנה' ), 'start: three pending case cards without guides' );
TK_T::ok( strpos( $s0, 'תיק 4000' ) < strpos( $s0, 'תיק 2000' ) && strpos( $s0, 'תיק 2000' ) < strpos( $s0, 'תיק 1000' ), 'start: case order 4000, 2000, 1000' );
TK_T::ok( false === strpos( $s0, '/trial/case/' ), 'start: no links to unpublished case pages' );
TK_T::ok( false === strpos( $s0, 'כתב האישום בקצרה' ), 'start: indictment section hidden when null' );
TK_T::ok( false !== strpos( $s0, TK_Render_Guides::NEUTRAL ) && false !== strpos( $s0, '/trial/glossary/#term-presumption-of-innocence' ), 'start: neutrality line links the glossary term' );
TK_T::ok( false !== strpos( $s0, '/trial/hearing/' . $hr . '/' ) && false !== strpos( $s0, '25.5.2026' ) && false !== strpos( $s0, 'עמ׳ 7' ) && false !== strpos( $s0, 'tk-srcs' ), 'start: latest hearing with date and sources pill' );
TK_T::ok( false === strpos( $s0, '<b>' ), 'start: summary text escaped' );
TK_T::ok( false !== strpos( $s0, '/trial/witness/w_72da315abb/' ) && false !== strpos( $s0, 'נאשם 1' ), 'start: witnesses link to witness pages, label shown' );
TK_T::ok( false !== strpos( $s0, '>17<' ) && false !== strpos( $s0, 'https://site.test/decisions/' ), 'start: counts link to document pages' );
TK_T::ok( false !== strpos( $s0, '/trial/timeline/' ) && false !== strpos( $s0, '/trial/witnesses/' ) && false !== strpos( $s0, 'id="tk-ask"' ) && false !== strpos( $s0, 'ASK' ), 'start: entry links and embedded Ask' );
TK_T::ok( false !== strpos( $s0, 'tk-glossable' ), 'start: texts marked for glossary tooltips' );

// --- start page with guides
$g1               = $g0;
$g1['cases']      = array( array( 'key' => '4000', 'title' => 'תיק 4000', 'subtitle' => 'פרשת <i>בזק</i>', 'one_line' => array( 'text' => 'לפי כתב האישום…', 'citation_ids' => array( $su2 ) ), 'defendants' => array( 'נאשם א' ), 'charges' => array(), 'event_count' => 2 ) );
$g1['indictment'] = array(
	'artifact_id' => 'a', 'title' => 'כתב האישום', 'document' => array( 'source_version_id' => $sv, 'title' => 'כתב אישום', 'document_date' => '2019-12-01', 'page_count' => 77 ),
	'blocks'      => array( array( 'block' => 'overview', 'items' => array( array( 'text' => 'סקירה', 'citation_ids' => array( $su1 ) ) ) ), array( 'block' => 'defendants', 'items' => array( array( 'label' => 'נאשם א', 'text' => 'תיאור', 'citation_ids' => array( $su1 ) ) ) ) ),
	'citations'   => array( $cit( $su1, 6 ) ),
);
$s1 = TK_Render_Guides::start( $g1 );
TK_T::ok( false !== strpos( $s1, '/trial/case/4000/' ) && 2 === substr_count( $s1, 'המדריך לתיק בהכנה' ), 'start: published case card links, others pending' );
TK_T::ok( false === strpos( $s1, '<i>' ) && false !== strpos( $s1, 'פרשת &lt;i&gt;בזק' ), 'start: subtitle escaped' );
TK_T::ok( false !== strpos( $s1, 'כתב האישום בקצרה' ) && false !== strpos( $s1, '/trial/document/' . $sv . '/' ) && false !== strpos( $s1, 'עמ׳ 6' ) && false !== strpos( $s1, 'tk-srcs' ), 'start: indictment overview cited, links the document' );
TK_T::ok( false !== strpos( $s1, 'href="https://site.test/trial/source/' . $su2 . '/"' ), 'start: uncited-map chip falls back to the source page' );

// --- case page
$case = array(
	'key'       => '4000', 'title' => 'תיק 4000', 'subtitle' => 'פרשת בזק–וואלה',
	'blocks'    => array(
		array( 'block' => 'one_line', 'items' => array( array( 'text' => 'שורה', 'citation_ids' => array( $su1 ) ) ) ),
		array( 'block' => 'alleged', 'items' => array( array( 'text' => 'נטען <script>x</script>', 'citation_ids' => array( $su1, $su2 ) ) ) ),
		array( 'block' => 'charges', 'items' => array( array( 'label' => 'בנימין נתניהו', 'text' => 'שוחד; מרמה והפרת אמונים', 'citation_ids' => array( $su1 ) ) ) ),
		array( 'block' => 'people', 'items' => array( array( 'label' => 'אילן ישועה', 'text' => 'מנכ"ל', 'citation_ids' => array( $su1 ), 'witness_slug' => 'w_346fdfeda0' ), array( 'label' => 'אחר', 'text' => 'תפקיד', 'citation_ids' => array() ) ) ),
		array( 'block' => 'events', 'items' => array(
			array( 'label' => 'ב', 'text' => 'אירוע', 'date' => '2015-03-12', 'date_precision' => 'day', 'citation_ids' => array( $su1 ) ),
			array( 'label' => 'א', 'text' => 'אירוע', 'date' => '2014-01-01', 'date_precision' => 'year', 'citation_ids' => array() ),
			array( 'label' => 'ג', 'text' => 'אירוע', 'date' => '2015-06-01', 'date_precision' => 'month', 'citation_ids' => array() ),
		) ),
	),
	'citations' => array( $cit( $su1, 6 ), $cit( $su2, 6 ) ),
	'hearings'  => array( array( 'id' => $hr, 'hearing_date' => '2021-05-10', 'witnesses' => array( 'אילן ישועה' ) ) ),
	'document'  => array( 'source_version_id' => $sv, 'title' => 'כתב אישום', 'document_date' => '2019-12-01', 'page_count' => 77 ),
);
$cp = TK_Render_Guides::case_page( $case, array( 'slugs' => $slugs ) );
TK_T::ok( false !== strpos( $cp, 'מה שמופיע כאן הוא תיאור הטענות בכתב האישום, לא קביעות של בית המשפט' ), 'case: allegation banner' );
TK_T::ok( false === strpos( $cp, '<script>' ), 'case: alleged text escaped' );
$tk_pill = TK_Render_Guides::chips( array( $su1, $su2, $su1 ), TK_Render_Guides::cit_map( $case['citations'] ) );
TK_T::eq( 1, substr_count( $tk_pill, 'class="tk-srcs"' ), 'chips (2.6): one sources pill per item' );
TK_T::eq( 2, substr_count( $tk_pill, 'class="tk-srcs__row"' ), 'chips (2.6): one row per distinct source, repeats dropped' );
TK_T::ok( false !== strpos( $tk_pill, 'aria-expanded="false"' ) && false !== strpos( $tk_pill, 'מקורות' ), 'chips (2.6): pill is a button with the count' );
TK_T::eq( 1, substr_count( TK_Render_Guides::chips( array( $su1 ), TK_Render_Guides::cit_map( $case['citations'] ) ), 'class="tk-srcs tk-srcs--one"' ), 'chips (2.6): a single source is a direct link' );
TK_T::ok( false !== strpos( $cp, '<li>שוחד</li>' ) && false !== strpos( $cp, '<li>מרמה והפרת אמונים</li>' ), 'case: charges split into offenses per defendant' );
TK_T::ok( false !== strpos( $cp, '/trial/witness/w_346fdfeda0/' ) && 1 === substr_count( $cp, 'העיד/ה במשפט' ), 'case: people link witness pages and mark who testified' );
TK_T::ok( strpos( $cp, '>2014<' ) < strpos( $cp, '>12.3.2015<' ) && strpos( $cp, '>12.3.2015<' ) < strpos( $cp, '>יוני 2015<' ), 'case: events sorted and grouped by year with precision' );
TK_T::ok( false !== strpos( $cp, '/trial/timeline/?tk_case=4000' ), 'case: link to the timeline filtered to the case' );
TK_T::ok( false !== strpos( $cp, '/trial/hearing/' . $hr . '/' ) && false !== strpos( $cp, '/trial/document/' . $sv . '/' ), 'case: hearings and source document linked' );
TK_T::ok( false !== strpos( TK_Render_Guides::case_pending( '2000' ), 'המדריך לתיק בהכנה' ), 'case: friendly page when not published' );

// --- witness page
$wp = array(
	'slug'              => 'w_346fdfeda0', 'name' => 'אילן ישועה', 'label' => null, 'artifact_id' => null, 'blocks' => array(), 'cases' => array( '4000' ),
	'hearings'          => array( array( 'id' => $hr, 'hearing_date' => '2021-05-10', 'digest_sentences' => array( array( 'text' => 'ישועה אישר', 'citation_ids' => array( $su1 ) ) ) ), array( 'id' => 'hr_' . str_repeat( '5', 26 ), 'hearing_date' => '2021-06-08', 'digest_sentences' => array() ) ),
	'notable_exchanges' => array( array( 'hearing_id' => $hr, 'hearing_date' => '2021-05-10', 'question_unit_id' => $su1, 'answer_unit_id' => $su2, 'answer_relation' => 'affirms', 'question' => "עו\"ד חן: נכון?\nכן", 'answer' => 'זה <b>נכון</b>.', 'question_speaker' => 'עו"ד חן', 'answer_speaker' => 'אילן ישועה' ) ),
	'citations'         => array( $cit( $su1, 2 ), $cit( $su2, 3 ) ),
);
$w = TK_Render_Guides::witness_page( $wp, $witnesses );
TK_T::ok( false !== strpos( $w, '<h1 class="tk-head__title">אילן ישועה</h1>' ) && false !== strpos( $w, 'tk-case--4000' ), 'witness: name and case badge' );
TK_T::ok( false !== strpos( $w, 'סקירה של העדות בהכנה' ), 'witness: degrades without a published guide' );
TK_T::ok( false !== strpos( $w, 'דיון מיום 10.5.2021' ) && false !== strpos( $w, 'טרם פורסם תקציר לדיון זה' ), 'witness: per-hearing digest sentences, empty hearing noted' );
TK_T::ok( false !== strpos( $w, 'tk-badge--affirm' ) && false !== strpos( $w, '>אישר<' ) && false === strpos( $w, '<b>' ), 'witness: exchange with affirmed badge, escaped' );
TK_T::ok( false !== strpos( $w, '<p>נכון? כן</p>' ), 'witness: question flows without PDF line breaks or repeated speaker' );
TK_T::ok( false !== strpos( $w, 'aria-current="page"' ), 'witness: list of all witnesses marks the current one' );
TK_T::ok( false !== strpos( TK_Render_Guides::relation_badge( 'denies' ), 'tk-badge--deny' ) && false !== strpos( TK_Render_Guides::relation_badge( 'ambiguous' ), 'tk-badge--neutral' ), 'relation badges: denies / neutral' );

// --- timeline JSON embedding
$tl = array(
	'events'    => array(
		array( 'id' => 'ev_4000_0', 'track' => 'story', 'date' => '2015-03-12', 'date_precision' => 'day', 'title' => 'כותרת </script><script>alert(1)</script>', 'text' => 'a & b', 'case_keys' => array( '4000' ), 'kind' => 'indictment_fact', 'link' => array( 'type' => 'case', 'key' => '4000' ), 'citation_ids' => array( $su1, 'su_missing' ) ),
		array( 'id' => $hr, 'track' => 'trial', 'date' => '2021-05-10', 'date_precision' => 'day', 'title' => 'דיון', 'text' => null, 'case_keys' => array(), 'kind' => 'hearing', 'link' => array( 'type' => 'hearing', 'id' => $hr ), 'citation_ids' => array() ),
		array( 'id' => $sv, 'track' => 'trial', 'date' => '2021-07-04', 'date_precision' => 'day', 'title' => 'החלטה', 'text' => null, 'case_keys' => array( '2000' ), 'kind' => 'decision', 'link' => array( 'type' => 'document', 'id' => $sv ), 'citation_ids' => array() ),
	),
	'citations' => array( $su1 => $cit( $su1, 6 ) ),
	'range'     => array( 'from' => '2015-03-12', 'to' => '2021-07-04' ),
);
$th = TK_Render_Guides::timeline( $tl );
preg_match( '#<script type="application/json" class="tk-tl__data">(.*?)</script>#s', $th, $m );
TK_T::ok( isset( $m[1] ) && false === stripos( $m[1], '</script' ) && false === strpos( $m[1], '<' ), 'timeline: JSON cannot close the script element' );
$pl = isset( $m[1] ) ? json_decode( $m[1], true ) : null;
TK_T::ok( is_array( $pl ) && 3 === count( $pl['events'] ) && 'כותרת </script><script>alert(1)</script>' === $pl['events'][0]['title'], 'timeline: JSON round-trips the original text' );
TK_T::eq( array( $su1 ), $pl['events'][0]['cits'] ?? null, 'timeline: unknown citations dropped' );
TK_T::eq( 'https://site.test/trial/case/4000/', $pl['events'][0]['url'] ?? '', 'timeline: story event links the case page' );
TK_T::eq( 'https://site.test/trial/hearing/' . $hr . '/', $pl['events'][1]['url'] ?? '', 'timeline: hearing event links the hearing page' );
TK_T::eq( 'עמ׳ 6', $pl['citations'][ $su1 ]['label'] ?? '', 'timeline: citation chip data' );
TK_T::ok( false !== strpos( $th, 'class="tk-tl__fallback"' ) && false !== strpos( $th, '>2015<' ) && false === strpos( $th, '<script>alert' ), 'timeline: escaped no-JS list grouped by year' );
$th4 = TK_Render_Guides::timeline( $tl, '4000' );
TK_T::ok( false !== strpos( $th4, 'data-case="4000"' ) && false === strpos( $th4, '>החלטה</a>' ) && false !== strpos( $th4, '>דיון</a>' ), 'timeline: case preselect filters the fallback (unassigned trial events kept)' );
TK_T::ok( false !== strpos( TK_Render_Guides::timeline( array( 'events' => array( $tl['events'][1] ) ) ), 'יוצגו כאן אחרי שהמדריכים' ), 'timeline: note while no story events are published' );
TK_T::ok( false === strpos( TK_Render_Guides::timeline( $tl, '<x>' ), '<x>' ), 'timeline: invalid case param ignored' );

// --- glossary
$gl = array(
	'note'  => 'הסברים כלליים',
	'terms' => array(
		array( 'id' => 'cross-examination', 'term' => 'חקירה נגדית', 'aliases' => array( 'בחקירה נגדית' ), 'category' => 'procedure', 'short' => 'קצר <i>x</i>', 'long' => 'ארוך', 'see_also' => array( 'case-4000' ), 'link' => null ),
		array( 'id' => 'case-4000', 'term' => 'תיק 4000', 'aliases' => array(), 'category' => 'documents', 'short' => 'בזק', 'long' => '', 'see_also' => array(), 'link' => array( 'type' => 'case', 'key' => '4000' ) ),
	),
);
$gh = TK_Render_Guides::glossary( $gl );
TK_T::ok( false !== strpos( $gh, 'id="term-cross-examination"' ) && false !== strpos( $gh, 'id="cat-procedure"' ) && false !== strpos( $gh, 'href="#term-case-4000"' ), 'glossary: anchors per term and category, see-also links' );
TK_T::ok( false !== strpos( $gh, 'הסברים כלליים' ) && false === strpos( $gh, '<i>' ) && false !== strpos( $gh, '/trial/case/4000/' ), 'glossary: note shown, escaped, case terms link the case page' );
$gd = TK_Guides::glossary_script_data( $gl );
TK_T::eq( 'https://site.test/trial/glossary/#term-cross-examination', $gd['terms'][0]['url'], 'glossary tooltip links the glossary anchor' );
TK_T::eq( 'https://site.test/trial/case/4000/', $gd['terms'][1]['url'], 'glossary tooltip for a case term links the case page' );

// --- hearing page with tabs
$hd = array(
	'hearing' => array( 'id' => $hr, 'hearing_date' => '2025-09-17', 'judges' => array( 'שופטת א' ), 'witnesses' => array( 'נאשם 1 — בנימין נתניהו', 'דובי שרצר' ), 'source_version_id' => $sv ),
	'digest'  => array( 'summary_sentences' => array( array( 'text' => 'תקציר', 'citation_ids' => array( $su1 ) ) ), 'citations' => array( $cit( $su1, 4 ) ), 'topics' => array( 'נושא' ), 'notable_exchanges' => array() ),
);
$tr = array( 'page_from' => 1, 'page_to' => 25, 'page_count' => 60, 'next_page_from' => 26, 'prev_page_from' => null, 'pdf_url' => 'https://api.test/pdf', 'document' => array( 'source_version_id' => $sv, 'title' => 'פרוטוקול', 'source_type' => 'protocol', 'page_count' => 60 ), 'units' => array() );
$hp = TK_Render_Guides::hearing_page( $hd, array( 'transcript' => $tr, 'slugs' => $slugs, 'exchanges' => array(), 'tab' => 'full' ) );
TK_T::ok( false !== strpos( $hp, 'tk_tab=full&amp;tk_p=26#tk-tab-full' ), 'hearing: transcript pager keeps the full-protocol tab' );
TK_T::ok( false !== strpos( $hp, 'data-active="full"' ) && false !== strpos( $hp, 'id="tk-tab-full" data-tab="full"' ) && false !== strpos( $hp, 'class="tk-tabs__panel is-active" id="tk-tab-full"' ), 'hearing: requested tab is active' );
TK_T::eq( 4, substr_count( $hp, 'class="tk-tabs__tab"' ), 'hearing: four tabs' );
TK_T::ok( false !== strpos( $hp, 'href="#tk-tab-summary"' ), 'hearing: tabs are anchors without JS' );
TK_T::ok( false !== strpos( $hp, '/trial/witness/w_72da315abb/' ) && false !== strpos( $hp, 'דובי שרצר' ) && false !== strpos( $hp, 'שופטת א' ), 'hearing: witnesses linked by slug (label stripped), judges listed' );
TK_T::ok( false !== strpos( $hp, 'לא סומנו שאלות ותשובות' ) && false !== strpos( $hp, 'https://api.test/pdf' ) && false !== strpos( $hp, '/trial/document/' . $sv . '/' ), 'hearing: Q/A placeholder and source document tab' );
$hp2 = TK_Render_Guides::hearing_page( $hd, array( 'transcript' => null ) );
TK_T::ok( false !== strpos( $hp2, 'class="tk-tabs__panel is-active" id="tk-tab-summary"' ) && false !== strpos( $hp2, 'המידע אינו זמין' ), 'hearing: default summary tab; transcript error degrades' );

// --- webhooks purge guide caches
$tags = TK_Webhooks::tags_for( array( 'event' => 'artifact.published', 'payload' => array( 'artifact_type' => 'guide', 'object_type' => 'case', 'object_id' => '4000' ) ) );
TK_T::ok( in_array( 'guide', $tags, true ) && in_array( 'guide:case:4000', $tags, true ) && in_array( 'timeline', $tags, true ) && in_array( 'lists', $tags, true ), 'webhook: published case guide purges guide, case and timeline caches' );
$tags = TK_Webhooks::tags_for( array( 'event' => 'artifact.unpublished', 'payload' => array( 'artifact_type' => 'guide', 'object_type' => 'witness', 'object_id' => 'w_346fdfeda0' ) ) );
TK_T::ok( in_array( 'witness:w_346fdfeda0', $tags, true ) && in_array( 'guide', $tags, true ), 'webhook: unpublished witness guide purges the witness page' );
$tags = TK_Webhooks::tags_for( array( 'event' => 'source_version.published', 'payload' => array( 'source_version_id' => $sv ) ) );
TK_T::ok( in_array( 'timeline', $tags, true ) && in_array( 'guide', $tags, true ), 'webhook: corpus change purges guide caches' );
tk_test_reset_store();
TK_Cache::remember( '/v2/guide', function () { return array( 'x' => 1 ); } );
TK_Cache::purge( TK_Webhooks::tags_for( array( 'event' => 'artifact.published', 'payload' => array( 'artifact_type' => 'guide', 'object_type' => 'indictment', 'object_id' => 'main' ) ) ) );
TK_Sync::run_refresh();
TK_T::eq( array( '/v2/guide' ), tk_api()->calls, 'webhook: start page refetched after an indictment guide is published' );

// --- duplicates admin screen (2.3.1)
require_once TK_DIR . 'includes/class-permissions.php';
require_once TK_DIR . 'includes/class-admin-duplicates.php';
$pub = array( 'kind' => 'source', 'publication_state' => 'published', 'source_version_id' => 'sv_' . str_repeat( 'a', 26 ), 'hearing_id' => null, 'title' => 'החלטה <b>x</b>' );
TK_T::ok( false !== strpos( TK_Admin_Duplicates::kept_link( $pub ), '/document/sv_' ), 'duplicates: published source links to its document page' );
TK_T::ok( false !== strpos( TK_Admin_Duplicates::kept_link( array_merge( $pub, array( 'hearing_id' => 'hr_' . str_repeat( 'b', 26 ) ) ) ), '/hearing/hr_' ), 'duplicates: protocol links to its hearing page' );
TK_T::ok( '' === TK_Admin_Duplicates::kept_link( array_merge( $pub, array( 'publication_state' => 'draft' ) ) ), 'duplicates: unpublished source has no public link' );
TK_T::ok( false === strpos( TK_Admin_Duplicates::kept_html( $pub ), '<b>x</b>' ), 'duplicates: kept title is escaped' );
TK_T::ok( false !== strpos( TK_Admin_Duplicates::kept_html( array( 'kind' => 'inbox', 'object_key' => 'inbox/a.pdf', 'status' => 'ingested' ) ), 'inbox/a.pdf' ), 'duplicates: kept inbox file shows its key' );
TK_T::ok( false !== strpos( TK_Admin_Duplicates::kept_html( null ), 'לא ידוע' ), 'duplicates: unknown kept copy' );
