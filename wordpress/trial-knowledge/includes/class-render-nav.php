<?php
/**
 * Wayfinding for readers who do not know the case (2.7):
 * one site bar on every page, breadcrumbs, "where the trial stands" as stages,
 * the criminal trial in five steps, and example questions for "שאלו".
 * Pure functions of API data, so they are tested without WordPress.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Render_Nav {

	/** Bar items: key → label. URLs come from urls(). */
	const ITEMS = array(
		'home'      => 'התחלה',
		'cases'     => 'התיקים',
		'witnesses' => 'עדים',
		'timeline'  => 'ציר הזמן',
		'documents' => 'מסמכים',
		'glossary'  => 'מילון',
		'ask'       => 'שאלו',
	);

	/** Questions the archive answers well (each answer is cached, so a click on an example costs nothing new). */
	const ASK_EXAMPLES = array(
		'מה טוען כתב האישום בתיק 4000?',
		'מה העיד אילן ישועה על הפניות של שאול אלוביץ\'?',
		'מה אמר ארנון מילצ\'ן על הסיגרים?',
		'מה החליט בית המשפט על מספר ימי הדיון בשבוע?',
	);

	public static function urls() {
		$home = home_url( '/' );
		return array(
			'home'      => $home,
			'cases'     => $home . '#tk-cases',
			'witnesses' => TK_Public_Pages::section_url( 'witnesses' ),
			'timeline'  => TK_Public_Pages::section_url( 'timeline' ),
			'documents' => TK_Public_Pages::section_url( 'documents' ),
			'glossary'  => TK_Public_Pages::section_url( 'glossary' ),
			'ask'       => $home . '#tk-ask',
		);
	}

	/**
	 * Site bar + breadcrumbs.
	 *
	 * @param string $active ITEMS key of the current section ('' for none).
	 * @param array  $crumbs list of array( label, url ) after "ראשי"; the last one is the current page (url ignored).
	 */
	public static function bar( $active = '', array $crumbs = array() ) {
		$urls = self::urls();
		$out  = '<nav class="tk-subnav" aria-label="' . esc_attr__( 'המאגר', 'trial-knowledge' ) . '" dir="rtl" lang="he"><ul class="tk-subnav__list">';
		foreach ( self::ITEMS as $k => $label ) {
			$cur  = $k === $active;
			$out .= '<li><a class="tk-subnav__a' . ( $cur ? ' is-current' : '' ) . '" href="' . esc_url( $urls[ $k ] ) . '"' . ( $cur ? ' aria-current="page"' : '' ) . '>' . esc_html( $label ) . '</a></li>';
		}
		$out .= '</ul></nav>';
		if ( $crumbs ) {
			$out .= self::crumbs( $crumbs );
		}
		return $out;
	}

	public static function crumbs( array $crumbs ) {
		$out  = '<nav class="tk-crumbs" aria-label="' . esc_attr__( 'מיקום באתר', 'trial-knowledge' ) . '" dir="rtl" lang="he"><ol>';
		$out .= '<li><a href="' . esc_url( home_url( '/' ) ) . '">' . esc_html__( 'ראשי', 'trial-knowledge' ) . '</a></li>';
		$last = count( $crumbs ) - 1;
		foreach ( array_values( $crumbs ) as $i => $c ) {
			$label = (string) ( $c[0] ?? '' );
			$url   = (string) ( $c[1] ?? '' );
			$out  .= $i === $last || '' === $url ? '<li aria-current="page">' . esc_html( $label ) . '</li>' : '<li><a href="' . esc_url( $url ) . '">' . esc_html( $label ) . '</a></li>';
		}
		return $out . '</ol></nav>';
	}

	// ------------------------------------------------------------------ stages

	/** Is this witness the defendant who testified (label "נאשם 1")? */
	public static function is_defendant( array $w ) {
		return 0 === strpos( (string) ( $w['label'] ?? '' ), 'נאשם' );
	}

	/**
	 * Stages of the trial from the published record: indictment, prosecution witnesses, the defendant's testimony,
	 * further defence witnesses, closing and verdict. A stage counts as started when a witness of it testified.
	 *
	 * @param array $ws /v2/guide witnesses.
	 * @return array list of array( key, label, from, to, state: done|now|later, note )
	 */
	public static function stages( array $ws ) {
		$def = null;
		foreach ( $ws as $w ) {
			if ( self::is_defendant( $w ) && ! empty( $w['first_date'] ) ) {
				$def = $w;
				break;
			}
		}
		$pros_from = $pros_to = $dw_from = $dw_to = '';
		foreach ( $ws as $w ) {
			$f = (string) ( $w['first_date'] ?? '' );
			$l = (string) ( $w['last_date'] ?? $f );
			if ( '' === $f || self::is_defendant( $w ) ) {
				continue;
			}
			$stage = self::witness_stage( $w, $ws );
			if ( 'prosecution' === $stage ) {
				$pros_from = '' === $pros_from || strcmp( $f, $pros_from ) < 0 ? $f : $pros_from;
				$pros_to   = strcmp( $l, $pros_to ) > 0 ? $l : $pros_to;
			} elseif ( 'defense' === $stage ) { // only witnesses a court notice names as defence witnesses
				$dw_from = '' === $dw_from || strcmp( $f, $dw_from ) < 0 ? $f : $dw_from;
				$dw_to   = strcmp( $l, $dw_to ) > 0 ? $l : $dw_to;
			}
		}
		$st = array(
			array( 'indictment', __( 'כתב האישום', 'trial-knowledge' ), '2020-01-28', '', __( 'התביעה מפרטת את טענותיה. המשפט נפתח.', 'trial-knowledge' ) ),
			array( 'prosecution', __( 'עדי התביעה', 'trial-knowledge' ), $pros_from, $pros_to, __( 'התביעה מביאה את ראיותיה; ההגנה חוקרת את עדיה בחקירה נגדית.', 'trial-knowledge' ) ),
			array( 'defendant', __( 'עדות נתניהו', 'trial-knowledge' ), $def['first_date'] ?? '', $def['last_date'] ?? '', __( 'הנאשם מעיד להגנתו ונחקר בידי התביעה.', 'trial-knowledge' ) ),
			array( 'defense', __( 'עדי ההגנה', 'trial-knowledge' ), $dw_from, $dw_to, __( 'ההגנה מביאה עדים מטעמה.', 'trial-knowledge' ) ),
			array( 'verdict', __( 'סיכומים והכרעת דין', 'trial-knowledge' ), '', '', __( 'הצדדים מסכמים, ובית המשפט מכריע: זיכוי או הרשעה.', 'trial-knowledge' ) ),
		);
		$now = 0;
		foreach ( $st as $i => $s ) {
			if ( '' !== $s[2] ) {
				$now = $i;
			}
		}
		$out = array();
		foreach ( $st as $i => $s ) {
			$out[] = array(
				'key'   => $s[0],
				'label' => $s[1],
				'from'  => $s[2],
				'to'    => $s[3],
				'state' => $i < $now ? 'done' : ( $i === $now ? 'now' : 'later' ),
				'note'  => $s[4],
			);
		}
		return $out;
	}

	/**
	 * Group of a witness: the defendant; a witness a court notice names for one side; otherwise, by date, a prosecution
	 * witness when heard before the defendant began to testify, and "other" after that (the record does not say
	 * which side called them, so the site does not guess).
	 */
	public static function witness_stage( array $w, array $ws ) {
		if ( self::is_defendant( $w ) ) {
			return 'defendant';
		}
		if ( in_array( $w['side'] ?? '', array( 'prosecution', 'defense' ), true ) ) {
			return $w['side'];
		}
		$def = '';
		foreach ( $ws as $x ) {
			if ( self::is_defendant( $x ) && ! empty( $x['first_date'] ) ) {
				$def = $x['first_date'];
				break;
			}
		}
		return ( '' === $def || strcmp( (string) ( $w['first_date'] ?? '' ), $def ) < 0 ) ? 'prosecution' : 'other';
	}

	public static function stages_html( array $ws, $latest_date = '' ) {
		$out = '<ol class="tk-stages" dir="rtl" lang="he">';
		foreach ( self::stages( $ws ) as $s ) {
			$when = '';
			if ( 'indictment' === $s['key'] ) {
				$when = __( 'ינואר 2020', 'trial-knowledge' );
			} elseif ( $s['from'] ) {
				$when = TK_Render_Guides::fmt_date( $s['from'], 'month' ) . ( 'now' === $s['state'] ? ' – ' . __( 'היום', 'trial-knowledge' ) : ( $s['to'] && substr( $s['to'], 0, 7 ) !== substr( $s['from'], 0, 7 ) ? ' – ' . TK_Render_Guides::fmt_date( $s['to'], 'month' ) : '' ) );
			}
			$state = array( 'done' => __( 'הסתיים', 'trial-knowledge' ), 'now' => __( 'עכשיו', 'trial-knowledge' ), 'later' => __( 'טרם החל', 'trial-knowledge' ) )[ $s['state'] ];
			$out  .= '<li class="tk-stage tk-stage--' . esc_attr( $s['state'] ) . '"' . ( 'now' === $s['state'] ? ' aria-current="step"' : '' ) . '>' .
				'<span class="tk-stage__dot" aria-hidden="true"></span><span class="tk-stage__label">' . esc_html( $s['label'] ) . '</span>' .
				'<span class="tk-stage__when">' . esc_html( $when ? $when : $state ) . '</span>' .
				'<span class="screen-reader-text"> (' . esc_html( $state ) . ')</span>' .
				'<span class="tk-stage__note">' . esc_html( $s['note'] ) . '</span></li>';
		}
		$out .= '</ol>';
		if ( $latest_date ) {
			$out .= '<p class="tk-stages__asof tk-muted">' . esc_html( sprintf( __( 'לפי הפרוטוקולים שפורסמו, עד הדיון מיום %s. הדיונים עדיין נמשכים; סדר העדים לא תמיד רציף.', 'trial-knowledge' ), TK_Render_Guides::fmt_date( $latest_date ) ) ) . '</p>';
		}
		return $out;
	}

	// ------------------------------------------------------------------ five steps

	public static function five_steps() {
		$steps = array(
			array( __( 'חקירה', 'trial-knowledge' ), __( 'המשטרה חוקרת, והפרקליטות מחליטה אם יש די ראיות כדי להעמיד לדין.', 'trial-knowledge' ) ),
			array( __( 'כתב אישום', 'trial-knowledge' ), __( 'התביעה מגישה כתב אישום: אלה טענות שלה, לא קביעות. הנאשם בחזקת חפות.', 'trial-knowledge' ) ),
			array( __( 'פרשת התביעה', 'trial-knowledge' ), __( 'עדי התביעה מעידים. קודם התביעה שואלת (חקירה ראשית), ואחר כך ההגנה (חקירה נגדית).', 'trial-knowledge' ) ),
			array( __( 'פרשת ההגנה', 'trial-knowledge' ), __( 'הנאשם ועדי ההגנה מעידים. ההגנה באה אחרי התביעה כי חובת ההוכחה מוטלת על התביעה.', 'trial-knowledge' ) ),
			array( __( 'סיכומים והכרעת דין', 'trial-knowledge' ), __( 'הצדדים מסכמים, ובית המשפט מכריע אם האשמה הוכחה מעבר לספק סביר: זיכוי או הרשעה. על הכרעת הדין אפשר לערער.', 'trial-knowledge' ) ),
		);
		$out = '<ol class="tk-steps" dir="rtl" lang="he">';
		foreach ( $steps as $i => $s ) {
			$out .= '<li class="tk-steps__item"><span class="tk-steps__n" aria-hidden="true">' . ( $i + 1 ) . '</span><strong class="tk-steps__t">' . esc_html( $s[0] ) . '</strong> <span class="tk-steps__d tk-glossable">' . esc_html( $s[1] ) . '</span></li>';
		}
		return $out . '</ol>';
	}

	// ------------------------------------------------------------------ ask examples

	public static function ask_examples() {
		$out = '<div class="tk-ask__examples"><span class="tk-muted">' . esc_html__( 'למשל:', 'trial-knowledge' ) . '</span> ';
		foreach ( self::ASK_EXAMPLES as $q ) {
			$out .= '<button type="button" class="tk-ask__ex" data-q="' . esc_attr( $q ) . '">' . esc_html( $q ) . '</button> ';
		}
		return $out . '</div>';
	}
}
