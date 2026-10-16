<?php
$cit  = array( 'source_unit_id' => 'su_' . str_repeat( 'a', 26 ), 'source_version_id' => 'sv_' . str_repeat( 'b', 26 ), 'page' => 3, 'line_start' => 4, 'line_end' => 6, 'speaker' => '<script>x</script>', 'quote' => null, 'court_record_status' => 'filed', 'permalink' => 'https://api.test/v2/citations/su_x' );
$card = array(
	'status_as_of' => array( 'status' => 'disputed' ),
	'bundle'       => array(
		'claim_id' => '11111111-1111-5111-8111-111111111111', 'question' => 'שאלה "עם" <b>תגים</b>?', 'claim_text' => 'טענה', 'status' => 'disputed',
		'as_of' => '2026-10-10T00:00:00+00:00', 'answer_short' => 'קצר', 'citations' => array( $cit ),
		'support' => array( array( 'evidence_id' => 'e', 'summary' => 'מחזק <img src=x onerror=alert(1)>', 'direction' => 'supports', 'court_record_status' => 'filed', 'citation_ids' => array( $cit['source_unit_id'] ) ) ),
		'weakness' => array(), 'court_position' => array( 'level' => 'question_or_comment', 'summary' => 'שאלת שופט', 'citation_ids' => array( $cit['source_unit_id'] ) ),
		'unresolved_questions' => array(), 'review' => array( 'state' => 'published', 'risk_flags' => array() ),
	),
);
$html = TK_Render::claim_card( $card );
TK_T::ok( false === strpos( $html, '<script>' ) && false === strpos( $html, '<img' ) && false === strpos( $html, '<b>' ), 'claim card escapes untrusted text' );
TK_T::ok( false !== strpos( $html, 'מה מחליש או סותר אותה' ) && false !== strpos( $html, 'לא נמצא חומר מחליש' ), 'four boxes present incl. empty weakness box' );
TK_T::ok( false !== strpos( $html, 'שאלה או הערה של שופט — אינה החלטה' ), 'judicial level labelled as not a ruling' );
TK_T::ok( false !== strpos( $html, 'עמ׳ 3, שורות ⁦4–6⁩' ), 'citation shows page and lines' );
TK_T::ok( false !== strpos( $html, 'dir="rtl"' ), 'RTL container' );
$env  = array( 'answer_id' => '22222222-2222-5222-8222-222222222222', 'answer_status' => 'false_premise_corrected', 'answer_short' => 'לא <i>זוכה</i>', 'sections' => array(), 'citations' => array(), 'as_of' => '2026-10-10T00:00:00+00:00', 'corpus_version' => 'cv-000009', 'latest_permalink' => null );
$a    = TK_Render::answer( $env );
TK_T::ok( false === strpos( $a, '<i>' ) && false !== strpos( $a, 'cv-000009' ) && false !== strpos( $a, '/trial/answer/22222222' ), 'answer escaped, shows corpus version and permalink' );
// 2.7.5: an answer built on the defense's case — the defense's points form one section with a numbered list
$sid  = $cit['source_unit_id'];
$envd = array_merge( $env, array( 'answer_status' => 'answered', 'citations' => array( $cit ), 'sections' => array(
	array( 'kind' => 'allegation', 'text' => 'לפי כתב האישום…', 'citation_ids' => array( $sid ) ),
	array( 'kind' => 'defense', 'text' => 'נקודה ראשונה <b>x</b>', 'citation_ids' => array( $sid ) ),
	array( 'kind' => 'defense', 'text' => 'נקודה שנייה', 'citation_ids' => array( $sid ) ),
	array( 'kind' => 'prosecution', 'text' => 'התביעה נשענת על…', 'citation_ids' => array( $sid ) ),
) ) );
$ad = TK_Render::answer( $envd );
TK_T::ok( 1 === substr_count( $ad, 'מה התגלה בדיונים' ) && 2 === substr_count( $ad, 'class="tk-answer__para"' ) && false === strpos( $ad, '<li>' ), 'answer (2.7.12): findings grouped under one neutral heading, as paragraphs' );
TK_T::ok( false !== strpos( $ad, 'טענת התביעה' ) && false !== strpos( $ad, 'תשובת התביעה' ) && false === strpos( $ad, 'לטובת ההגנה' ) && false === strpos( $ad, '<b>' ), 'answer (2.7.12): neutral labels, text escaped' );

