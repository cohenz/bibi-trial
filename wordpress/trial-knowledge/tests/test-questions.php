<?php
// --- visitors' questions (2.7.8)
tk_test_reset_store();
$env = function ( $id, $q, $short = 'קצר' ) {
	return array( 'answer_id' => $id, 'question' => $q, 'normalized_question' => $q, 'answer_status' => 'answered', 'answer_short' => $short,
		'sections' => array( array( 'kind' => 'defense', 'text' => 'נקודה <b>x</b>', 'citation_ids' => array() ) ), 'citations' => array(),
		'as_of' => '2026-10-13T00:00:00+00:00', 'corpus_version' => 'cv-1', 'latest_permalink' => null );
};
TK_T::eq( '1000', TK_Questions::guess_topic( 'מה עלה לגבי השמפניות והסיגרים?' ), 'topic: champagne → 1000' );
TK_T::eq( '4000', TK_Questions::guess_topic( 'מה העיד ניר חפץ על וואלה?' ), 'topic: Walla → 4000' );
TK_T::eq( '2000', TK_Questions::guess_topic( 'מה אמר מוזס על ידיעות?' ), 'topic: Mozes → 2000' );
TK_T::eq( 'general', TK_Questions::guess_topic( 'כמה ימי דיון יש בשבוע?' ), 'topic: none → general' );

$now  = '2026-10-13 18:00:00';
$item = array( 'answer_id' => 'a-1', 'question' => 'מה עם השמפניות?', 'normalized_question' => 'מה עם השמפניות', 'answer_status' => 'answered', 'created_at' => '2026-10-13T17:00:00+00:00', 'envelope' => $env( 'a-1', 'מה עם השמפניות?' ) );
$row  = TK_Questions::merge( null, $item, $now );
TK_T::ok( 'pending' === $row['state'] && '1000' === $row['topic'] && 64 === strlen( $row['qkey'] ) && '2026-10-13 17:00:00' === $row['answered_at'], 'merge: a new question waits for the admin, topic guessed' );
TK_T::eq( null, TK_Questions::merge( $row, $item, $now ), 'merge: the same answer changes nothing' );
$newer = array_merge( $item, array( 'answer_id' => 'a-2', 'created_at' => '2026-10-14T09:00:00+00:00', 'envelope' => $env( 'a-2', 'מה עם השמפניות?', 'חדש' ) ) );
$r2    = TK_Questions::merge( $row, $newer, $now );
TK_T::ok( 'a-2' === $r2['answer_id'] && '' === $r2['next_envelope'], 'merge: a newer answer replaces one that is not shown' );
$shown = array_merge( $row, array( 'state' => 'shown' ) );
$r3    = TK_Questions::merge( $shown, $newer, $now );
TK_T::ok( 'a-1' === $r3['answer_id'] && false !== strpos( $r3['next_envelope'], 'a-2' ), 'merge: a shown question keeps its answer; the newer one waits' );
TK_T::eq( null, TK_Questions::merge( $r3, $newer, $now ), 'merge: the waiting answer is not queued twice' );
$older = array_merge( $item, array( 'answer_id' => 'a-0', 'created_at' => '2026-10-01T00:00:00+00:00' ) );
TK_T::eq( null, TK_Questions::merge( $row, $older, $now ), 'merge: an older answer is ignored' );

// storage and admin changes (fake wpdb)
TK_Questions::put( $shown );
TK_Questions::put( $r3 );
TK_Questions::update( $row['qkey'], array( 'accept_update' => true, 'topic' => '4000', 'display_question' => 'נוסח <i>מתוקן</i>' ) );
$got = TK_Questions::get( $row['qkey'] );
TK_T::ok( 'a-2' === $got['answer_id'] && '' === $got['next_envelope'] && '4000' === $got['topic'] && false !== strpos( $got['display_question'], 'מתוקן' ), 'update: accept the newer answer, topic, wording' );
TK_Questions::update( $row['qkey'], array( 'display_question' => $got['question'], 'state' => 'bogus', 'topic' => 'x' ) );
$got = TK_Questions::get( $row['qkey'] );
TK_T::ok( '' === $got['display_question'] && 'shown' === $got['state'] && '4000' === $got['topic'], 'update: the original wording clears the override; unknown values are ignored' );

