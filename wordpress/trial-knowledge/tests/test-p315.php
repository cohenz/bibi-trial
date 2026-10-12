<?php
/** 2.6: "315 האירועים" — data file, the three-test counts, page and entry card. */
$d = TK_P315::data();
TK_T::eq( 315, count( $d['items'] ), '315: all events in the data file' );
$s = TK_P315::stats();
TK_T::eq( array( 'not_met' => 136, 'not_exceptional' => 155, 'not_involved' => 13, 'insufficient' => 5, 'exceptional' => 6 ), $s['cats'], '315: class counts match the project' );
TK_T::eq( array( 174, 19, 6, 136, 5 ), array( $s['met'], $s['met_exc'], $s['met_exc_inv'], $s['not_met'], $s['unknown'] ), '315: the sieve 315 → 174 → 19 → 6' );
TK_T::eq( 159, $s['inv_no'], '315: events the indictment does not attribute to Netanyahu' );
TK_T::eq( 315, array_sum( $s['years'] ), '315: every event has a date' );
$ns = array_map( static function ( $i ) { return $i['n']; }, $d['items'] );
TK_T::eq( range( 1, 315 ), $ns, '315: numbered 1–315 in order' );
$p = TK_P315::page();
TK_T::eq( 315, substr_count( $p, 'class="tk315-cell ' ), '315 page: one cell per event' );
TK_T::eq( 315, substr_count( $p, '<li class="tk315-item" id="p315-' ), '315 page: full list rendered without JS' );
TK_T::eq( 48, substr_count( $p, '<li class="tk315-col' ), '315 page: 48 months 2013–2016' );
TK_T::ok( false !== strpos( $p, 'https://www.the315.org/examples-1' ) && false !== strpos( $p, 'Project_315' ), '315 page: links to the project and to the opposing view' );
TK_T::ok( false === strpos( $p, '<script' ), '315 page: no inline script' );
$e = TK_P315::entry_card();
TK_T::ok( false !== strpos( $e, '<strong>6</strong>' ) && false !== strpos( $e, '/trial/315/' ), '315 entry card: headline number and link' );