// 2.2: full transcript and documents
$su = 'su_' . str_repeat( 'c', 26 );
$t  = array(
	'page_from' => 1, 'page_to' => 2, 'page_count' => 60, 'next_page_from' => 26, 'prev_page_from' => null,
	'pdf_url'   => 'https://api.test/v2/sources/sv_x/pdf',
	'units'     => array(
		array( 'id' => $su, 'page' => 1, 'line_start' => 3, 'line_end' => 5, 'speaker' => 'עו"ד <b>חדד</b>', 'unit_type' => 'question', 'text' => "ש. האם ידעת?\n<script>", 'exchange_label' => null ),
		array( 'id' => 'su_' . str_repeat( 'd', 26 ), 'page' => 2, 'line_start' => 1, 'line_end' => 1, 'speaker' => 'העד', 'unit_type' => 'answer', 'text' => 'לא.', 'exchange_label' => 'העד הכחיש את הנטען' ),
	),
);
$h = TK_Render::transcript( $t, 'https://site.test/trial/hearing/hr_x/' );
TK_T::ok( false === strpos( $h, '<script>' ) && false === strpos( $h, '<b>' ), 'transcript escapes text and speakers' );
TK_T::ok( false !== strpos( $h, 'id="' . $su . '"' ) && false !== strpos( $h, 'עמוד 1' ) && false !== strpos( $h, 'עמוד 2' ), 'units anchored and grouped by page' );
TK_T::ok( false !== strpos( $h, 'tk_p=26' ) && false !== strpos( $h, 'עמודים ⁦1–2⁩ מתוך 60' ) && false !== strpos( $h, 'PDF המקורי' ), 'pager with next page and PDF link' );
// 2.6: short texts stay open; the (i) note on extracted text; the PDF toggle
TK_T::ok( false === strpos( $h, '<details' ) && false !== strpos( $h, 'class="tk-info"' ) && false !== strpos( $h, 'קריאת מחשב' ), 'transcript (2.6): 2 pages stay open, (i) note shown' );
$t5          = $t;
$t5['units'] = array();
for ( $pn = 1; $pn <= 5; $pn++ ) {
	$t5['units'][] = array( 'id' => 'su_' . str_repeat( (string) $pn, 26 ), 'page' => $pn, 'line_start' => 1, 'line_end' => 2, 'speaker' => 'העד', 'unit_type' => 'answer', 'text' => 'כן.', 'exchange_label' => null );
}
$h5 = TK_Render::transcript( $t5, 'https://site.test/trial/hearing/hr_x/' );
TK_T::eq( 5, substr_count( $h5, '<details class="tk-tpage" id="page-' ), 'transcript (2.6): longer texts collapse page by page' );
TK_T::ok( false === strpos( $h5, '<details class="tk-tpage" id="page-1" open' ) && false !== strpos( $h5, 'data-tk-pages="open"' ) && false !== strpos( $h5, 'data-tk-only' ), 'transcript (2.6): collapsed, with open-all and only-this-page controls' );
update_option( TK_OPTION, array( 'show_pdf' => 0, 'ocr_disclaimer' => '' ) );
$hn = TK_Render::transcript( $t, 'https://site.test/trial/hearing/hr_x/' );
TK_T::ok( false === strpos( $hn, 'PDF המקורי' ) && false === strpos( $hn, '/pdf' ), 'PDF toggle off (2.6): no link to the original PDF' );
TK_T::ok( false === strpos( $hn, 'class="tk-info"' ), 'empty disclaimer (2.6): no (i)' );
update_option( TK_OPTION, array() );
TK_T::ok( false !== strpos( $h, 'tk-badge--deny' ) && false !== strpos( $h, 'title="העד הכחיש את הנטען"' ), 'verified Q/A label shown as a short badge' );
$docs = TK_Render::documents( array( 'items' => array( array( 'source_version_id' => 'sv_' . str_repeat( 'e', 26 ), 'title' => 'החלטה <i>x</i>', 'source_type' => 'decision', 'document_date' => '2025-10-12', 'page_count' => 3 ) ) ) );
TK_T::ok( false !== strpos( $docs, '/trial/document/sv_eeee' ) && false !== strpos( $docs, 'החלטה' ) && false === strpos( $docs, '<i>' ), 'documents list links document pages, escaped' );
TK_T::ok( false !== strpos( TK_Render::documents( array( 'items' => array() ) ), 'עדיין לא פורסמו' ), 'empty documents list' );
$ctx = TK_Render::in_context_url( array( 'citation' => array( 'page' => 30, 'source_unit_id' => $su, 'source_version_id' => 'sv_y' ), 'hearing_id' => 'hr_z' ) );
TK_T::eq( 'https://site.test/trial/hearing/hr_z/?tk_p=26#' . $su, $ctx, 'citation links into the transcript page range' );
$tl = TK_Render::timeline( array( 'events' => array(), 'hearings' => array(), 'documents' => array( array( 'source_version_id' => 'sv_' . str_repeat( 'f', 26 ), 'title' => 'החלטה', 'source_type' => 'decision', 'document_date' => '2025-10-12' ) ) ) );
TK_T::ok( false !== strpos( $tl, '2025-10-12' ) && false !== strpos( $tl, '/trial/document/sv_ffff' ), 'timeline lists dated documents' );
$dup = TK_Render::transcript( array( 'page_from' => 1, 'page_to' => 1, 'page_count' => 1, 'units' => array( array( 'id' => 'su_' . str_repeat( '9', 26 ), 'page' => 1, 'line_start' => 1, 'line_end' => 1, 'speaker' => 'עו"ד תירוש', 'unit_type' => 'speech_turn', 'text' => 'עו"ד תירוש: אוקי.', 'exchange_label' => null ) ) ), 'https://site.test/x/' );
TK_T::ok( false === strpos( $dup, 'tk-u__speaker' ), 'speaker printed in the text is not repeated' );

$chip = TK_Render::citation_chip( array( 'source_unit_id' => $su, 'page' => 118, 'line_start' => 3, 'line_end' => 5, 'speaker' => 'עו"ד <x>' ) );
TK_T::ok( false !== strpos( $chip, '>עמ׳ 118<' ) && false === strpos( $chip, '<x>' ), 'compact citation chip, escaped tooltip' );
$tl2 = TK_Render::timeline( array( 'events' => array(), 'hearings' => array(), 'documents' => array( array( 'source_version_id' => 'sv_' . str_repeat( 'a', 26 ), 'title' => 'החלטה: על בקשה', 'source_type' => 'decision', 'document_date' => '2025-01-01' ) ) ) );
TK_T::ok( false === strpos( $tl2, 'החלטה: החלטה' ), 'timeline does not repeat the type label' );