// public list: most opened first, chips for the topics present, escaped
$a = array_merge( $row, array( 'qkey' => str_repeat( 'a', 64 ), 'opens' => 2, 'topic' => '1000', 'question' => 'שאלה <script>א</script>', 'answered_at' => '2026-10-10 00:00:00' ) );
$b = array_merge( $row, array( 'qkey' => str_repeat( 'b', 64 ), 'opens' => 9, 'topic' => '4000', 'question' => 'שאלה ב', 'display_question' => 'נוסח ב', 'answered_at' => '2026-10-01 00:00:00' ) );
$c = array_merge( $row, array( 'qkey' => str_repeat( 'c', 64 ), 'opens' => 2, 'topic' => 'general', 'question' => 'שאלה ג', 'answered_at' => '2026-10-12 00:00:00' ) );
$html = TK_Questions::render_public( array( $a, $b, $c ) );
TK_T::ok( strpos( $html, 'נוסח ב' ) < strpos( $html, 'שאלה ג' ) && strpos( $html, 'שאלה ג' ) < strpos( $html, 'שאלה &lt;script' ), 'public: most opened first, then the newest' );
TK_T::ok( false === strpos( $html, '<script>' ) && false === strpos( $html, '<b>' ) && 3 === substr_count( $html, '<details class="tk-q"' ), 'public: escaped, collapsed' );
TK_T::ok( false !== strpos( $html, 'data-topic="1000" aria-pressed="false"' ) && false === strpos( $html, 'data-topic="2000"' ) && false !== strpos( $html, 'id="q-aaaaaaaaaaaa"' ), 'public: chips only for topics present; anchors' );
TK_T::ok( false !== strpos( TK_Questions::render_public( array() ), 'עדיין אין כאן שאלות' ), 'public: empty state' );

// admin
list( $w, $k ) = TK_Admin_Questions::parse_do( 'bulk:shown', array( str_repeat( 'a', 64 ), 'bad' ) );
TK_T::ok( 'shown' === $w && array( str_repeat( 'a', 64 ) ) === $k, 'admin: bulk show takes only valid keys' );
TK_T::eq( array( 'accept', array( str_repeat( 'b', 64 ) ) ), TK_Admin_Questions::parse_do( 'accept:' . str_repeat( 'b', 64 ), array() ), 'admin: one row action' );
TK_T::eq( array( '', array() ), TK_Admin_Questions::parse_do( 'shown:zz', array() ), 'admin: a malformed action does nothing' );
$adm = TK_Admin_Questions::render( array( $a, $r3 ), array( 'pending' => 1, 'shown' => 1, 'hidden' => 0 ), 'pending', array() );
TK_T::ok( false !== strpos( $adm, 'החלפה בתשובה החדשה' ) && false !== strpos( $adm, 'ממתינות <span class="count">(1)' ) && false === strpos( $adm, '<script>' ), 'admin: tabs, newer-answer action, escaped' );

