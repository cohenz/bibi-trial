<?php
/**
 * "315 האירועים" (/{slug}/315/, 2.6): a reader's bridge to Project 315 (the315.org).
 *
 * Data: data/p315.json, extracted from Project 315's full table ("315 - full list - V3.pdf",
 * tools/p315/): for every coverage event in the appendix to the Case 4000 indictment, the
 * indictment's own description and the project's three tests (was the demand met in practice,
 * was the response exceptional, was Netanyahu involved according to the prosecution) and its
 * classification. Static: no API and no model calls.
 *
 * The page does not copy the project; it summarizes and links to it: a sieve of the three tests,
 * a 315-cell overview, events by month, the project's four lines of argument, an opposing view,
 * and the full list (filterable) with a link back to the project's explanation of each class.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_P315 {

	const SITE = 'https://www.the315.org';
	const PDF  = 'https://drive.google.com/file/d/1rDBn1twRwfQpmnvRFeBxbfaPzHIJk5TM/view';

	/** Classes in the order of the tests (the order also fixes their colors). */
	const CATS = array(
		'not_met'         => array(
			'label' => 'הדרישה לא נענתה בפועל',
			'long'  => 'הדרישה לא נענתה (בפועל)',
			'about' => 'לפי בדיקת הפרויקט, מה שנדרש לא קרה: כתבה שנדרש להסיר נשארה באתר, או ידיעה שנדרש לפרסם לא עלתה, או שעלתה בנוסח אחר.',
			'url'   => '/examples-1',
		),
		'not_exceptional' => array(
			'label' => 'אם נענתה, לא באופן חריג',
			'long'  => 'ההיענות (אם הייתה) לא חריגה',
			'about' => 'הפרסום עלה, אבל כמו בכל אתר חדשות: הודעת דוברות שנשלחה לכל כלי התקשורת, ידיעה שפורסמה גם באתרים אחרים, או תגובה שגרתית לפרסום שגוי.',
			'url'   => '/examples-2',
		),
		'not_involved'    => array(
			'label' => 'נתניהו לא מעורב, לפי התביעה',
			'long'  => 'גם אם נענה וחריג, נתניהו לא מעורב בדרישה (על פי התביעה)',
			'about' => 'הדרישה נענתה וההיענות חריגה, אבל כתב האישום עצמו אינו מייחס לנתניהו מעורבות בדרישה.',
			'url'   => '/list',
		),
		'insufficient'    => array(
			'label' => 'אין די פרטים כדי לקבוע',
			'long'  => 'לא סופקו מספיק פרטים בכתב האישום כדי לקבוע',
			'about' => 'התיאור בכתב האישום חסר מכדי לבדוק מה פורסם ואם הדרישה נענתה.',
			'url'   => '/list',
		),
		'exceptional'     => array(
			'label' => 'היענות חריגה לדרישות סיקור',
			'long'  => 'היענות חריגה לדרישות סיקור',
			'about' => 'האירועים שעומדים בשלושת המבחנים: הדרישה נענתה, ההיענות חריגה, ונתניהו מעורב לפי התביעה.',
			'url'   => '/list',
		),
	);

	/** The project's four lines of argument (the315.org/examples), summarized. */
	const ARGUMENTS = array(
		array( 'אירועים שלא קרו', 'ב־136 אירועים, לפי הפרויקט, התגובה שהתביעה מתארת לא התרחשה: כתבות ש"הוסרו" עדיין באוויר, וכתבות ש"עלו לפי דרישה" לא עלו, או שעלתה במקומן כתבה שלילית.', '/examples-1' ),
		array( 'אירועים שאינם חריגים', 'רוב האירועים שבהם הייתה היענות הם פרסומים שגרתיים: הודעות דוברות שנשלחו לכל כלי התקשורת והתפרסמו באתרים רבים, או תיקון של ידיעה שגויה. אם כולם פרסמו, וואלה לא נענה באופן חריג.', '/examples-2' ),
		array( 'לפנק את היריבים', 'באותן שנים וואלה פרסם גם פרסומים אוהדים במיוחד ליריביו הפוליטיים של נתניהו, בעיקר לפני בחירות. לטענת הפרויקט, אתר שמפנק את כולם אינו מעניק טובת הנאה מיוחדת לאחד.', '/examples-3' ),
		array( 'סיקור שלילי ועוין', 'באותה תקופה פורסמו בוואלה גם כתבות שליליות ועוינות במיוחד כלפי נתניהו. לטענת הפרויקט, התמונה הכוללת אינה של סיקור אוהד, ולכן אין כאן שוחד.', '/examples-4' ),
	);

	/** Election days inside the period (marked on the monthly chart). */
	const ELECTIONS = array(
		'2013-01' => 'בחירות לכנסת ה־19 (22.1.2013)',
		'2015-03' => 'בחירות לכנסת ה־20 (17.3.2015)',
	);

	private static $data = null;

	/** @return array{source: array, items: array} */
	public static function data() {
		if ( null === self::$data ) {
			$raw        = file_get_contents( TK_DIR . 'data/p315.json' ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_get_contents_file_get_contents -- local plugin file
			$d          = $raw ? json_decode( $raw, true ) : null;
			self::$data = is_array( $d ) && ! empty( $d['items'] ) ? $d : array( 'source' => array(), 'items' => array() );
		}
		return self::$data;
	}

	public static function url() {
		return TK_Public_Pages::section_url( '315' );
	}

	public static function site_url( $path = '' ) {
		return self::SITE . $path;
	}

	/** Counts used by the page and by the entry cards elsewhere. */
	public static function stats( array $items = null ) {
		$items = null === $items ? self::data()['items'] : $items;
		$s     = array(
			'total'        => count( $items ),
			'cats'         => array_fill_keys( array_keys( self::CATS ), 0 ),
			'met'          => 0,
			'met_exc'      => 0,
			'met_exc_inv'  => 0,
			'not_met'      => 0,
			'unknown'      => 0,
			'inv_no'       => 0,
			'months'       => array(),
			'years'        => array(),
		);
		foreach ( $items as $it ) {
			$c = isset( self::CATS[ $it['c'] ] ) ? $it['c'] : 'insufficient';
			++$s['cats'][ $c ];
			if ( 'y' === $it['met'] ) {
				++$s['met'];
				if ( 'y' === $it['exc'] ) {
					++$s['met_exc'];
					if ( 'y' === $it['inv'] ) {
						++$s['met_exc_inv'];
					}
				}
			} elseif ( 'n' === $it['met'] ) {
				++$s['not_met'];
			} else {
				++$s['unknown'];
			}
			if ( 'n' === $it['inv'] ) {
				++$s['inv_no'];
			}
			$m = substr( (string) $it['d'], 0, 7 );
			$y = substr( (string) $it['d'], 0, 4 );
			if ( ! isset( $s['months'][ $m ] ) ) {
				$s['months'][ $m ] = array_fill_keys( array_keys( self::CATS ), 0 );
			}
			++$s['months'][ $m ][ $c ];
			$s['years'][ $y ] = ( $s['years'][ $y ] ?? 0 ) + 1;
		}
		ksort( $s['years'] );
		return $s;
	}

	private static function pct( $n, $total ) {
		return $total ? (int) round( 100 * $n / $total ) : 0;
	}

	private static function fmt_date( $iso ) {
		return $iso ? TK_Render_Guides::fmt_date( $iso ) : '';
	}

	private static function yn( $v, $yes, $no ) {
		if ( 'y' === $v ) {
			return '<span class="tk315-yn tk315-yn--y">' . esc_html( $yes ) . '</span>';
		}
		if ( 'n' === $v ) {
			return '<span class="tk315-yn tk315-yn--n">' . esc_html( $no ) . '</span>';
		}
		if ( 'u' === $v ) {
			return '<span class="tk315-yn tk315-yn--u">' . esc_html__( 'לא ידוע', 'trial-knowledge' ) . '</span>';
		}
		return '';
	}

	/** Whole page. */
	public static function page() {
		$d     = self::data();
		$items = $d['items'];
		if ( ! $items ) {
			return TK_Render::unavailable();
		}
		$s = self::stats( $items );
		wp_enqueue_script( 'trial-knowledge-p315' );

		$out  = '<div class="tk-guide tk315" dir="rtl" lang="he">';
		$out .= '<header class="tk-head"><p class="tk-kicker">' . TK_Render_Guides::case_badge( '4000' ) . ' ' . esc_html__( 'הנספח לכתב האישום', 'trial-knowledge' ) . '</p>';
		$out .= '<h1 class="tk-head__title">' . esc_html__( '315 האירועים: מה נשאר מהם', 'trial-knowledge' ) . '</h1>';
		$out .= '<p class="tk315-lead">' . esc_html__( 'לפי כתב האישום בתיק 4000, השוחד שקיבל נתניהו הוא "היענות חריגה לדרישות סיקור" באתר וואלה. בנספח לכתב האישום מפורטים 315 אירועים כאלה. מתנדבי פרויקט 315 בדקו כל אירוע מול הארכיון של האתר ושאלו עליו שלוש שאלות. כאן מוצגות התוצאות בקצרה; ההסברים המלאים, הדוגמאות והסרטונים נמצאים באתר הפרויקט.', 'trial-knowledge' ) . '</p>';
		$out .= '<p class="tk-actions-row"><a class="tk-button" href="' . esc_url( self::site_url() ) . '" rel="noopener">' . esc_html__( 'לאתר פרויקט 315', 'trial-knowledge' ) . '</a> ' .
			'<a class="tk-button" href="#tk315-list">' . esc_html__( 'לרשימה המלאה', 'trial-knowledge' ) . '</a></p></header>';

		$out .= self::sieve( $s );
		$out .= self::overview( $items, $s );
		$out .= self::by_month( $s );
		$out .= self::arguments( $s );
		$out .= self::other_view();
		$out .= self::list_section( $items, $s );
		$out .= '<p class="tk-muted tk-small tk315-credit">' . esc_html__( 'מקור הנתונים: הטבלה המלאה של פרויקט 315 (גרסה 3), שבה תיאור כל אירוע מובא כלשונו בנספח לכתב האישום, לצד בדיקת הפרויקט. הסיווג הוא של הפרויקט; הניסוח המקוצר והתרשימים הם שלנו.', 'trial-knowledge' ) .
			' <a href="' . esc_url( self::PDF ) . '" rel="noopener">' . esc_html__( 'הטבלה המקורית', 'trial-knowledge' ) . '</a></p>';
		return $out . '</div>';
	}

	/** Three tests as a narrowing sieve: 315 → met → exceptional → Netanyahu involved. */
	private static function sieve( array $s ) {
		$t     = max( 1, $s['total'] );
		$steps = array(
			array( $s['total'], __( 'אירועים בנספח לכתב האישום', 'trial-knowledge' ), '', '' ),
			array( $s['met'], __( 'הדרישה נענתה בפועל', 'trial-knowledge' ), __( 'השאלה הראשונה: האם מה שנדרש אכן פורסם או הוסר?', 'trial-knowledge' ),
				sprintf( __( '%1$d לא נענו, ועל %2$d אין די פרטים', 'trial-knowledge' ), $s['not_met'], $s['unknown'] ) ),
			array( $s['met_exc'], __( 'ההיענות הייתה חריגה', 'trial-knowledge' ), __( 'השאלה השנייה: האם וואלה נהג אחרת מאשר כלפי כל דרישה או כל כלי תקשורת?', 'trial-knowledge' ),
				sprintf( __( '%d נענו באופן שגרתי', 'trial-knowledge' ), $s['met'] - $s['met_exc'] ) ),
			array( $s['met_exc_inv'], __( 'ונתניהו מעורב בדרישה, לפי התביעה', 'trial-knowledge' ), __( 'השאלה השלישית: האם כתב האישום עצמו מייחס את הדרישה לנתניהו?', 'trial-knowledge' ),
				sprintf( __( '%d בלי מעורבות של נתניהו', 'trial-knowledge' ), $s['met_exc'] - $s['met_exc_inv'] ) ),
		);
		$out = '<section class="tk-sec tk315-sieve" aria-labelledby="tk315-sieve-h"><h2 class="tk-sec__h" id="tk315-sieve-h">' . esc_html__( 'שלוש שאלות, ומה נשאר', 'trial-knowledge' ) . '</h2>';
		$out .= '<ol class="tk315-steps">';
		foreach ( $steps as $i => $st ) {
			$w    = max( 1.2, 100 * $st[0] / $t );
			$out .= '<li class="tk315-step tk315-step--' . (int) $i . '">';
			if ( $st[2] ) {
				$out .= '<p class="tk315-step__q">' . esc_html( $st[2] ) . '</p>';
			}
			$out .= '<div class="tk315-step__row"><span class="tk315-step__bar" style="--w:' . esc_attr( number_format( $w, 2, '.', '' ) ) . '%"></span>' .
				'<span class="tk315-step__n">' . (int) $st[0] . '</span><span class="tk315-step__label">' . esc_html( $st[1] ) . '</span></div>';
			if ( $st[3] ) {
				$out .= '<p class="tk315-step__out">' . esc_html( $st[3] ) . '</p>';
			}
			$out .= '</li>';
		}
		$out .= '</ol>';
		$out .= '<p class="tk315-hero"><strong>' . esc_html( sprintf( __( '%1$d מתוך %2$d', 'trial-knowledge' ), $s['met_exc_inv'], $s['total'] ) ) . '</strong> ' .
			esc_html( sprintf( __( '(%s%%) עומדים בשלושת המבחנים, לפי בדיקת הפרויקט.', 'trial-knowledge' ), self::pct_str( $s['met_exc_inv'], $s['total'] ) ) ) . '</p>';
		$out .= '<p class="tk-notice tk-notice--soft tk315-note">' . esc_html( sprintf( __( 'נתון שעולה מכתב האישום עצמו: ב־%1$d מתוך %2$d האירועים, התיאור בנספח אינו מייחס לנתניהו מעורבות בדרישה.', 'trial-knowledge' ), $s['inv_no'], $s['total'] ) ) . '</p>';
		return $out . '</section>';
	}

	private static function pct_str( $n, $t ) {
		$p = $t ? 100 * $n / $t : 0;
		return $p < 10 ? rtrim( rtrim( number_format( $p, 1, '.', '' ), '0' ), '.' ) : (string) (int) round( $p );
	}

	/** 315 cells, one per event, grouped by class; the legend carries counts (and is the text alternative). */
	private static function overview( array $items, array $s ) {
		$order = array_flip( array_keys( self::CATS ) );
		usort(
			$items,
			static function ( $a, $b ) use ( $order ) {
				return array( $order[ $a['c'] ] ?? 9, $a['n'] ) <=> array( $order[ $b['c'] ] ?? 9, $b['n'] );
			}
		);
		$out  = '<section class="tk-sec tk315-overview" aria-labelledby="tk315-ov-h"><h2 class="tk-sec__h" id="tk315-ov-h">' . esc_html__( 'כל 315 האירועים במבט אחד', 'trial-knowledge' ) . '</h2>';
		$out .= '<p class="tk-sec__note">' . esc_html__( 'כל ריבוע הוא אירוע אחד מהנספח, צבוע לפי סיווג הפרויקט. מעבר עם העכבר מציג את האירוע, ולחיצה מובילה אליו ברשימה.', 'trial-knowledge' ) . '</p>';
		$out .= self::legend( $s, true );
		$out .= '<div class="tk315-waffle" aria-hidden="true">';
		foreach ( $items as $it ) {
			$out .= '<a class="tk315-cell tk315-c--' . esc_attr( $it['c'] ) . '" href="#p315-' . (int) $it['n'] . '" tabindex="-1" data-n="' . (int) $it['n'] . '"></a>';
		}
		return $out . '</div></section>';
	}

	/** Legend: swatch, label, count and share; buttons filter the list when JS is on. */
	private static function legend( array $s, $filter ) {
		$out = '<ul class="tk315-legend">';
		foreach ( self::CATS as $k => $c ) {
			$n    = $s['cats'][ $k ];
			$body = '<span class="tk315-sw tk315-c--' . esc_attr( $k ) . '"></span><span class="tk315-legend__label">' . esc_html( $c['label'] ) . '</span>' .
				'<span class="tk315-legend__n">' . (int) $n . '</span><span class="tk315-legend__p">' . esc_html( self::pct_str( $n, $s['total'] ) ) . '%</span>';
			$out .= '<li>' . ( $filter ? '<a class="tk315-legend__a" href="#tk315-list" data-tk315-cat="' . esc_attr( $k ) . '">' . $body . '</a>' : $body ) . '</li>';
		}
		return $out . '</ul>';
	}

	/** Events by month (stacked by class, one count axis), elections marked. Earliest month on the right. */
	private static function by_month( array $s ) {
		$months = array();
		for ( $y = 2013; $y <= 2016; $y++ ) {
			for ( $m = 1; $m <= 12; $m++ ) {
				$months[] = sprintf( '%04d-%02d', $y, $m );
			}
		}
		$max = 1;
		foreach ( $s['months'] as $row ) {
			$max = max( $max, array_sum( $row ) );
		}
		$scale = (int) ( ceil( $max / 10 ) * 10 );
		$out   = '<section class="tk-sec tk315-months" aria-labelledby="tk315-mo-h"><h2 class="tk-sec__h" id="tk315-mo-h">' . esc_html__( 'האירועים לאורך הזמן', 'trial-knowledge' ) . '</h2>';
		$out  .= '<p class="tk-sec__note">' . esc_html__( 'מספר האירועים בכל חודש, 2013–2016. השיאים סמוכים לבחירות של 2015 ולסוף 2016.', 'trial-knowledge' ) . '</p>';
		$out  .= self::legend( $s, false );
		$out  .= '<div class="tk315-chart" style="--max:' . (int) $scale . '"><div class="tk315-grid" aria-hidden="true">';
		foreach ( array( $scale, $scale / 2, 0 ) as $g ) {
			$out .= '<span style="--v:' . esc_attr( (string) $g ) . '">' . (int) $g . '</span>';
		}
		$out .= '</div><ol class="tk315-cols">';
		foreach ( $months as $mo ) {
			$row   = $s['months'][ $mo ] ?? array();
			$total = array_sum( $row );
			$label = TK_Render_Guides::fmt_date( $mo . '-01', 'month' );
			$tip   = $label . ': ' . sprintf( _n( 'אירוע אחד', '%d אירועים', $total, 'trial-knowledge' ), $total );
			foreach ( self::CATS as $k => $c ) {
				if ( ! empty( $row[ $k ] ) ) {
					$tip .= "\n" . $c['label'] . ': ' . (int) $row[ $k ];
				}
			}
			$el   = self::ELECTIONS[ $mo ] ?? '';
			$out .= '<li class="tk315-col' . ( $el ? ' tk315-col--election' : '' ) . ( '01' === substr( $mo, 5 ) ? ' tk315-col--year' : '' ) . '" data-tip="' . esc_attr( $tip . ( $el ? "\n" . $el : '' ) ) . '" tabindex="0" aria-label="' . esc_attr( str_replace( "\n", ', ', $tip ) ) . '">';
			$out .= '<span class="tk315-stack">';
			foreach ( self::CATS as $k => $c ) {
				if ( ! empty( $row[ $k ] ) ) {
					$out .= '<span class="tk315-seg tk315-c--' . esc_attr( $k ) . '" style="--v:' . (int) $row[ $k ] . '"></span>';
				}
			}
			$out .= '</span>';
			if ( '01' === substr( $mo, 5 ) ) {
				$out .= '<span class="tk315-col__year">' . esc_html( substr( $mo, 0, 4 ) ) . '</span>';
			}
			if ( $el ) {
				$out .= '<span class="tk315-col__el" title="' . esc_attr( $el ) . '">' . esc_html__( 'בחירות', 'trial-knowledge' ) . '</span>';
			}
			$out .= '</li>';
		}
		$out .= '</ol></div>';
		$years = array();
		foreach ( $s['years'] as $y => $n ) {
			$years[] = '<span class="tk315-year"><bdi>' . esc_html( (string) $y ) . '</bdi> <strong>' . (int) $n . '</strong></span>';
		}
		$out .= '<p class="tk-muted tk-small tk315-years">' . esc_html__( 'לפי שנה:', 'trial-knowledge' ) . ' ' . implode( ' ', $years ) . '</p>';
		return $out . '</section>';
	}

	private static function arguments( array $s ) {
		$out = '<section class="tk-sec tk315-args" aria-labelledby="tk315-args-h"><h2 class="tk-sec__h" id="tk315-args-h">' . esc_html__( 'ארבעה קווי טיעון של הפרויקט', 'trial-knowledge' ) . '</h2><ul class="tk315-cards">';
		foreach ( self::ARGUMENTS as $i => $a ) {
			$out .= '<li class="tk315-card"><p class="tk315-card__no">' . (int) ( $i + 1 ) . '</p><h3 class="tk315-card__h">' . esc_html( $a[0] ) . '</h3><p>' . esc_html( $a[1] ) . '</p>' .
				'<p><a href="' . esc_url( self::site_url( $a[2] ) ) . '" rel="noopener">' . esc_html__( 'הדוגמאות באתר 315', 'trial-knowledge' ) . ' ←</a></p></li>';
		}
		return $out . '</ul></section>';
	}

	/** The opposing reading, so the page shows both sides of the legal question. */
	private static function other_view() {
		return '<section class="tk-sec tk315-other" aria-labelledby="tk315-other-h"><h2 class="tk-sec__h" id="tk315-other-h">' . esc_html__( 'מה אומרים המבקרים?', 'trial-knowledge' ) . '</h2>' .
			'<p>' . esc_html__( 'יש המבקרים את שיטת הבדיקה של הפרויקט. לטענתם, "היענות חריגה לדרישות סיקור" בכתב האישום מתארת את התנהלות בני הזוג אלוביץ\' מול עורכי האתר, ולא את אופי הפרסום עצמו; ולכן גם ידיעה שפורסמה בכל כלי התקשורת יכולה להיות חלק מהיענות חריגה לדרישות סיקור, אם הדרך שבה הגיעה לאתר הייתה חריגה. השאלה הזאת תוכרע בבית המשפט.', 'trial-knowledge' ) . '</p>' .
			'<p><a href="https://en.wikipedia.org/wiki/Project_315" rel="noopener">' . esc_html__( 'על הפרויקט והביקורת עליו (ויקיפדיה, באנגלית)', 'trial-knowledge' ) . '</a></p></section>';
	}

	/** Full list: server-rendered (works without JS); the script adds filters, search and paging. */
	private static function list_section( array $items, array $s ) {
		$out  = '<section class="tk-sec tk315-list" id="tk315-list" aria-labelledby="tk315-list-h"><h2 class="tk-sec__h" id="tk315-list-h">' . esc_html__( 'הרשימה המלאה', 'trial-knowledge' ) . '</h2>';
		$out .= '<p class="tk-sec__note">' . esc_html__( 'תיאור כל אירוע כלשונו בנספח לכתב האישום, ולצדו בדיקת הפרויקט.', 'trial-knowledge' ) . '</p>';
		$out .= '<form class="tk315-filters" hidden role="search" onsubmit="return false"><div class="tk315-chips" role="group" aria-label="' . esc_attr__( 'סינון לפי סיווג', 'trial-knowledge' ) . '">' .
			'<button type="button" class="tk315-chip is-on" data-tk315-cat="">' . esc_html__( 'הכול', 'trial-knowledge' ) . ' <span>' . (int) $s['total'] . '</span></button>';
		foreach ( self::CATS as $k => $c ) {
			$out .= '<button type="button" class="tk315-chip" data-tk315-cat="' . esc_attr( $k ) . '"><span class="tk315-sw tk315-c--' . esc_attr( $k ) . '"></span>' . esc_html( $c['label'] ) . ' <span>' . (int) $s['cats'][ $k ] . '</span></button>';
		}
		$out .= '</div><div class="tk315-fields"><label>' . esc_html__( 'שנה', 'trial-knowledge' ) . ' <select data-tk315-year><option value="">' . esc_html__( 'כל השנים', 'trial-knowledge' ) . '</option>';
		foreach ( array_keys( $s['years'] ) as $y ) {
			$out .= '<option value="' . esc_attr( $y ) . '">' . esc_html( $y ) . '</option>';
		}
		$out .= '</select></label><label class="tk315-search">' . esc_html__( 'חיפוש', 'trial-knowledge' ) . ' <input type="search" data-tk315-q placeholder="' . esc_attr__( 'שם, נושא או מספר אירוע', 'trial-knowledge' ) . '"></label></div>' .
			'<p class="tk315-count" aria-live="polite"></p></form>';
		$out .= '<ol class="tk315-items">';
		foreach ( $items as $it ) {
			$c    = self::CATS[ $it['c'] ] ?? self::CATS['insufficient'];
			$date = ! empty( $it['d2'] ) ? TK_Render::nrange( self::fmt_date( $it['d'] ), self::fmt_date( $it['d2'] ) ) : self::fmt_date( $it['d'] );
			$out .= '<li class="tk315-item" id="p315-' . (int) $it['n'] . '" data-c="' . esc_attr( $it['c'] ) . '" data-y="' . esc_attr( substr( (string) $it['d'], 0, 4 ) ) . '">';
			$out .= '<p class="tk315-item__head"><span class="tk315-item__n">' . esc_html( sprintf( __( 'אירוע %d', 'trial-knowledge' ), $it['n'] ) ) . '</span>' .
				'<time datetime="' . esc_attr( (string) $it['d'] ) . '">' . esc_html( $date ) . '</time>' .
				'<span class="tk315-verdict tk315-c--' . esc_attr( $it['c'] ) . '">' . esc_html( $c['label'] ) . '</span></p>';
			$out .= '<p class="tk315-item__demand">' . esc_html( $it['demand'] ) . '</p>';
			if ( '' !== (string) $it['rest'] ) {
				$out .= '<p class="tk315-item__rest">' . esc_html( $it['rest'] ) . '</p>';
			}
			$out .= '<p class="tk315-item__tests">' .
				'<span>' . esc_html__( 'נענתה בפועל:', 'trial-knowledge' ) . ' ' . self::yn( $it['met'], 'כן', 'לא' ) . '</span>' .
				( '' !== $it['exc'] ? '<span>' . esc_html__( 'היענות חריגה לדרישות סיקור:', 'trial-knowledge' ) . ' ' . self::yn( $it['exc'], 'כן', 'לא' ) . '</span>' : '' ) .
				'<span>' . esc_html__( 'נתניהו מעורב לפי התביעה:', 'trial-knowledge' ) . ' ' . self::yn( $it['inv'], 'כן', 'לא' ) . '</span>' .
				'<a class="tk315-item__more" href="' . esc_url( self::site_url( $c['url'] ) ) . '" rel="noopener">' . esc_html__( 'ההסבר באתר 315', 'trial-knowledge' ) . '</a></p>';
			$out .= '</li>';
		}
		$out .= '</ol><p class="tk315-more" hidden><button type="button" class="tk-button" data-tk315-more>' . esc_html__( 'עוד אירועים', 'trial-knowledge' ) . '</button></p>';
		$out .= '<dl class="tk315-about">';
		foreach ( self::CATS as $k => $c ) {
			$out .= '<div><dt><span class="tk315-sw tk315-c--' . esc_attr( $k ) . '"></span>' . esc_html( $c['long'] ) . '</dt><dd>' . esc_html( $c['about'] ) . '</dd></div>';
		}
		return $out . '</dl></section>';
	}

	/** Small entry card for the start page and the Case 4000 page. */
	public static function entry_card() {
		$items = self::data()['items'];
		if ( ! $items ) {
			return '';
		}
		$s = self::stats( $items );
		return '<aside class="tk315-entry" dir="rtl" lang="he"><p class="tk315-entry__k">' . esc_html__( 'פרויקט 315', 'trial-knowledge' ) . '</p>' .
			'<p class="tk315-entry__big"><strong>' . (int) $s['met_exc_inv'] . '</strong> ' . esc_html( sprintf( __( 'מתוך %d', 'trial-knowledge' ), $s['total'] ) ) . '</p>' .
			'<p>' . esc_html__( 'אירועי הסיקור שבנספח לכתב האישום, שעומדים בשלושת המבחנים לפי בדיקת פרויקט 315.', 'trial-knowledge' ) . '</p>' .
			'<p><a class="tk-button" href="' . esc_url( self::url() ) . '">' . esc_html__( '315 האירועים במבט אחד', 'trial-knowledge' ) . '</a></p></aside>';
	}
}
