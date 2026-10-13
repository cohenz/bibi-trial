<?php
// 2.7 wayfinding: site bar, breadcrumbs, stages, grouped witnesses, layered witness page, documents page.
$ws27 = array(
	array( 'slug' => 'w_346fdfeda0', 'name' => 'אילן ישועה', 'label' => null, 'side' => 'prosecution', 'hearing_count' => 28, 'appearance_count' => 0, 'first_date' => '2021-04-05', 'last_date' => '2021-10-04', 'cases' => array( '4000' ) ),
	array( 'slug' => 'w_d1dc28ccdd', 'name' => 'אבירם אלעד', 'label' => null, 'side' => null, 'hearing_count' => 1, 'appearance_count' => 0, 'first_date' => '2021-10-11', 'last_date' => '2021-10-11', 'cases' => array() ),
	array( 'slug' => 'w_72da315abb', 'name' => 'בנימין נתניהו', 'label' => 'נאשם 1', 'side' => 'defense', 'hearing_count' => 81, 'appearance_count' => 2, 'first_date' => '2024-12-10', 'last_date' => '2026-06-24', 'cases' => array( '4000', '2000', '1000' ) ),
	array( 'slug' => 'w_b2823a1512', 'name' => 'יורם נעמן', 'label' => null, 'side' => 'defense', 'hearing_count' => 6, 'appearance_count' => 0, 'first_date' => '2026-01-04', 'last_date' => '2026-04-19', 'cases' => array() ),
	array( 'slug' => 'w_63b8ed8847', 'name' => 'רונית מנדלבוים', 'label' => null, 'side' => null, 'hearing_count' => 1, 'appearance_count' => 0, 'first_date' => '2026-09-16', 'last_date' => '2026-09-16', 'cases' => array() ),
);

// --- bar and breadcrumbs
$bar = TK_Render_Nav::bar( 'witnesses', array( array( 'עדים', 'https://site.test/trial/witnesses/' ), array( 'אילן <ישועה>', '' ) ) );
TK_T::eq( 7, substr_count( $bar, 'class="tk-subnav__a' ), 'bar: seven sections' );
TK_T::eq( 1, substr_count( $bar, 'aria-current="page" >' ) + substr_count( $bar, '" aria-current="page">' ), 'bar: one current section' );
TK_T::ok( false !== strpos( $bar, '<li aria-current="page">אילן &lt;ישועה&gt;</li>' ) && false !== strpos( $bar, '>ראשי</a>' ), 'crumbs: home first, current page last and escaped' );

// --- stages
$st = TK_Render_Nav::stages( $ws27 );
TK_T::eq( array( 'indictment', 'prosecution', 'defendant', 'defense', 'verdict' ), array_column( $st, 'key' ), 'stages: five in trial order' );
TK_T::eq( array( 'done', 'done', 'done', 'now', 'later' ), array_column( $st, 'state' ), 'stages: the last one with testimony is now; the verdict is later' );
TK_T::eq( '2021-04-05', $st[1]['from'], 'stages: prosecution starts with its first witness' );
TK_T::eq( '2026-01-04', $st[3]['from'], 'stages: defence witnesses start after the defendant began' );
$sh = TK_Render_Nav::stages_html( $ws27, '2026-09-22' );
TK_T::ok( 1 === substr_count( $sh, 'aria-current="step"' ) && false !== strpos( $sh, '22.9.2026' ), 'stages html: one current step and the as-of date' );
TK_T::eq( 'prosecution', TK_Render_Nav::witness_stage( $ws27[1], $ws27 ), 'stage of a witness without a side: by date, before the defendant' );
TK_T::eq( 'other', TK_Render_Nav::witness_stage( $ws27[4], $ws27 ), 'a witness without a side after the defendant began: not assigned to a side' );
TK_T::eq( 'defense', TK_Render_Nav::witness_stage( $ws27[3], $ws27 ), 'a witness a notice names for the defence' );
TK_T::eq( 'defendant', TK_Render_Nav::witness_stage( $ws27[2], $ws27 ), 'stage of the defendant' );

// --- five steps, ask examples
TK_T::eq( 5, substr_count( TK_Render_Nav::five_steps(), 'class="tk-steps__item"' ), 'five steps' );
TK_T::ok( false !== strpos( TK_Render::ask_form(), 'class="tk-ask__ex"' ), 'ask: example questions under the form' );

// --- grouped witnesses
$wg = TK_Render_Guides::witnesses_grouped( $ws27 );
TK_T::ok( strpos( $wg, 'עדי התביעה' ) < strpos( $wg, 'הנאשם' ) && strpos( $wg, 'הנאשם' ) < strpos( $wg, 'עדי ההגנה' ), 'witnesses: groups in trial order' );
TK_T::ok( false !== strpos( $wg, 'עוד 1 עדים שהעידו יום אחד' ) || false !== strpos( $wg, 'עוד 1 ' ), 'witnesses: one-day witnesses folded' );
TK_T::ok( false !== strpos( $wg, 'data-cases="4000"' ) && 4 === substr_count( $wg, 'class="tk-filter__b' ), 'witnesses: case filter buttons and data for them' );
$kw = TK_Render_Guides::key_witnesses( $ws27, 2 );
TK_T::ok( strpos( $kw, 'בנימין נתניהו' ) < strpos( $kw, 'אילן ישועה' ) && false === strpos( $kw, 'רונית מנדלבוים' ), 'key witnesses: most days first, limited' );

