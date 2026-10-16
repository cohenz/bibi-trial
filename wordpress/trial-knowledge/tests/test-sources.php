<?php
// --- sources (2.7.13): the type of an upload; unpublished uploads and what to do with them
TK_T::eq( array( 'source_type' => 'protocol', 'auto_kind' => true ), TK_Admin_Sources::kind_fields( 'auto' ), 'kind: automatic = protocol unless it is not a hearing record' );
TK_T::eq( array( 'source_type' => 'motion' ), TK_Admin_Sources::kind_fields( 'motion' ), 'kind: chosen' );
TK_T::eq( array( 'source_type' => 'protocol', 'auto_kind' => true ), TK_Admin_Sources::kind_fields( 'bogus' ), 'kind: unknown → automatic' );
$sv = 'sv_' . str_repeat( 'a', 26 );
$c = TK_Admin_Sources::action_calls( 'publish', $sv, 'protocol', '', '', 'protocol', true );
TK_T::ok( 1 === count( $c ) && "/v2/admin/sources/$sv/publish" === $c[0][0] && $c[0][1] instanceof stdClass, 'publish a protocol as it is' );
$c = TK_Admin_Sources::action_calls( 'publish', $sv, 'other', 'בקשת חנינה', 'באי כוח נאשם 1 (נתניהו)', 'protocol', true );
TK_T::ok( 1 === count( $c ) && "/v2/admin/sources/$sv/classify" === $c[0][0] && true === $c[0][1]['publish'] && 'other' === $c[0][1]['kind'] && 'בקשת חנינה' === $c[0][1]['title'], 'a protocol that is not one: classify and publish in one call' );
TK_T::eq( array(), TK_Admin_Sources::action_calls( 'save', $sv, 'protocol', '', '', 'protocol', true ), 'save with nothing changed calls nothing' );
TK_T::eq( 'withdraw', substr( TK_Admin_Sources::action_calls( 'withdraw', $sv, 'other', '', '', 'decision', false )[0][0], -8 ), 'withdraw' );
$c = TK_Admin_Sources::action_calls( 'save', $sv, 'other', '', '', 'decision', false );
TK_T::ok( 1 === count( $c ) && false === $c[0][1]['publish'], 'fix the type of a published document without publishing again' );
$html = TK_Admin_Sources::render_pending( array( array( 'id' => $sv, 'title' => 'בקשת <b>חנינה</b>', 'source_type' => 'protocol', 'source_owner' => 'הרשות השופטת', 'page_count' => 111, 'unit_count' => 116, 'hearing_id' => 'hr_x', 'hearing_date' => '2025-11-30',
	'same_file' => array( array( 'title' => 'החלטה — 2025-11-30', 'source_type' => 'decision', 'publication_state' => 'published' ) ), 'units' => array( array( 'page' => 1, 'speaker' => null, 'text' => 'כבוד <script>' ) ) ) ) );
TK_T::ok( false === strpos( $html, '<b>' ) && false === strpos( $html, '<script>' ) && false !== strpos( $html, 'נקלט כדיון מיום 2025-11-30' ) && false !== strpos( $html, 'אותו קובץ בדיוק כבר במאגר' ), 'pending: escaped, hearing and duplicate shown' );
TK_T::ok( false !== strpos( $html, 'value="withdraw"' ) && false !== strpos( $html, 'name="tk_sv"' ), 'pending: withdraw offered; a published document can be re-typed' );
