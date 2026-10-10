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
TK_T::ok( false !== strpos( $html, 'עמ׳ 3, שורות 4–6' ), 'citation shows page and lines' );
TK_T::ok( false !== strpos( $html, 'dir="rtl"' ), 'RTL container' );
$env  = array( 'answer_id' => '22222222-2222-5222-8222-222222222222', 'answer_status' => 'false_premise_corrected', 'answer_short' => 'לא <i>זוכה</i>', 'sections' => array(), 'citations' => array(), 'as_of' => '2026-10-10T00:00:00+00:00', 'corpus_version' => 'cv-000009', 'latest_permalink' => null );
$a    = TK_Render::answer( $env );
TK_T::ok( false === strpos( $a, '<i>' ) && false !== strpos( $a, 'cv-000009' ) && false !== strpos( $a, '/trial/answer/22222222' ), 'answer escaped, shows corpus version and permalink' );