// --- layered witness page
$tests = array();
for ( $i = 0; $i < 5; $i++ ) {
	$tests[] = array( 'text' => 'נקודה ' . $i, 'citation_ids' => array() );
}
$hs = array();
foreach ( array( '2021-04-05', '2021-04-07', '2021-05-10' ) as $d ) {
	$hs[] = array( 'id' => 'hr_' . str_repeat( substr( $d, -1 ), 26 ), 'hearing_date' => $d, 'digest_sentences' => array( array( 'text' => 'א ' . $d, 'citation_ids' => array() ), array( 'text' => 'ב ' . $d, 'citation_ids' => array() ) ) );
}
$wp = TK_Render_Guides::witness_page(
	array( 'slug' => 'w_346fdfeda0', 'name' => 'אילן ישועה', 'label' => null, 'side' => 'prosecution', 'cases' => array( '4000' ), 'citations' => array(), 'notable_exchanges' => array(), 'appearances' => array(),
		'blocks' => array( array( 'block' => 'testimony', 'items' => $tests ) ), 'hearings' => $hs ),
	$ws27
);
TK_T::ok( false !== strpos( $wp, 'עוד 2 נקודות מהעדות' ), 'witness page: first three points, the rest folded' );
TK_T::ok( 2 === substr_count( $wp, 'class="tk-fold tk-month"' ) && 1 === substr_count( $wp, 'tk-month" open' ), 'witness page: days by month, the first month open' );
TK_T::ok( false !== strpos( $wp, 'העד הבא' ) && false !== strpos( $wp, 'w_d1dc28ccdd' ), 'witness page: next witness of the same stage' );
TK_T::ok( false !== strpos( $wp, 'class="tk-crumbs"' ) && false !== strpos( $wp, 'class="tk-kicker">עדי התביעה<' ), 'witness page: breadcrumbs and stage kicker' );

// --- hearing neighbours
$evs = array(
	array( 'id' => 'hr_' . str_repeat( 'a', 26 ), 'kind' => 'hearing', 'date' => '2021-01-01' ),
	array( 'id' => 'sv_' . str_repeat( 'b', 26 ), 'kind' => 'decision', 'date' => '2021-01-02' ),
	array( 'id' => 'hr_' . str_repeat( 'c', 26 ), 'kind' => 'hearing', 'date' => '2021-01-03' ),
	array( 'id' => 'hr_' . str_repeat( 'd', 26 ), 'kind' => 'hearing', 'date' => '2021-01-05' ),
);
$nb = TK_Guides::neighbors_in( $evs, 'hr_' . str_repeat( 'c', 26 ) );
TK_T::ok( 'hr_' . str_repeat( 'a', 26 ) === $nb['prev']['id'] && 'hr_' . str_repeat( 'd', 26 ) === $nb['next']['id'], 'hearing: previous and next hearing, documents skipped' );
TK_T::ok( false !== strpos( TK_Render_Guides::hearing_pager( $nb ), 'הדיון הבא' ), 'hearing: pager' );
TK_T::eq( '', TK_Render_Guides::hearing_pager( array() ), 'hearing: no pager without neighbours' );

// --- documents page
$docs = array();
foreach ( array( array( 'decision', '2026-08-09', 'substantive', 'פסילת חומרים מהטלפון' ), array( 'motion', '2026-08-01', 'procedural', 'ארכה' ), array( 'decision', '2021-03-01', 'substantive', 'חסיון' ) ) as $i => $x ) {
	$docs[] = array( 'source_version_id' => 'sv_' . str_repeat( (string) $i, 26 ), 'title' => $x[3], 'display_title' => $x[3], 'source_type' => $x[0], 'document_date' => $x[1], 'page_count' => 2,
		'significance' => $x[2], 'brief' => array( 'title' => $x[3], 'summary' => 'תקציר ' . $x[3], 'significance' => $x[2] ) );
}
$dp = TK_Render_Guides::documents_page( $docs, array(), 'https://site.test/trial/documents/' );
TK_T::ok( false !== strpos( $dp, '2 מסמכים' ) && false !== strpos( $dp, 'ועוד 1 פרוצדורליים' ), 'documents: procedural hidden by default and counted' );
$dp = TK_Render_Guides::documents_page( $docs, array( 'type' => 'decision', 'year' => '2021' ), 'https://site.test/trial/documents/' );
TK_T::ok( false !== strpos( $dp, 'מסמך אחד' ) && false !== strpos( $dp, 'חסיון' ) && false === strpos( $dp, 'פסילת חומרים' ), 'documents: type and year filters' );
$dp = TK_Render_Guides::documents_page( $docs, array( 'q' => 'טלפון', 'all' => true ), 'https://site.test/trial/documents/' );
TK_T::ok( false !== strpos( $dp, 'מסמך אחד' ) && false !== strpos( $dp, 'value="טלפון"' ) && false !== strpos( $dp, 'ניקוי' ), 'documents: words search, reset link' );
