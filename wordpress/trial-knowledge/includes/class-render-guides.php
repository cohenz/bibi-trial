<?php
/**
 * Server-side HTML for the reader entry points (2.3): start page, case page,
 * witness page, witnesses list, dual timeline, glossary and the tabbed hearing page.
 * Pure functions of API data (no fetching here) so they can be tested without WordPress.
 * All text is escaped; texts that may receive glossary tooltips carry class "tk-glossable".
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Render_Guides {

	const MONTHS = array( 1 => 'ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר' );

	const BLOCKS = array(
		'one_line'   => 'בשורה אחת',
		'overview'   => 'סקירה',
		'defendants' => 'הנאשמים',
		'alleged'    => 'מה טוען כתב האישום',
		'people'     => 'מי מעורב',
		'charges'    => 'האישומים',
		'events'     => 'ציר הזמן של התיק',
		'role'       => 'מי העד או העדה',
		'testimony'  => 'עיקרי העדות',
	);

	const KINDS = array(
		'indictment_fact' => 'לפי כתב האישום',
		'indictment'      => 'כתב אישום',
		'hearing'         => 'דיון',
		'decision'        => 'החלטה',
		'motion'          => 'בקשה',
		'response'        => 'תגובה',
		'notice'          => 'הודעה',
		'affidavit'       => 'תצהיר',
		'exhibit'         => 'מוצג',
		'other'           => 'מסמך',
	);

	const GLOSSARY_CATEGORIES = array(
		'procedure' => 'ההליך בבית המשפט',
		'evidence'  => 'ראיות ועדויות',
		'offense'   => 'עבירות',
		'people'    => 'מי ומי באולם',
		'documents' => 'מסמכים',
	);

	const TABS = array(
		'summary' => 'בקצרה',
		'qa'      => 'שאלות ותשובות מרכזיות',
		'full'    => 'הפרוטוקול המלא',
		'source'  => 'מסמך המקור',
	);

	const NEUTRAL = 'כתב אישום הוא טענות התביעה. נאשם בחזקת חפות כל עוד לא הוכרעה אשמתו.';

	// ------------------------------------------------------------------ helpers

	/**
	 * Date by precision: day → 12.3.2015, month → מרץ 2015, year → 2015.
	 *
	 * @param string $date      YYYY-MM-DD.
	 * @param string $precision day|month|year.
	 */
	public static function fmt_date( $date, $precision = 'day' ) {
		if ( ! preg_match( '/^(\d{4})-(\d{2})-(\d{2})/', (string) $date, $m ) ) {
			return (string) $date;
		}
		$y = (int) $m[1];
		$mo = (int) $m[2];
		$d = (int) $m[3];
		if ( 'year' === $precision ) {
			return (string) $y;
		}
		if ( 'month' === $precision ) {
			return ( self::MONTHS[ $mo ] ?? '' ) . ' ' . $y;
		}
		return $d . '.' . $mo . '.' . $y;
	}

	public static function time_tag( $date, $precision = 'day' ) {
		$iso = substr( (string) $date, 0, 'year' === $precision ? 4 : ( 'month' === $precision ? 7 : 10 ) );
		return '<time datetime="' . esc_attr( $iso ) . '">' . esc_html( self::fmt_date( $date, $precision ) ) . '</time>';
	}

	/** "10.5.2021–14.6.2021" or a single date. */
	public static function date_range( $from, $to ) {
		if ( ! $from ) {
			return '';
		}
		return ( ! $to || $to === $from ) ? self::fmt_date( $from ) : self::fmt_date( $from ) . '–' . self::fmt_date( $to );
	}

	/** @return array source_unit_id → citation */
	public static function cit_map( $citations ) {
		$map = array();
		foreach ( (array) $citations as $k => $c ) {
			if ( is_array( $c ) && ! empty( $c['source_unit_id'] ) ) {
				$map[ $c['source_unit_id'] ] = $c;
			} elseif ( is_array( $c ) && is_string( $k ) ) {
				$map[ $k ] = $c + array( 'source_unit_id' => $k );
			}
		}
		return $map;
	}

	/**
	 * Citation chips for an item; repeated citations of the same page collapse into one chip.
	 *
	 * @param array $ids  source unit ids.
	 * @param array $cits cit_map().
	 */
	public static function chips( $ids, array $cits ) {
		$out  = array();
		$seen = array();
		foreach ( (array) $ids as $id ) {
			if ( ! preg_match( '/^su_[0-9a-f]{26}$/', (string) $id ) ) {
				continue;
			}
			if ( isset( $cits[ $id ] ) && isset( $cits[ $id ]['page'] ) ) {
				$key = ( $cits[ $id ]['source_version_id'] ?? '' ) . '#' . (int) $cits[ $id ]['page'];
				if ( isset( $seen[ $key ] ) ) {
					continue;
				}
				$seen[ $key ] = 1;
				$out[]        = TK_Render::citation_chip( $cits[ $id ] );
			} else {
				$out[] = '<a class="tk-chip" href="' . esc_url( TK_Render::citation_url( $id ) ) . '" title="' . esc_attr__( 'המקור בתיק', 'trial-knowledge' ) . '">' . esc_html__( 'מקור', 'trial-knowledge' ) . '</a>';
			}
		}
		return $out ? ' <span class="tk-chips">' . implode( '', $out ) . '</span>' : '';
	}

	public static function case_badge( $key, $link = true ) {
		$key = preg_replace( '/[^0-9]/', '', (string) $key );
		if ( '' === $key ) {
			return '';
		}
		$label = sprintf( __( 'תיק %s', 'trial-knowledge' ), $key );
		if ( $link && TK_Guides::valid_case( $key ) ) {
			return '<a class="tk-case-badge tk-case--' . esc_attr( $key ) . '" href="' . esc_url( TK_Public_Pages::url( 'case', $key ) ) . '">' . esc_html( $label ) . '</a>';
		}
		return '<span class="tk-case-badge tk-case--' . esc_attr( $key ) . '">' . esc_html( $label ) . '</span>';
	}

	public static function case_badges( $keys, $link = true ) {
		$out = '';
		foreach ( (array) $keys as $k ) {
			$out .= self::case_badge( $k, $link ) . ' ';
		}
		return trim( $out );
	}

	/** Items of a block in a guide payload. */
	public static function block( array $guide, $name ) {
		foreach ( (array) ( $guide['blocks'] ?? array() ) as $b ) {
			if ( ( $b['block'] ?? '' ) === $name ) {
				return (array) ( $b['items'] ?? array() );
			}
		}
		return array();
	}

	/** Paragraphs (prose) for alleged/overview/testimony blocks. */
	public static function prose( array $items, array $cits ) {
		$out = '<div class="tk-prose tk-glossable">';
		foreach ( $items as $it ) {
			$label = ! empty( $it['label'] ) ? '<strong>' . esc_html( $it['label'] ) . '.</strong> ' : '';
			$out  .= '<p>' . $label . esc_html( $it['text'] ?? '' ) . self::chips( $it['citation_ids'] ?? array(), $cits ) . '</p>';
		}
		return $out . '</div>';
	}

	/** Label → text list (charges, defendants, role). */
	public static function labelled( array $items, array $cits, $class = '' ) {
		$out = '<ul class="tk-labelled tk-glossable ' . esc_attr( $class ) . '">';
		foreach ( $items as $it ) {
			$out .= '<li>' . ( ! empty( $it['label'] ) ? '<span class="tk-labelled__label">' . esc_html( $it['label'] ) . '</span> ' : '' ) .
				'<span class="tk-labelled__text">' . esc_html( $it['text'] ?? '' ) . self::chips( $it['citation_ids'] ?? array(), $cits ) . '</span></li>';
		}
		return $out . '</ul>';
	}

	public static function sentences( array $sentences, array $cits, $class = 'tk-sentences' ) {
		if ( ! $sentences ) {
			return '';
		}
		$out = '<ul class="' . esc_attr( $class ) . ' tk-glossable">';
		foreach ( $sentences as $s ) {
			$out .= '<li>' . esc_html( $s['text'] ?? '' ) . self::chips( $s['citation_ids'] ?? array(), $cits ) . '</li>';
		}
		return $out . '</ul>';
	}

	/** Witness name linked to the witness page when the slug is known. */
	public static function witness_link( $raw, array $slugs ) {
		list( $name, $label ) = TK_Guides::split_label( $raw );
		$slug                 = TK_Guides::slug_for( $raw, $slugs );
		$text                 = esc_html( $name ) . ( $label ? ' <span class="tk-badge tk-badge--label">' . esc_html( $label ) . '</span>' : '' );
		return $slug ? '<a href="' . esc_url( TK_Public_Pages::url( 'witness', $slug ) ) . '">' . $text . '</a>' : $text;
	}

	public static function section( $id, $title, $body, $extra_class = '' ) {
		return '<section class="tk-sec ' . esc_attr( $extra_class ) . '" id="' . esc_attr( $id ) . '" aria-labelledby="' . esc_attr( $id ) . '-h">' .
			'<h2 class="tk-sec__h" id="' . esc_attr( $id ) . '-h">' . esc_html( $title ) . '</h2>' . $body . '</section>';
	}

	private static function allegation_tag() {
		return '<span class="tk-tag tk-tag--allegation">' . esc_html__( 'לפי כתב האישום', 'trial-knowledge' ) . '</span>';
	}

	// ------------------------------------------------------------------ start page

	/**
	 * [tk_start] — "מתחילים כאן".
	 *
	 * @param array $g    /v2/guide.
	 * @param array $opts urls: glossary, timeline, witnesses, docs (type → url); ask_html.
	 */
	public static function start( array $g, array $opts = array() ) {
		$urls = self::entry_urls( $opts );
		$out  = '<div class="tk-guide tk-start" dir="rtl" lang="he">';

		// intro + neutrality line
		$out .= '<header class="tk-intro">';
		$out .= '<p class="tk-intro__lead tk-glossable">' . esc_html__( 'מדריך נגיש למשפט הפלילי של בנימין נתניהו (ת״פ 67104-01-20, בית המשפט המחוזי בירושלים). כל מה שכתוב כאן נשען על תיק בית המשפט: ליד כל משפט יש קישור לעמוד ולשורות במקור — בפרוטוקולים, בכתב האישום ובהחלטות.', 'trial-knowledge' ) . '</p>';
		$out .= '<p class="tk-neutral" role="note"><strong>' . esc_html( self::NEUTRAL ) . '</strong> <a href="' . esc_url( $urls['glossary'] . '#term-presumption-of-innocence' ) . '">' . esc_html__( 'מהי חזקת החפות?', 'trial-knowledge' ) . '</a></p>';
		$out .= '</header>';

		// three cases
		$by_key = array();
		foreach ( (array) ( $g['cases'] ?? array() ) as $c ) {
			$by_key[ (string) $c['key'] ] = $c;
		}
		$cards = '<p class="tk-sec__note">' . esc_html__( 'התיאורים מבוססים על כתב האישום, כלומר על טענות התביעה.', 'trial-knowledge' ) . '</p><div class="tk-cards">';
		foreach ( TK_Guides::CASE_KEYS as $key ) {
			$cards .= self::case_card( $key, $by_key[ $key ] ?? null, self::cit_map( $g['indictment']['citations'] ?? array() ) );
		}
		$out .= self::section( 'tk-cases', __( 'שלושת התיקים', 'trial-knowledge' ), $cards . '</div>' );

		// indictment overview
		if ( ! empty( $g['indictment'] ) ) {
			$out .= self::section( 'tk-indictment', __( 'כתב האישום בקצרה', 'trial-knowledge' ), self::indictment( $g['indictment'] ) );
		}

		// where the trial stands
		$out .= self::section( 'tk-status', __( 'איפה המשפט עומד', 'trial-knowledge' ), self::status( $g, $urls ) );

		// witnesses
		$ws = (array) ( $g['witnesses'] ?? array() );
		if ( $ws ) {
			$out .= self::section( 'tk-witnesses', __( 'עדים', 'trial-knowledge' ), self::witnesses_list( $ws, array( 'compact' => true ) ) . '<p><a class="tk-more" href="' . esc_url( $urls['witnesses'] ) . '">' . esc_html__( 'לכל העדים', 'trial-knowledge' ) . '</a></p>' );
		}

		// entry links
		$out .= self::section( 'tk-entries', __( 'לאן ממשיכים', 'trial-knowledge' ), self::entries( $g, $urls ) );

		if ( ! empty( $opts['ask_html'] ) ) {
			$out .= '<section class="tk-sec tk-sec--ask" id="tk-ask" aria-labelledby="tk-ask-h"><h2 class="tk-sec__h" id="tk-ask-h">' . esc_html__( 'שאלו את המאגר', 'trial-knowledge' ) . '</h2>' . $opts['ask_html'] . '</section>';
		}
		return $out . '</div>';
	}

	/** Default URLs of the entry points (virtual routes and the WP document pages). */
	public static function entry_urls( array $opts = array() ) {
		$docs = array(
			'decision' => home_url( '/decisions/' ),
			'motion'   => home_url( '/motions/' ),
			'response' => home_url( '/responses/' ),
			'notice'   => home_url( '/notices/' ),
		);
		return array(
			'glossary'  => $opts['glossary'] ?? TK_Public_Pages::section_url( 'glossary' ),
			'timeline'  => $opts['timeline'] ?? TK_Public_Pages::section_url( 'timeline' ),
			'witnesses' => $opts['witnesses'] ?? TK_Public_Pages::section_url( 'witnesses' ),
			'docs'      => array_merge( $docs, (array) ( $opts['docs'] ?? array() ) ),
		);
	}

	public static function case_card( $key, $c, array $cits = array() ) {
		$out = '<article class="tk-casecard tk-case--' . esc_attr( $key ) . ( $c ? '' : ' tk-casecard--pending' ) . '">';
		if ( ! $c ) {
			$out .= '<h3 class="tk-casecard__title tk-casecard__kicker">' . esc_html( sprintf( __( 'תיק %s', 'trial-knowledge' ), $key ) ) . '</h3>';
			$out .= '<p class="tk-muted">' . esc_html__( 'המדריך לתיק בהכנה', 'trial-knowledge' ) . '</p>';
			return $out . '</article>';
		}
		$out  .= '<p class="tk-casecard__kicker">' . esc_html( sprintf( __( 'תיק %s', 'trial-knowledge' ), $key ) ) . '</p>';
		$url   = TK_Public_Pages::url( 'case', $key );
		$title = ! empty( $c['subtitle'] ) ? $c['subtitle'] : ( $c['title'] ?? '' );
		$out  .= '<h3 class="tk-casecard__title"><a href="' . esc_url( $url ) . '">' . esc_html( $title ) . '</a></h3>';
		if ( ! empty( $c['one_line']['text'] ) ) {
			$out .= '<p class="tk-casecard__line tk-glossable">' . esc_html( $c['one_line']['text'] ) . self::chips( $c['one_line']['citation_ids'] ?? array(), $cits ) . '</p>';
		}
		if ( ! empty( $c['defendants'] ) ) {
			$out .= '<p class="tk-casecard__meta"><span class="tk-muted">' . esc_html__( 'נאשמים:', 'trial-knowledge' ) . '</span> ' . esc_html( implode( ', ', (array) $c['defendants'] ) ) . '</p>';
		}
		$out .= '<p class="tk-casecard__go"><a class="tk-button tk-button--case" href="' . esc_url( $url ) . '">' . esc_html__( 'למדריך לתיק', 'trial-knowledge' ) . ' <span aria-hidden="true">←</span></a></p>';
		return $out . '</article>';
	}

	public static function indictment( array $ind ) {
		$cits = self::cit_map( $ind['citations'] ?? array() );
		$out  = '<p class="tk-sec__note">' . self::allegation_tag() . ' ' . esc_html__( 'אלה טענות התביעה כפי שנוסחו בכתב האישום, לא קביעות של בית המשפט.', 'trial-knowledge' ) . '</p>';
		$ov   = self::block( $ind, 'overview' );
		if ( $ov ) {
			$out .= self::prose( $ov, $cits );
		}
		$def = self::block( $ind, 'defendants' );
		if ( $def ) {
			$out .= '<h3 class="tk-sub">' . esc_html__( 'הנאשמים', 'trial-knowledge' ) . '</h3>' . self::labelled( $def, $cits, 'tk-labelled--defendants' );
		}
		if ( ! empty( $ind['document']['source_version_id'] ) ) {
			$doc  = $ind['document'];
			$out .= '<p><a class="tk-button" href="' . esc_url( TK_Public_Pages::url( 'document', $doc['source_version_id'] ) ) . '">' . esc_html__( 'לכתב האישום המלא', 'trial-knowledge' ) . '</a>';
			if ( ! empty( $doc['page_count'] ) ) {
				$out .= ' <span class="tk-muted">' . esc_html( sprintf( __( '%d עמודים', 'trial-knowledge' ), (int) $doc['page_count'] ) ) . '</span>';
			}
			$out .= '</p>';
		}
		return $out;
	}

	private static function status( array $g, array $urls ) {
		$out   = '';
		$slugs = TK_Guides::slug_map( (array) ( $g['witnesses'] ?? array() ) );
		$lh    = $g['latest_hearing'] ?? null;
		if ( $lh ) {
			$cits = self::cit_map( $lh['citations'] ?? array() );
			$url  = TK_Public_Pages::url( 'hearing', $lh['id'] );
			$out .= '<article class="tk-latest"><p class="tk-latest__kicker">' . esc_html__( 'הדיון האחרון שפורסם', 'trial-knowledge' ) . '</p>';
			$out .= '<h3 class="tk-latest__title"><a href="' . esc_url( $url ) . '">' . esc_html( sprintf( __( 'דיון מיום %s', 'trial-knowledge' ), self::fmt_date( $lh['hearing_date'] ) ) ) . '</a></h3>';
			if ( ! empty( $lh['witnesses'] ) ) {
				$names = array();
				foreach ( $lh['witnesses'] as $w ) {
					$names[] = self::witness_link( $w, $slugs );
				}
				$out .= '<p class="tk-latest__w"><span class="tk-muted">' . esc_html__( 'העידו:', 'trial-knowledge' ) . '</span> ' . implode( ', ', $names ) . '</p>';
			}
			$out .= self::sentences( (array) ( $lh['summary_sentences'] ?? array() ), $cits );
			$out .= '<p><a class="tk-button" href="' . esc_url( $url ) . '">' . esc_html__( 'לדף הדיון', 'trial-knowledge' ) . '</a></p></article>';
		}
		$counts = $g['counts'] ?? array();
		if ( $counts ) {
			$docs  = (array) ( $counts['documents'] ?? array() );
			$stats = array( array( (int) ( $counts['hearings'] ?? 0 ), __( 'דיונים שפורסמו', 'trial-knowledge' ), $urls['timeline'] ) );
			$names = array( 'decision' => 'החלטות', 'motion' => 'בקשות', 'response' => 'תגובות', 'notice' => 'הודעות' );
			foreach ( $names as $t => $label ) {
				if ( ! empty( $docs[ $t ] ) ) {
					$stats[] = array( (int) $docs[ $t ], $label, $urls['docs'][ $t ] ?? '' );
				}
			}
			$out .= '<ul class="tk-stats">';
			foreach ( $stats as $s ) {
				$inner = '<span class="tk-stats__n">' . esc_html( (string) $s[0] ) . '</span> <span class="tk-stats__l">' . esc_html( $s[1] ) . '</span>';
				$out  .= '<li>' . ( $s[2] ? '<a href="' . esc_url( $s[2] ) . '">' . $inner . '</a>' : $inner ) . '</li>';
			}
			$out .= '</ul>';
		}
		return $out ? $out : '<p class="tk-muted">' . esc_html__( 'עדיין לא פורסמו דיונים.', 'trial-knowledge' ) . '</p>';
	}

	private static function entries( array $g, array $urls ) {
		$docs  = $urls['docs'];
		$tiles = array(
			array( $urls['timeline'], __( 'ציר הזמן', 'trial-knowledge' ), __( 'מה קרה ומתי: האירועים לפי כתב האישום, והדיונים וההחלטות במשפט.', 'trial-knowledge' ) ),
			array( $urls['witnesses'], __( 'עדים', 'trial-knowledge' ), __( 'מי העיד, מתי, ומה עלה בעדות.', 'trial-knowledge' ) ),
			array( $urls['glossary'], __( 'מילון מונחים', 'trial-knowledge' ), __( 'חקירה נגדית, מוצג, הפרת אמונים — במילים פשוטות.', 'trial-knowledge' ) ),
			array( '#tk-ask', __( 'שאלו את המאגר', 'trial-knowledge' ), __( 'שאלה חופשית; התשובה מצטטת רק חומר שפורסם.', 'trial-knowledge' ) ),
		);
		$out = '<ul class="tk-entries">';
		foreach ( $tiles as $t ) {
			$out .= '<li class="tk-entry"><a class="tk-entry__a" href="' . esc_url( $t[0] ) . '"><span class="tk-entry__t">' . esc_html( $t[1] ) . '</span><span class="tk-entry__d">' . esc_html( $t[2] ) . '</span></a></li>';
		}
		$labels = array( 'decision' => 'החלטות', 'motion' => 'בקשות', 'response' => 'תגובות', 'notice' => 'הודעות' );
		$counts = (array) ( $g['counts']['documents'] ?? array() );
		$out   .= '<li class="tk-entry tk-entry--docs"><span class="tk-entry__t">' . esc_html__( 'מסמכים', 'trial-knowledge' ) . '</span><span class="tk-entry__d">' . esc_html__( 'החלטות בית המשפט ובקשות הצדדים, במלואן.', 'trial-knowledge' ) . '</span><span class="tk-entry__links">';
		foreach ( $labels as $t => $l ) {
			$out .= '<a class="tk-pill" href="' . esc_url( $docs[ $t ] ) . '">' . esc_html( $l ) . ( ! empty( $counts[ $t ] ) ? ' <span class="tk-pill__n">' . (int) $counts[ $t ] . '</span>' : '' ) . '</a>';
		}
		return $out . '</span></li></ul>';
	}

	// ------------------------------------------------------------------ witnesses

	/**
	 * [tk_witnesses] and the start-page list.
	 *
	 * @param array $ws   /v2/guide witnesses.
	 * @param array $opts compact, current (slug).
	 */
	public static function witnesses_list( array $ws, array $opts = array() ) {
		if ( ! $ws ) {
			return '<p class="tk-empty">' . esc_html__( 'עדיין אין עדים בחומר שפורסם.', 'trial-knowledge' ) . '</p>';
		}
		$cur = $opts['current'] ?? '';
		$out = '<ul class="tk-wlist' . ( ! empty( $opts['compact'] ) ? ' tk-wlist--compact' : '' ) . '" dir="rtl" lang="he">';
		foreach ( $ws as $w ) {
			$n      = (int) ( $w['hearing_count'] ?? 0 );
			$is_cur = $cur && $cur === $w['slug'];
			$out   .= '<li class="tk-wlist__item' . ( $is_cur ? ' tk-wlist__item--current' : '' ) . '">';
			$out   .= '<a class="tk-wlist__name" href="' . esc_url( TK_Public_Pages::url( 'witness', $w['slug'] ) ) . '"' . ( $is_cur ? ' aria-current="page"' : '' ) . '>' . esc_html( $w['name'] ) . '</a>';
			if ( ! empty( $w['label'] ) ) {
				$out .= ' <span class="tk-badge tk-badge--label">' . esc_html( $w['label'] ) . '</span>';
			}
			$out .= ' <span class="tk-wlist__meta">' . esc_html( 1 === $n ? __( 'דיון אחד', 'trial-knowledge' ) : sprintf( __( '%d דיונים', 'trial-knowledge' ), $n ) );
			$range = self::date_range( $w['first_date'] ?? '', $w['last_date'] ?? '' );
			if ( $range ) {
				$out .= ' · ' . esc_html( $range );
			}
			$out .= '</span>';
			if ( ! empty( $w['cases'] ) ) {
				$out .= ' <span class="tk-wlist__cases">' . self::case_badges( $w['cases'], false ) . '</span>';
			}
			$out .= '</li>';
		}
		return $out . '</ul>';
	}

	/**
	 * Witness page body.
	 *
	 * @param array $w   /v2/guide/witnesses/{slug}.
	 * @param array $all All witnesses (for the list at the end).
	 */
	public static function witness_page( array $w, array $all = array() ) {
		$cits = self::cit_map( $w['citations'] ?? array() );
		$out  = '<article class="tk-guide tk-witness" dir="rtl" lang="he">';
		$out .= '<header class="tk-head"><p class="tk-kicker">' . esc_html__( 'עדים במשפט', 'trial-knowledge' ) . '</p>';
		$out .= '<h1 class="tk-head__title">' . esc_html( $w['name'] ) . '</h1>';
		$meta = array();
		if ( ! empty( $w['label'] ) ) {
			$meta[] = '<span class="tk-badge tk-badge--label">' . esc_html( $w['label'] ) . '</span>';
		}
		if ( ! empty( $w['cases'] ) ) {
			$meta[] = self::case_badges( $w['cases'] );
		}
		$n      = count( (array) ( $w['hearings'] ?? array() ) );
		$meta[] = '<span class="tk-muted">' . esc_html( 1 === $n ? __( 'העיד/ה בדיון אחד שפורסם', 'trial-knowledge' ) : sprintf( __( 'העיד/ה ב־%d דיונים שפורסמו', 'trial-knowledge' ), $n ) ) . '</span>';
		$out   .= '<p class="tk-head__meta">' . implode( ' ', $meta ) . '</p></header>';

		$role = self::block( $w, 'role' );
		$test = self::block( $w, 'testimony' );
		if ( $role ) {
			$out .= self::section( 'tk-w-role', self::BLOCKS['role'], self::prose( $role, $cits ) );
		}
		if ( $test ) {
			$out .= self::section( 'tk-w-testimony', self::BLOCKS['testimony'], self::prose( $test, $cits ) );
		}
		if ( ! $role && ! $test ) {
			$out .= '<p class="tk-notice tk-notice--soft">' . esc_html__( 'סקירה של העדות בהכנה. בינתיים מוצגים כאן עיקרי הדיונים שבהם העיד/ה, מתוך תקצירי הדיונים שפורסמו.', 'trial-knowledge' ) . '</p>';
		}

		$hl = '';
		foreach ( (array) ( $w['hearings'] ?? array() ) as $h ) {
			$url = TK_Public_Pages::url( 'hearing', $h['id'] );
			$hl .= '<li class="tk-hlist__item"><h3 class="tk-hlist__h"><a href="' . esc_url( $url ) . '">' . esc_html( sprintf( __( 'דיון מיום %s', 'trial-knowledge' ), self::fmt_date( $h['hearing_date'] ) ) ) . '</a></h3>';
			$hl .= ! empty( $h['digest_sentences'] ) ? self::sentences( $h['digest_sentences'], $cits ) : '<p class="tk-muted">' . esc_html__( 'טרם פורסם תקציר לדיון זה.', 'trial-knowledge' ) . '</p>';
			$hl .= '</li>';
		}
		if ( $hl ) {
			$out .= self::section( 'tk-w-hearings', __( 'הדיונים שבהם העיד/ה', 'trial-knowledge' ), '<ol class="tk-hlist">' . $hl . '</ol>' );
		}
		if ( ! empty( $w['notable_exchanges'] ) ) {
			$out .= self::section( 'tk-w-qa', __( 'שאלות ותשובות מרכזיות', 'trial-knowledge' ), self::exchanges( $w['notable_exchanges'], $cits, true ) );
		}
		if ( $all ) {
			$out .= self::section( 'tk-w-all', __( 'כל העדים', 'trial-knowledge' ), self::witnesses_list( $all, array( 'compact' => true, 'current' => $w['slug'] ) ) );
		}
		return $out . '</article>';
	}

	/**
	 * Protocol text as running prose: PDF line breaks become spaces and a speaker
	 * name printed at the start of the turn ("עו"ד חן: …") is not repeated.
	 */
	public static function flow_text( $text, $speaker = '' ) {
		$t = trim( preg_replace( '/\s*\n\s*/u', ' ', (string) $text ) );
		if ( '' !== (string) $speaker && 0 === strpos( $t, (string) $speaker ) ) {
			$rest = ltrim( substr( $t, strlen( (string) $speaker ) ) );
			if ( 0 === strpos( $rest, ':' ) ) {
				$t = ltrim( substr( $rest, 1 ) );
			}
		}
		return $t;
	}

	/** Badge for answer_relation (affirms/denies via TK_Render::qa_badge). */
	public static function relation_badge( $rel ) {
		if ( 'affirms' === $rel ) {
			return TK_Render::qa_badge( __( 'העד אישר את הנטען בשאלה', 'trial-knowledge' ) );
		}
		if ( 'denies' === $rel ) {
			return TK_Render::qa_badge( __( 'העד הכחיש את הנטען בשאלה', 'trial-knowledge' ) );
		}
		return '<span class="tk-badge tk-badge--qa tk-badge--neutral" title="' . esc_attr__( 'התשובה אינה אישור או הכחשה מפורשים', 'trial-knowledge' ) . '">' . esc_html__( 'לא חד־משמעי', 'trial-knowledge' ) . '</span>';
	}

	/**
	 * Question/answer pairs.
	 *
	 * @param array $xs       exchanges with question/answer text.
	 * @param array $cits     cit_map.
	 * @param bool  $with_date Show the hearing date link.
	 */
	public static function exchanges( array $xs, array $cits, $with_date = false ) {
		$out = '<ol class="tk-qa">';
		foreach ( $xs as $x ) {
			$out .= '<li class="tk-qa__item">';
			if ( $with_date && ! empty( $x['hearing_id'] ) ) {
				$out .= '<p class="tk-qa__when"><a href="' . esc_url( TK_Public_Pages::url( 'hearing', $x['hearing_id'] ) ) . '">' . esc_html( sprintf( __( 'דיון מיום %s', 'trial-knowledge' ), self::fmt_date( $x['hearing_date'] ?? '' ) ) ) . '</a></p>';
			}
			$qs   = (string) ( $x['question_speaker'] ?? '' );
			$as   = (string) ( $x['answer_speaker'] ?? '' );
			$out .= '<div class="tk-qa__q"><span class="tk-qa__who">' . esc_html( '' !== $qs ? $qs : __( 'שאלה', 'trial-knowledge' ) ) . '</span><p>' . esc_html( self::flow_text( $x['question'] ?? '', $qs ) ) . '</p></div>';
			$out .= '<div class="tk-qa__a"><span class="tk-qa__who">' . esc_html( '' !== $as ? $as : __( 'תשובה', 'trial-knowledge' ) ) . '</span><p>' . esc_html( self::flow_text( $x['answer'] ?? '', $as ) ) . '</p></div>';
			$out .= '<p class="tk-qa__foot">' . self::relation_badge( $x['answer_relation'] ?? '' );
			if ( ! empty( $x['answer_unit_id'] ) && preg_match( '/^su_[0-9a-f]{26}$/', $x['answer_unit_id'] ) ) {
				$label = isset( $cits[ $x['answer_unit_id'] ]['page'] ) ? sprintf( __( 'בפרוטוקול, עמ׳ %d', 'trial-knowledge' ), (int) $cits[ $x['answer_unit_id'] ]['page'] ) : __( 'בפרוטוקול', 'trial-knowledge' );
				$out  .= ' <a class="tk-chip" href="' . esc_url( TK_Render::citation_url( $x['answer_unit_id'] ) ) . '">' . esc_html( $label ) . '</a>';
			}
			$out .= '</p></li>';
		}
		return $out . '</ol>';
	}

	// ------------------------------------------------------------------ case page

	/**
	 * Case page body.
	 *
	 * @param array $c    /v2/guide/cases/{key}.
	 * @param array $opts timeline (url).
	 */
	public static function case_page( array $c, array $opts = array() ) {
		$key  = (string) $c['key'];
		$cits = self::cit_map( $c['citations'] ?? array() );
		$tl   = add_query_arg( 'tk_case', $key, $opts['timeline'] ?? TK_Public_Pages::section_url( 'timeline' ) );
		$out  = '<article class="tk-guide tk-casepage tk-case--' . esc_attr( $key ) . '" dir="rtl" lang="he">';
		$out .= '<header class="tk-head tk-head--case"><p class="tk-kicker">' . esc_html( $c['title'] ?? sprintf( __( 'תיק %s', 'trial-knowledge' ), $key ) ) . '</p>';
		$out .= '<h1 class="tk-head__title">' . esc_html( ! empty( $c['subtitle'] ) ? $c['subtitle'] : ( $c['title'] ?? '' ) ) . '</h1>';
		$out .= '<p class="tk-banner" role="note">' . esc_html__( 'מה שמופיע כאן הוא תיאור הטענות בכתב האישום, לא קביעות של בית המשפט.', 'trial-knowledge' ) . '</p>';
		foreach ( self::block( $c, 'one_line' ) as $it ) {
			$out .= '<p class="tk-lead tk-glossable">' . esc_html( $it['text'] ) . self::chips( $it['citation_ids'] ?? array(), $cits ) . '</p>';
		}
		$out .= '</header>';

		$secs = array();
		if ( $x = self::block( $c, 'overview' ) ) {
			$secs['tk-c-overview'] = array( self::BLOCKS['overview'], self::prose( $x, $cits ) );
		}
		if ( $x = self::block( $c, 'alleged' ) ) {
			$secs['tk-c-alleged'] = array( self::BLOCKS['alleged'], '<p class="tk-sec__note">' . self::allegation_tag() . '</p>' . self::prose( $x, $cits ) );
		}
		if ( $x = self::block( $c, 'charges' ) ) {
			$secs['tk-c-charges'] = array( self::BLOCKS['charges'], self::charges( $x, $cits ) );
		}
		if ( $x = self::block( $c, 'people' ) ) {
			$secs['tk-c-people'] = array( self::BLOCKS['people'], self::people( $x, $cits ) );
		}
		$ev = self::block( $c, 'events' );
		if ( $ev ) {
			$secs['tk-c-events'] = array( self::BLOCKS['events'], '<p class="tk-sec__note">' . self::allegation_tag() . '</p>' . self::events( $ev, $cits ) .
				'<p><a class="tk-button" href="' . esc_url( $tl ) . '">' . esc_html__( 'התיק בציר הזמן המלא', 'trial-knowledge' ) . '</a></p>' );
		}
		if ( ! empty( $c['hearings'] ) ) {
			$secs['tk-c-hearings'] = array( __( 'דיונים שבהם העידו מעורבים בתיק', 'trial-knowledge' ), self::hearing_list( $c['hearings'], $opts['slugs'] ?? array() ) );
		}
		if ( count( $secs ) > 2 ) {
			$out .= '<nav class="tk-toc" aria-label="' . esc_attr__( 'בעמוד זה', 'trial-knowledge' ) . '"><span class="tk-muted">' . esc_html__( 'בעמוד זה:', 'trial-knowledge' ) . '</span> ';
			foreach ( $secs as $id => $s ) {
				$out .= '<a href="#' . esc_attr( $id ) . '">' . esc_html( $s[0] ) . '</a> ';
			}
			$out .= '</nav>';
		}
		foreach ( $secs as $id => $s ) {
			$out .= self::section( $id, $s[0], $s[1] );
		}
		if ( ! empty( $c['document']['source_version_id'] ) ) {
			$d    = $c['document'];
			$src  = '<p>' . esc_html__( 'כל הטענות בעמוד זה לקוחות מכתב האישום, וכל משפט מקושר לעמוד ולשורות בו.', 'trial-knowledge' ) . '</p>';
			$src .= '<p><a class="tk-button" href="' . esc_url( TK_Public_Pages::url( 'document', $d['source_version_id'] ) ) . '">' . esc_html( $d['title'] ?? __( 'כתב האישום', 'trial-knowledge' ) ) . '</a>';
			if ( ! empty( $d['document_date'] ) ) {
				$src .= ' <span class="tk-muted">' . self::time_tag( $d['document_date'] ) . '</span>';
			}
			$src .= '</p>';
			$out .= self::section( 'tk-c-source', __( 'המקור', 'trial-knowledge' ), $src );
		}
		$out .= '<nav class="tk-other-cases" aria-label="' . esc_attr__( 'התיקים האחרים', 'trial-knowledge' ) . '">';
		foreach ( TK_Guides::CASE_KEYS as $k ) {
			if ( $k !== $key ) {
				$out .= self::case_badge( $k ) . ' ';
			}
		}
		return $out . '</nav></article>';
	}

	/** Friendly page for a case guide that is not published yet. */
	public static function case_pending( $key, array $opts = array() ) {
		$out  = '<article class="tk-guide tk-casepage tk-case--' . esc_attr( $key ) . '" dir="rtl" lang="he">';
		$out .= '<header class="tk-head tk-head--case"><p class="tk-kicker">' . esc_html( sprintf( __( 'תיק %s', 'trial-knowledge' ), $key ) ) . '</p>';
		$out .= '<h1 class="tk-head__title">' . esc_html__( 'המדריך לתיק בהכנה', 'trial-knowledge' ) . '</h1></header>';
		$out .= '<p class="tk-notice tk-notice--soft">' . esc_html__( 'המדריך לתיק הזה עדיין עובר בדיקה ולא פורסם. כל מדריך נבדק מול כתב האישום לפני פרסום.', 'trial-knowledge' ) . '</p>';
		$out .= '<p>' . esc_html__( 'בינתיים אפשר:', 'trial-knowledge' ) . '</p><ul>';
		$out .= '<li><a href="' . esc_url( $opts['timeline'] ?? TK_Public_Pages::section_url( 'timeline' ) ) . '">' . esc_html__( 'לעיין בציר הזמן של המשפט', 'trial-knowledge' ) . '</a></li>';
		$out .= '<li><a href="' . esc_url( $opts['witnesses'] ?? TK_Public_Pages::section_url( 'witnesses' ) ) . '">' . esc_html__( 'לקרוא על העדים', 'trial-knowledge' ) . '</a></li>';
		$out .= '<li><a href="' . esc_url( $opts['home'] ?? home_url( '/' ) ) . '">' . esc_html__( 'לחזור לעמוד "מתחילים כאן"', 'trial-knowledge' ) . '</a></li></ul>';
		return $out . '</article>';
	}

	private static function charges( array $items, array $cits ) {
		$out = '<ul class="tk-charges tk-glossable">';
		foreach ( $items as $it ) {
			$offenses = array_filter( array_map( 'trim', preg_split( '/[;；]/u', (string) ( $it['text'] ?? '' ) ) ) );
			$out     .= '<li class="tk-charges__item"><span class="tk-charges__who">' . esc_html( $it['label'] ?? '' ) . '</span><ul class="tk-charges__list">';
			foreach ( $offenses as $o ) {
				$out .= '<li>' . esc_html( $o ) . '</li>';
			}
			$out .= '</ul>' . self::chips( $it['citation_ids'] ?? array(), $cits ) . '</li>';
		}
		return $out . '</ul>';
	}

	private static function people( array $items, array $cits ) {
		$out = '<ul class="tk-people">';
		foreach ( $items as $it ) {
			$slug = $it['witness_slug'] ?? '';
			$name = esc_html( $it['label'] ?? '' );
			if ( $slug && TK_Guides::valid_witness( $slug ) ) {
				$name = '<a href="' . esc_url( TK_Public_Pages::url( 'witness', $slug ) ) . '">' . $name . '</a> <span class="tk-badge tk-badge--testified">' . esc_html__( 'העיד/ה במשפט', 'trial-knowledge' ) . '</span>';
			}
			$out .= '<li class="tk-people__item"><span class="tk-people__name">' . $name . '</span> <span class="tk-people__role tk-glossable">' . esc_html( $it['text'] ?? '' ) . self::chips( $it['citation_ids'] ?? array(), $cits ) . '</span></li>';
		}
		return $out . '</ul>';
	}

	/** Case events grouped by year. */
	public static function events( array $items, array $cits ) {
		usort(
			$items,
			static function ( $a, $b ) {
				return strcmp( (string) ( $a['date'] ?? '' ), (string) ( $b['date'] ?? '' ) );
			}
		);
		$out  = '<div class="tk-events">';
		$year = null;
		foreach ( $items as $it ) {
			$y = substr( (string) ( $it['date'] ?? '' ), 0, 4 );
			if ( $y !== $year ) {
				$out .= ( null === $year ? '' : '</ol>' ) . '<h3 class="tk-events__year">' . esc_html( '' === $y ? __( 'ללא תאריך', 'trial-knowledge' ) : $y ) . '</h3><ol class="tk-events__list">';
				$year = $y;
			}
			$prec = $it['date_precision'] ?? 'day';
			$out .= '<li class="tk-events__item">' . ( ! empty( $it['date'] ) ? '<span class="tk-events__date">' . self::time_tag( $it['date'], $prec ) . '</span>' : '' ) .
				'<div class="tk-events__body tk-glossable">' . ( ! empty( $it['label'] ) ? '<strong class="tk-events__label">' . esc_html( $it['label'] ) . '</strong> ' : '' ) .
				esc_html( $it['text'] ?? '' ) . self::chips( $it['citation_ids'] ?? array(), $cits ) . '</div></li>';
		}
		return $out . ( null === $year ? '' : '</ol>' ) . '</div>';
	}

	public static function hearing_list( array $hearings, array $slugs = array() ) {
		$out = '<ul class="tk-hearings">';
		foreach ( $hearings as $h ) {
			$ws = array();
			foreach ( (array) ( $h['witnesses'] ?? array() ) as $raw ) {
				$ws[] = self::witness_link( $raw, $slugs );
			}
			$out .= '<li><a href="' . esc_url( TK_Public_Pages::url( 'hearing', $h['id'] ) ) . '">' . esc_html( self::fmt_date( $h['hearing_date'] ) ) . '</a>' .
				( $ws ? ' <span class="tk-muted">·</span> ' . implode( ', ', $ws ) : '' ) . '</li>';
		}
		return $out . '</ul>';
	}

	// ------------------------------------------------------------------ timeline

	/** Link of a timeline event. */
	public static function event_url( array $e ) {
		$l = (array) ( $e['link'] ?? array() );
		switch ( $l['type'] ?? '' ) {
			case 'case':
				return TK_Guides::valid_case( $l['key'] ?? '' ) ? TK_Public_Pages::url( 'case', $l['key'] ) : '';
			case 'hearing':
				return preg_match( '/^hr_[0-9a-f]{26}$/', (string) ( $l['id'] ?? '' ) ) ? TK_Public_Pages::url( 'hearing', $l['id'] ) : '';
			case 'document':
				return preg_match( '/^sv_[0-9a-f]{26}$/', (string) ( $l['id'] ?? '' ) ) ? TK_Public_Pages::url( 'document', $l['id'] ) : '';
		}
		return '';
	}

	/**
	 * Data for assets/timeline.js: URLs resolved server-side, citations reduced to chip data.
	 *
	 * @param array $t /v2/guide/timeline.
	 */
	public static function timeline_payload( array $t ) {
		$cits   = self::cit_map( $t['citations'] ?? array() );
		$events = array();
		$used   = array();
		foreach ( (array) ( $t['events'] ?? array() ) as $e ) {
			if ( empty( $e['date'] ) || ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', (string) $e['date'] ) ) {
				continue;
			}
			$ids = array_values( array_filter( (array) ( $e['citation_ids'] ?? array() ), static function ( $id ) use ( $cits ) {
				return isset( $cits[ $id ] );
			} ) );
			foreach ( $ids as $id ) {
				$used[ $id ] = 1;
			}
			$kind     = isset( self::KINDS[ $e['kind'] ?? '' ] ) ? $e['kind'] : 'other';
			$events[] = array(
				'id'    => (string) $e['id'],
				'track' => 'story' === ( $e['track'] ?? '' ) ? 'story' : 'trial',
				'date'  => $e['date'],
				'p'     => in_array( $e['date_precision'] ?? 'day', array( 'day', 'month', 'year' ), true ) ? $e['date_precision'] : 'day',
				'title' => (string) ( $e['title'] ?? '' ),
				'text'  => (string) ( $e['text'] ?? '' ),
				'cases' => array_values( array_filter( (array) ( $e['case_keys'] ?? array() ), array( 'TK_Guides', 'valid_case' ) ) ),
				'kind'  => $kind,
				'url'   => self::event_url( $e ),
				'cits'  => $ids,
			);
		}
		$cmap = array();
		foreach ( array_keys( $used ) as $id ) {
			$c           = $cits[ $id ];
			$cmap[ $id ] = array(
				'label' => sprintf( 'עמ׳ %d', (int) $c['page'] ),
				'title' => sprintf( 'עמ׳ %1$d, שורות %2$d–%3$d', (int) $c['page'], (int) ( $c['line_start'] ?? 0 ), (int) ( $c['line_end'] ?? 0 ) ),
				'url'   => TK_Render::citation_url( $id ),
			);
		}
		return array( 'events' => $events, 'citations' => (object) $cmap, 'kinds' => self::KINDS );
	}

	/** JSON safe inside a <script> element (no "</script>", no HTML-significant characters). */
	public static function json_for_script( $data ) {
		return wp_json_encode( $data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT );
	}

	/**
	 * [tk_timeline]: JSON for the zoomable view + a plain grouped list without JS.
	 *
	 * @param array  $t    /v2/guide/timeline.
	 * @param string $case Preselected case filter.
	 */
	public static function timeline( array $t, $case = '' ) {
		$case    = TK_Guides::valid_case( $case ) ? $case : '';
		$payload = self::timeline_payload( $t );
		$id      = 'tk-tl-' . substr( md5( (string) count( $payload['events'] ) . $case ), 0, 6 );
		$out     = '<div class="tk-tl" id="' . esc_attr( $id ) . '" dir="rtl" lang="he" data-case="' . esc_attr( $case ) . '">';
		$out    .= '<p class="tk-tl__intro">' . esc_html__( 'שני מסלולים על ציר זמן אחד: "מה קרה" — האירועים כפי שכתב האישום מתאר אותם (טענות התביעה), ו"המשפט" — כתב האישום, הדיונים וההחלטות.', 'trial-knowledge' ) . '</p>';
		$out    .= '<script type="application/json" class="tk-tl__data">' . self::json_for_script( $payload ) . '</script>';
		$out    .= '<div class="tk-tl__fallback">';
		$has_story = false;
		foreach ( $payload['events'] as $e ) {
			$has_story = $has_story || 'story' === $e['track'];
		}
		if ( ! $has_story ) {
			$out .= '<p class="tk-muted">' . esc_html__( 'האירועים לפי כתב האישום יוצגו כאן אחרי שהמדריכים לתיקים יפורסמו.', 'trial-knowledge' ) . '</p>';
		}
		$year = null;
		$n    = 0;
		foreach ( $payload['events'] as $e ) {
			if ( $case && $e['cases'] && ! in_array( $case, $e['cases'], true ) ) {
				continue;
			}
			if ( $case && ! $e['cases'] && 'story' === $e['track'] ) {
				continue;
			}
			$y = substr( $e['date'], 0, 4 );
			if ( $y !== $year ) {
				$out .= ( null === $year ? '' : '</ol>' ) . '<h3 class="tk-tl__fy">' . esc_html( $y ) . '</h3><ol class="tk-tl__flist">';
				$year = $y;
			}
			++$n;
			$track = 'story' === $e['track'] ? __( 'לפי כתב האישום', 'trial-knowledge' ) : self::KINDS[ $e['kind'] ];
			$title = $e['url'] ? '<a href="' . esc_url( $e['url'] ) . '">' . esc_html( $e['title'] ) . '</a>' : esc_html( $e['title'] );
			$out  .= '<li class="tk-tl__fitem tk-tl__fitem--' . esc_attr( $e['track'] ) . ( $e['cases'] ? ' tk-case--' . esc_attr( $e['cases'][0] ) : '' ) . '">' .
				self::time_tag( $e['date'], $e['p'] ) . ' <span class="tk-badge">' . esc_html( $track ) . '</span> ' . $title .
				( $e['cases'] ? ' ' . self::case_badges( $e['cases'], false ) : '' ) . '</li>';
		}
		if ( null !== $year ) {
			$out .= '</ol>';
		}
		if ( ! $n ) {
			$out .= '<p class="tk-empty">' . esc_html__( 'אין אירועים להצגה.', 'trial-knowledge' ) . '</p>';
		}
		return $out . '</div></div>';
	}

	// ------------------------------------------------------------------ glossary

	/**
	 * [tk_glossary]: terms by category, one anchor per term (#term-{id}).
	 *
	 * @param array $gl /v2/glossary.
	 */
	public static function glossary( array $gl ) {
		$terms = (array) ( $gl['terms'] ?? array() );
		$byid  = array();
		$cats  = array();
		foreach ( $terms as $t ) {
			$byid[ $t['id'] ] = $t;
			$cats[ isset( self::GLOSSARY_CATEGORIES[ $t['category'] ?? '' ] ) ? $t['category'] : 'procedure' ][] = $t;
		}
		$out = '<div class="tk-glossary" dir="rtl" lang="he">';
		if ( ! empty( $gl['note'] ) ) {
			$out .= '<p class="tk-notice tk-notice--soft" role="note">' . esc_html( $gl['note'] ) . '</p>';
		}
		if ( ! $terms ) {
			return $out . '<p class="tk-empty">' . esc_html__( 'המילון ריק כרגע.', 'trial-knowledge' ) . '</p></div>';
		}
		$out .= '<nav class="tk-toc" aria-label="' . esc_attr__( 'נושאים במילון', 'trial-knowledge' ) . '">';
		foreach ( self::GLOSSARY_CATEGORIES as $k => $label ) {
			if ( ! empty( $cats[ $k ] ) ) {
				$out .= '<a href="#cat-' . esc_attr( $k ) . '">' . esc_html( $label ) . '</a> ';
			}
		}
		$out .= '</nav>';
		foreach ( self::GLOSSARY_CATEGORIES as $k => $label ) {
			if ( empty( $cats[ $k ] ) ) {
				continue;
			}
			$out .= '<section class="tk-sec tk-glossary__cat" id="cat-' . esc_attr( $k ) . '"><h2 class="tk-sec__h">' . esc_html( $label ) . '</h2><dl class="tk-terms">';
			foreach ( $cats[ $k ] as $t ) {
				$tid  = preg_replace( '/[^A-Za-z0-9_-]/', '', (string) $t['id'] );
				$out .= '<div class="tk-term" id="term-' . esc_attr( $tid ) . '"><dt class="tk-term__t">' . esc_html( $t['term'] ) . '</dt>';
				$out .= '<dd class="tk-term__short">' . esc_html( $t['short'] ?? '' ) . '</dd>';
				if ( ! empty( $t['long'] ) ) {
					$out .= '<dd class="tk-term__long">' . esc_html( $t['long'] ) . '</dd>';
				}
				$link = isset( $t['link'] ) && is_array( $t['link'] ) ? $t['link'] : null;
				if ( $link && 'case' === ( $link['type'] ?? '' ) && TK_Guides::valid_case( $link['key'] ?? '' ) ) {
					$out .= '<dd><a href="' . esc_url( TK_Public_Pages::url( 'case', $link['key'] ) ) . '">' . esc_html__( 'לעמוד התיק', 'trial-knowledge' ) . '</a></dd>';
				}
				$see = array();
				foreach ( (array) ( $t['see_also'] ?? array() ) as $sid ) {
					if ( isset( $byid[ $sid ] ) ) {
						$see[] = '<a href="#term-' . esc_attr( preg_replace( '/[^A-Za-z0-9_-]/', '', $sid ) ) . '">' . esc_html( $byid[ $sid ]['term'] ) . '</a>';
					}
				}
				if ( $see ) {
					$out .= '<dd class="tk-term__see"><span class="tk-muted">' . esc_html__( 'ראו גם:', 'trial-knowledge' ) . '</span> ' . implode( ', ', $see ) . '</dd>';
				}
				$out .= '</div>';
			}
			$out .= '</dl></section>';
		}
		return $out . '</div>';
	}

	// ------------------------------------------------------------------ hearing page

	/**
	 * Tabbed hearing page. Without JS the tabs are anchor links and every panel is shown.
	 *
	 * @param array $d    /v2/hearings/{id} (hearing, digest).
	 * @param array $opts transcript (array|null), transcript_error (bool), slugs, exchanges, tab, base_url.
	 */
	public static function hearing_page( array $d, array $opts = array() ) {
		$h     = $d['hearing'];
		$dg    = $d['digest'] ?? null;
		$slugs = (array) ( $opts['slugs'] ?? array() );
		$tab   = isset( self::TABS[ $opts['tab'] ?? '' ] ) ? $opts['tab'] : 'summary';
		$base  = $opts['base_url'] ?? TK_Public_Pages::url( 'hearing', $h['id'] );
		$cits  = self::cit_map( $dg['citations'] ?? array() );
		$t     = $opts['transcript'] ?? null;

		$out  = '<div class="tk-guide tk-hearing" dir="rtl" lang="he">';
		$out .= '<header class="tk-head"><p class="tk-kicker">' . esc_html__( 'דיון בבית המשפט', 'trial-knowledge' ) . '</p>';
		$out .= '<h1 class="tk-head__title">' . esc_html( sprintf( __( 'דיון מיום %s', 'trial-knowledge' ), self::fmt_date( $h['hearing_date'] ) ) ) . '</h1>';
		$out .= '<dl class="tk-meta">';
		if ( ! empty( $h['witnesses'] ) ) {
			$ws = array();
			foreach ( $h['witnesses'] as $raw ) {
				$ws[] = self::witness_link( $raw, $slugs );
			}
			$out .= '<div><dt>' . esc_html( count( $ws ) > 1 ? __( 'עדים', 'trial-knowledge' ) : __( 'עד/ה', 'trial-knowledge' ) ) . '</dt><dd>' . implode( ', ', $ws ) . '</dd></div>';
		}
		if ( ! empty( $h['judges'] ) ) {
			$out .= '<div><dt>' . esc_html__( 'שופטים', 'trial-knowledge' ) . '</dt><dd>' . esc_html( implode( ', ', $h['judges'] ) ) . '</dd></div>';
		}
		$out .= '</dl></header>';

		// tab list (links work without JS)
		$out .= '<div class="tk-tabs" data-tk-tabs data-active="' . esc_attr( $tab ) . '">';
		$out .= '<nav class="tk-tabs__nav" aria-label="' . esc_attr__( 'חלקי הדף', 'trial-knowledge' ) . '"><ul class="tk-tabs__list">';
		foreach ( self::TABS as $k => $label ) {
			$out .= '<li><a class="tk-tabs__tab" id="tk-tabbtn-' . esc_attr( $k ) . '" data-tab="' . esc_attr( $k ) . '" href="#tk-tab-' . esc_attr( $k ) . '"' .
				( $k === $tab ? ' aria-current="true"' : '' ) . '>' . esc_html( $label ) . '</a></li>';
		}
		$out .= '</ul></nav>';

		// summary
		$sum = '';
		if ( $dg && ! empty( $dg['summary_sentences'] ) ) {
			$sum .= self::sentences( $dg['summary_sentences'], $cits, 'tk-sentences tk-sentences--digest' );
			if ( ! empty( $dg['topics'] ) ) {
				$sum .= '<h3 class="tk-sub">' . esc_html__( 'נושאים בדיון', 'trial-knowledge' ) . '</h3><ul class="tk-topics">';
				foreach ( array_slice( (array) $dg['topics'], 0, 12 ) as $tp ) {
					$sum .= '<li>' . esc_html( $tp ) . '</li>';
				}
				$sum .= '</ul>';
			}
			$sum .= '<p class="tk-muted tk-small">' . esc_html__( 'התקציר נכתב בעזרת מודל שפה מתוך הפרוטוקול, וכל משפט בו מקושר לעמוד שבו הוא מופיע. המקור הוא הקובע.', 'trial-knowledge' ) . '</p>';
		} else {
			$sum .= '<p class="tk-muted">' . esc_html__( 'טרם פורסם תקציר לדיון זה. הפרוטוקול המלא זמין בלשונית "הפרוטוקול המלא".', 'trial-knowledge' ) . '</p>';
		}
		$out .= self::tab_panel( 'summary', $sum, $tab );

		// Q/A
		$xs = (array) ( $opts['exchanges'] ?? array() );
		if ( $xs ) {
			$qa = self::exchanges( $xs, $cits );
		} elseif ( $dg && ! empty( $dg['notable_exchanges'] ) ) {
			$qa = '<ol class="tk-qa tk-qa--links">';
			foreach ( $dg['notable_exchanges'] as $x ) {
				$qa .= '<li class="tk-qa__item">' . self::relation_badge( $x['answer_relation'] ?? '' ) . ' ' .
					( ! empty( $x['interpreted_proposition'] ) ? '<span class="tk-glossable">' . esc_html( $x['interpreted_proposition'] ) . '</span> ' : '' ) .
					self::chips( array( $x['question_unit_id'] ?? '', $x['answer_unit_id'] ?? '' ), $cits ) . '</li>';
			}
			$qa .= '</ol>';
		} else {
			$qa = '<p class="tk-muted">' . esc_html__( 'לא סומנו שאלות ותשובות מרכזיות בדיון זה.', 'trial-knowledge' ) . '</p>';
		}
		$out .= self::tab_panel( 'qa', $qa, $tab );

		// full transcript (pager keeps the tab)
		if ( is_array( $t ) && isset( $t['units'] ) ) {
			$full = TK_Render::transcript( $t, add_query_arg( 'tk_tab', 'full', $base ), 'tk-tab-full' );
		} else {
			$full = TK_Render::unavailable();
		}
		$out .= self::tab_panel( 'full', $full, $tab );

		// source document
		$out .= self::tab_panel( 'source', self::source_info( $h, is_array( $t ) ? $t : array() ), $tab );
		return $out . '</div></div>';
	}

	private static function tab_panel( $k, $body, $active ) {
		return '<section class="tk-tabs__panel' . ( $k === $active ? ' is-active' : '' ) . '" id="tk-tab-' . esc_attr( $k ) . '" data-tab="' . esc_attr( $k ) . '" aria-labelledby="tk-tabh-' . esc_attr( $k ) . '">' .
			'<h2 class="tk-tabs__h" id="tk-tabh-' . esc_attr( $k ) . '">' . esc_html( self::TABS[ $k ] ) . '</h2>' . $body . '</section>';
	}

	private static function source_info( array $h, array $t ) {
		$doc = (array) ( $t['document'] ?? array() );
		$sv  = $doc['source_version_id'] ?? ( $h['source_version_id'] ?? '' );
		$out = '<dl class="tk-docinfo">';
		if ( ! empty( $doc['title'] ) ) {
			$out .= '<div><dt>' . esc_html__( 'כותרת', 'trial-knowledge' ) . '</dt><dd>' . esc_html( $doc['title'] ) . '</dd></div>';
		}
		$out .= '<div><dt>' . esc_html__( 'סוג', 'trial-knowledge' ) . '</dt><dd>' . esc_html( TK_Render::type_label( $doc['source_type'] ?? 'protocol' ) ) . '</dd></div>';
		if ( ! empty( $doc['source_owner'] ) ) {
			$out .= '<div><dt>' . esc_html__( 'מקור', 'trial-knowledge' ) . '</dt><dd>' . esc_html( $doc['source_owner'] ) . '</dd></div>';
		}
		$date = $doc['document_date'] ?? ( $h['hearing_date'] ?? '' );
		if ( $date ) {
			$out .= '<div><dt>' . esc_html__( 'תאריך', 'trial-knowledge' ) . '</dt><dd>' . self::time_tag( $date ) . '</dd></div>';
		}
		$pages = $t['page_count'] ?? ( $doc['page_count'] ?? 0 );
		if ( $pages ) {
			$out .= '<div><dt>' . esc_html__( 'עמודים', 'trial-knowledge' ) . '</dt><dd>' . (int) $pages . '</dd></div>';
		}
		if ( ! empty( $doc['court_record_status'] ) ) {
			$out .= '<div><dt>' . esc_html__( 'מעמד בתיק', 'trial-knowledge' ) . '</dt><dd>' . esc_html( TK_Render::RECORD[ $doc['court_record_status'] ] ?? '' ) . '</dd></div>';
		}
		if ( ! empty( $doc['content_sha256'] ) ) {
			$out .= '<div><dt>SHA-256</dt><dd><code>' . esc_html( substr( $doc['content_sha256'], 0, 16 ) ) . '…</code></dd></div>';
		}
		$out .= '</dl><p class="tk-actions-row">';
		if ( ! empty( $t['pdf_url'] ) ) {
			$out .= '<a class="tk-button tk-button--pdf" href="' . esc_url( $t['pdf_url'] ) . '" rel="nofollow">' . esc_html__( 'PDF המקורי', 'trial-knowledge' ) . '</a> ';
		}
		if ( $sv && preg_match( '/^sv_[0-9a-f]{26}$/', $sv ) ) {
			$out .= '<a class="tk-button" href="' . esc_url( TK_Public_Pages::url( 'document', $sv ) ) . '">' . esc_html__( 'לעמוד המסמך', 'trial-knowledge' ) . '</a>';
		}
		return $out . '</p>';
	}
}