// limits form
TK_T::eq( array( 'per_visitor_daily' => 5, 'daily' => null ), TK_Admin_Costs::parse_limits( array( 'per_visitor_daily' => ' 5 ', 'daily' => '', 'x' => '1' ) ), 'limits: filled → int, emptied → back to default' );
$lf = TK_Admin_Costs::limits_form( array( 'per_visitor_daily' => 5, 'daily' => 200, 'per_minute' => 6, 'railway' => array( 'per_visitor_daily' => 20, 'daily' => 200, 'per_minute' => 6 ), 'source' => array( 'per_visitor_daily' => 'admin', 'daily' => 'railway', 'per_minute' => 'railway' ) ) );
TK_T::ok( false !== strpos( $lf, 'name="per_visitor_daily" min="0" max="10000" value="5" placeholder="20"' ) && false !== strpos( $lf, 'name="daily" min="0" max="100000" value=""' ), 'limits: overrides filled, defaults as placeholders' );
tk_test_reset_store();
// 2.7.9: upgrading from table version 1 drops the rows nobody acted on (evaluation questions) and restarts the sync
tk_test_reset_store();
update_option( TK_Questions::OPT_DB, '1' );
update_option( TK_Questions::OPT_SINCE, '2026-10-13T19:00:00+00:00' );
TK_Questions::put( array_merge( $row, array( 'qkey' => str_repeat( 'd', 64 ) ) ) );
TK_Questions::put( array_merge( $row, array( 'qkey' => str_repeat( 'e', 64 ), 'state' => 'shown' ) ) );
TK_Questions::maybe_upgrade();
TK_T::ok( null === TK_Questions::get( str_repeat( 'd', 64 ) ) && null !== TK_Questions::get( str_repeat( 'e', 64 ) ) && false === get_option( TK_Questions::OPT_SINCE ), 'upgrade 2: untouched pending rows dropped, approved kept, sync restarts' );
tk_test_reset_store();
// 2.7.10: answers held for the editor
$held = array( array(
	'answer_id' => '11111111-2222-5333-8444-555555555555', 'question' => 'מה המשמעות של <b>הקשיים</b>?', 'created_at' => '2026-10-16T05:50:00Z',
	'gate_report' => array( 'gates' => array( array( 'gate' => 'support', 'passed' => false, 'details' => array( array( 'path' => 'sections/1', 'problem' => 'low_lexical_support' ) ) ), array( 'gate' => 'verifier', 'passed' => true ) ), 'risk_flags' => array() ),
	'writer'      => array( 'output' => array( 'answer_short' => 'קצר', 'sections' => array(
		array( 'kind' => 'allegation', 'text' => 'כתב האישום טוען', 'citation_ids' => array() ),
		array( 'kind' => 'defense', 'text' => 'נקודה <script>א</script>', 'citation_ids' => array() ),
		array( 'kind' => 'defense', 'text' => 'נקודה ב', 'citation_ids' => array() ),
	) ) ),
	'verifier'    => array( 'output' => array( 'assertions' => array(
		array( 'path' => 'answer_short', 'supported' => 'yes', 'attribution_ok' => true ),
		array( 'path' => 'sections/1', 'supported' => 'yes', 'attribution_ok' => true ),
		array( 'path' => 'sections/2', 'supported' => 'partial', 'attribution_ok' => false, 'note' => 'ייחוס' ),
	) ) ),
) );
$hh = TK_Admin_Questions::render_held( $held );
TK_T::ok( false === strpos( $hh, '<script>' ) && false === strpos( $hh, '<b>' ) && false !== strpos( $hh, 'value="approve"' ), 'held: escaped, approve offered' );
TK_T::ok( false !== strpos( $hh, 'value="sections/2" checked' ) && false === strpos( $hh, 'value="sections/1" checked' ), 'held: what the verifier did not approve is ticked to omit; a mechanical-only flag is not' );
TK_T::ok( false !== strpos( $hh, 'מעט מילים משותפות' ) && false !== strpos( $hh, 'בדיקה מכנית' ), 'held: the reason in plain words' );
$nod = $held;
$nod[0]['writer'] = array( 'output' => array() );
TK_T::ok( false === strpos( TK_Admin_Questions::render_held( $nod ), 'value="approve"' ), 'held: no draft → only reject' );
TK_T::ok( false !== strpos( TK_Admin_Questions::tabs( array( 'pending' => 2, 'held' => 3 ), 'held' ), 'שנעצרו לבדיקה <span class="count">(3)' ), 'tabs: the held count' );
// 2.7.11: only the latest answer to each question is held for the editor
$lh = TK_Admin_Questions::latest_held( array(
	array( 'answer_id' => 'k1', 'normalized_question' => 'קליין', 'answer_status' => 'requires_human_review', 'created_at' => '2026-10-13T18:10:00Z' ),
	array( 'answer_id' => 'k3', 'normalized_question' => 'קליין', 'answer_status' => 'requires_human_review', 'created_at' => '2026-10-16T07:51:00Z' ),
	array( 'answer_id' => 'b1', 'normalized_question' => 'ברנור', 'answer_status' => 'requires_human_review', 'created_at' => '2026-10-13T18:09:00Z' ),
	array( 'answer_id' => 'b2', 'normalized_question' => 'ברנור', 'answer_status' => 'answered', 'created_at' => '2026-10-16T07:51:00Z' ),
	array( 'answer_id' => 'q1', 'normalized_question' => 'קשיים', 'answer_status' => 'requires_human_review', 'created_at' => '2026-10-16T05:50:00Z', 'human_decision' => 'reject' ),
) );
TK_T::eq( array( 'k3' ), array_column( $lh, 'answer_id' ), 'held: only the latest per question; none once published or decided' );
