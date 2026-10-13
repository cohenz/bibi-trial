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
		'alleged'    => 'מה טוען כתב האישום?',
		'people'     => 'מי מעורב?',
		'charges'    => 'האישומים',
		'events'     => 'ציר הזמן של התיק',
		'role'       => 'מה הקשר לתיק?',
		'testimony'  => 'עיקרי העדות',
	);

	const KINDS = array(
		'indictment_fact' => 'לפי כתב האישום',
		'indictment'      => 'כתב אישום',
		'hearing'         => 'דיון',
		'hearing_day'     => 'יום דיון (לפי הודעה)',
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
		'people'    => 'מי ומי באולם?',
		'documents' => 'מסמכים',
	);

	const TABS = array(
		'summary' => 'בקצרה',
		'qa'      => 'שאלות ותשובות מרכזיות',
		'full'    => 'הפרוטוקול המלא',
		'source'  => 'מסמך המקור',
	);

	const NEUTRAL = 'כתב אישום הוא טענות התביעה. נאשם בחזקת חפות כל עוד לא הוכרעה אשמתו.';

	/** Witness groups on the witnesses page, in trial order (TK_Render_Nav::witness_stage()). */
	const STAGE_GROUPS = array(
		'prosecution' => 'עדי התביעה',
		'defendant'   => 'הנאשם',
		'defense'     => 'עדי ההגנה',
		'other'       => 'עדים נוספים מאז תחילת עדות הנאשם',
	);

	/** Witness side as named in court notices (2.4). */
	const SIDES = array(
		'prosecution' => 'מטעם התביעה',
		'defense'     => 'מטעם ההגנה',
		'court'       => 'מטעם בית המשפט',
	);

	const SIDES_SHORT = array(
		'prosecution' => 'תביעה',
		'defense'     => 'הגנה',
	);

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
		return ( ! $to || $to === $from ) ? self::fmt_date( $from ) : TK_Render::nrange( self::fmt_date( $from ), self::fmt_date( $to ) );
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
	 * Sources of an item as one pill at its end (2.6; replaced one chip per page).
	 *
	 * @param array $ids  source unit ids.
	 * @param array $cits cit_map().
	 */
	public static function chips( $ids, array $cits ) {
		$items = array();
		$seen  = array();
		foreach ( (array) $ids as $id ) {
			if ( ! preg_match( '/^su_[0-9a-f]{26}$/', (string) $id ) || isset( $seen[ $id ] ) ) {
				continue;
			}
			$seen[ $id ] = 1;
			$items[]     = array( 'id' => $id, 'c' => $cits[ $id ] ?? null );
		}
		return TK_Render::sources_pill( $items );
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
		if ( $slug && TK_Guides::name_for( $slug ) ) {
			$name = TK_Guides::name_for( $slug ); // one spelling per person, whatever the protocol printed
		}
		$text = esc_html( $name ) . ( $label ? ' <span class="tk-badge tk-badge--label">' . esc_html( $label ) . '</span>' : '' );
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
	 * @param array $opts urls: glossary, timeline, witnesses, docs (type → url); ask_html;
	 *                    latest_day (timeline hearing_day event newer than the latest transcribed hearing, see latest_hearing_day());
	 *                    latest_docs (/v2/documents items, substantive, newest first).
	 */
	public static function start( array $g, array $opts = array() ) {
		$urls = self::entry_urls( $opts );
		$ws   = (array) ( $g['witnesses'] ?? array() );
		$out  = '<div class="tk-guide tk-start" dir="rtl" lang="he">';
		$out .= TK_Render_Nav::bar( 'home' );

		// intro + neutrality line + a door for newcomers
		$out .= '<header class="tk-intro">';
		$out .= '<p class="tk-intro__lead tk-glossable">' . esc_html__( 'מדריך נגיש למשפט הפלילי של בנימין נתניהו (ת״פ 67104-01-20, בית המשפט המחוזי בירושלים). כל מה שכתוב כאן נשען על תיק בית המשפט: ליד כל משפט יש קישור לעמוד ולשורות במקור — בפרוטוקולים, בכתב האישום ובהחלטות.', 'trial-knowledge' ) . '</p>';
		$out .= '<p class="tk-neutral" role="note"><strong>' . esc_html( self::NEUTRAL ) . '</strong> <a href="' . esc_url( $urls['glossary'] . '#term-presumption-of-innocence' ) . '">' . esc_html__( 'מהי חזקת החפות?', 'trial-knowledge' ) . '</a></p>';
		$out .= '<p class="tk-newcomer"><a href="' . esc_url( $urls['glossary'] . '#tk-steps' ) . '">' . esc_html__( 'חדשים כאן? המשפט הפלילי בחמישה צעדים', 'trial-knowledge' ) . ' <span aria-hidden="true">←</span></a></p>';
		$out .= '</header>';

		// where the trial stands: stages, then the latest hearing and the counts
		$lh    = $g['latest_hearing'] ?? null;
		$stand = TK_Render_Nav::stages_html( $ws, $lh['hearing_date'] ?? '' ) . self::status( $g, $urls, $opts['latest_day'] ?? null );
		$out  .= self::section( 'tk-status', __( 'איפה המשפט עומד?', 'trial-knowledge' ), $stand );

		// three cases; the indictment overview folded under them
		$by_key = array();
		foreach ( (array) ( $g['cases'] ?? array() ) as $c ) {
			$by_key[ (string) $c['key'] ] = $c;
		}
		$cards = '<p class="tk-sec__note">' . esc_html__( 'התיאורים מבוססים על כתב האישום, כלומר על טענות התביעה.', 'trial-knowledge' ) . '</p><div class="tk-cards">';
		foreach ( TK_Guides::CASE_KEYS as $key ) {
			$cards .= self::case_card( $key, $by_key[ $key ] ?? null, self::cit_map( $g['indictment']['citations'] ?? array() ) );
		}
		$cards .= '</div>';
		if ( ! empty( $g['indictment'] ) ) {
			$cards .= '<details class="tk-fold" id="tk-indictment"><summary class="tk-fold__s">' . esc_html__( 'כתב האישום בקצרה: מי הנאשמים ומה מיוחס להם?', 'trial-knowledge' ) . '</summary>' . self::indictment( $g['indictment'] ) . '</details>';
		}
		$out .= self::section( 'tk-cases', __( 'שלושת התיקים', 'trial-knowledge' ), $cards );

		// key witnesses, not all of them
		if ( $ws ) {
			$out .= self::section( 'tk-witnesses', __( 'עדים מרכזיים', 'trial-knowledge' ), self::key_witnesses( $ws, 8 ) .
				'<p><a class="tk-more" href="' . esc_url( $urls['witnesses'] ) . '">' . esc_html( sprintf( __( 'לכל %d העדים, לפי שלבי המשפט', 'trial-knowledge' ), count( $ws ) ) ) . ' <span aria-hidden="true">←</span></a></p>' );
		}

		// entry links
		$out .= self::section( 'tk-entries', __( 'לאן ממשיכים?', 'trial-knowledge' ), self::entries( $g, $urls, (array) ( $opts['latest_docs'] ?? array() ) ) );

		if ( ! empty( $opts['ask_html'] ) ) {
			$out .= '<section class="tk-sec tk-sec--ask" id="tk-ask" aria-labelledby="tk-ask-h"><h2 class="tk-sec__h" id="tk-ask-h">' . esc_html__( 'שאלו את המאגר', 'trial-knowledge' ) . '</h2>' . $opts['ask_html'] . '</section>';
		}
		return $out . '</div>';
	}

	/**
	 * The witnesses with the most published testimony days, each with the stage of the trial they belong to.
	 *
	 * @param array $ws /v2/guide witnesses.
	 * @param int   $n  how many.
	 */
	public static function key_witnesses( array $ws, $n = 8 ) {
		$top = $ws;
		usort(
			$top,
			static function ( $a, $b ) {
				return ( (int) ( $b['hearing_count'] ?? 0 ) <=> (int) ( $a['hearing_count'] ?? 0 ) ) ?: strcmp( (string) ( $a['first_date'] ?? '' ), (string) ( $b['first_date'] ?? '' ) );
			}
		);
		$top    = array_slice( $top, 0, $n );
		$labels = self::STAGE_GROUPS;
		$out    = '<ul class="tk-keyw">';
		foreach ( $top as $w ) {
			$stage = TK_Render_Nav::witness_stage( $w, $ws );
			$out  .= '<li class="tk-keyw__item"><a class="tk-keyw__name" href="' . esc_url( TK_Public_Pages::url( 'witness', $w['slug'] ) ) . '">' . esc_html( $w['name'] ) . '</a>' .
				'<span class="tk-keyw__meta">' . esc_html( $labels[ $stage ] ?? '' ) . ' · ' . esc_html( self::days_label( (int) ( $w['hearing_count'] ?? 0 ) ) ) . '</span>' .
				( ! empty( $w['cases'] ) ? '<span class="tk-keyw__cases">' . self::case_badges( $w['cases'], false ) . '</span>' : '' ) . '</li>';
		}
		return $out . '</ul>';
	}

	/** "יום עדות אחד" / "28 ימי עדות". */
	public static function days_label( $n ) {
		return 1 === (int) $n ? __( 'יום עדות אחד', 'trial-knowledge' ) : sprintf( __( '%d ימי עדות', 'trial-knowledge' ), (int) $n );
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

	/**
	 * The newest hearing day known only from a court notice, when it is later than $after (the latest transcribed hearing).
	 *
	 * @param array  $t     /v2/guide/timeline.
	 * @param string $after YYYY-MM-DD or ''.
	 * @return array|null Timeline event.
	 */
	public static function latest_hearing_day( array $t, $after = '' ) {
		$best = null;
		foreach ( (array) ( $t['events'] ?? array() ) as $e ) {
			if ( 'hearing_day' !== ( $e['kind'] ?? '' ) || ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', (string) ( $e['date'] ?? '' ) ) ) {
				continue;
			}
			if ( ( ! $best || strcmp( $e['date'], $best['date'] ) > 0 ) && strcmp( $e['date'], (string) $after ) > 0 ) {
				$best = $e;
			}
		}
		return $best;
	}

	private static function latest_day_html( array $e ) {
		$title = (string) ( $e['title'] ?? '' );
		$title = preg_replace( '/^יום דיון:\s*/u', '', $title );
		$url   = self::event_url( $e );
		$out   = '<p class="tk-latest-day"><span class="tk-latest-day__k">' . esc_html__( 'יום הדיון האחרון שידוע עליו:', 'trial-knowledge' ) . '</span> ' .
			'<strong>' . self::time_tag( $e['date'] ) . '</strong>' . ( '' !== $title ? ' · ' . ( $url ? '<a href="' . esc_url( $url ) . '">' . esc_html( $title ) . '</a>' : esc_html( $title ) ) : '' ) .
			' <span class="tk-muted">' . esc_html__( '(לפי הודעת בית המשפט; הפרוטוקול טרם פורסם)', 'trial-knowledge' ) . '</span></p>';
		return $out;
	}

	private static function status( array $g, array $urls, $latest_day = null ) {
		$out   = '';
		if ( is_array( $latest_day ) && ! empty( $latest_day['date'] ) ) {
			$out .= self::latest_day_html( $latest_day );
		}
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

	private static function entries( array $g, array $urls, array $latest_docs = array() ) {
		$docs  = $urls['docs'];
		$tiles = array(
			array( $urls['timeline'], __( 'ציר הזמן', 'trial-knowledge' ), __( 'מה קרה ומתי: האירועים לפי כתב האישום, והדיונים וההחלטות במשפט.', 'trial-knowledge' ) ),
			array( $urls['witnesses'], __( 'עדים', 'trial-knowledge' ), __( 'מי העיד, מתי, ומה עלה בעדות.', 'trial-knowledge' ) ),
			array( $urls['glossary'], __( 'מילון מונחים', 'trial-knowledge' ), __( 'חקירה נגדית, מוצג, הפרת אמונים — במילים פשוטות.', 'trial-knowledge' ) ),
			array( TK_Public_Pages::section_url( '315' ), __( '315 האירועים', 'trial-knowledge' ), __( 'אירועי הסיקור שבנספח לתיק 4000, ומה נשאר מהם לפי פרויקט 315.', 'trial-knowledge' ) ),
			array( '#tk-ask', __( 'שאלו את המאגר', 'trial-knowledge' ), __( 'שאלה חופשית; התשובה מצטטת רק חומר שפורסם.', 'trial-knowledge' ) ),
		);
		$out = '<ul class="tk-entries">';
		foreach ( $tiles as $t ) {
			$out .= '<li class="tk-entry"><a class="tk-entry__a" href="' . esc_url( $t[0] ) . '"><span class="tk-entry__t">' . esc_html( $t[1] ) . '</span><span class="tk-entry__d">' . esc_html( $t[2] ) . '</span></a></li>';
		}
		$labels = array( 'decision' => 'החלטות', 'motion' => 'בקשות', 'response' => 'תגובות', 'notice' => 'הודעות' );
		$counts = (array) ( $g['counts']['documents'] ?? array() );
		$out   .= '<li class="tk-entry tk-entry--docs"><span class="tk-entry__t">' . esc_html__( 'מסמכים', 'trial-knowledge' ) . '</span><span class="tk-entry__d">' . esc_html__( 'החלטות בית המשפט ובקשות הצדדים: תקציר קצר לכל מסמך, והמסמך המלא.', 'trial-knowledge' ) . '</span><span class="tk-entry__links">';
		foreach ( $labels as $t => $l ) {
			$out .= '<a class="tk-pill" href="' . esc_url( $docs[ $t ] ) . '">' . esc_html( $l ) . ( ! empty( $counts[ $t ] ) ? ' <span class="tk-pill__n">' . (int) $counts[ $t ] . '</span>' : '' ) . '</a>';
		}
		$out .= '</span>';
		if ( $latest_docs ) {
			$out .= '<span class="tk-entry__sub">' . esc_html__( 'האחרונים:', 'trial-knowledge' ) . '</span><ul class="tk-entry__docs">';
			foreach ( array_slice( $latest_docs, 0, 3 ) as $d ) {
				if ( empty( $d['source_version_id'] ) ) {
					continue;
				}
				$out .= '<li><a href="' . esc_url( TK_Public_Pages::url( 'document', $d['source_version_id'] ) ) . '">' . esc_html( TK_Render::display_title( $d ) ) . '</a>' .
					( ! empty( $d['document_date'] ) ? ' <span class="tk-muted">' . self::time_tag( $d['document_date'] ) . '</span>' : '' ) . '</li>';
			}
			$out .= '</ul>';
		}
		return $out . '</li></ul>';
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
			$out   .= '<li class="tk-wlist__item' . ( $is_cur ? ' tk-wlist__item--current' : '' ) . '" data-cases="' . esc_attr( implode( ' ', (array) ( $w['cases'] ?? array() ) ) ) . '">';
			$out   .= '<a class="tk-wlist__name" href="' . esc_url( TK_Public_Pages::url( 'witness', $w['slug'] ) ) . '"' . ( $is_cur ? ' aria-current="page"' : '' ) . '>' . esc_html( $w['name'] ) . '</a>';
			if ( ! empty( $w['label'] ) ) {
				$out .= ' <span class="tk-badge tk-badge--label">' . esc_html( $w['label'] ) . '</span>';
			}
			$side = (string) ( $w['side'] ?? '' );
			if ( isset( self::SIDES_SHORT[ $side ] ) ) {
				$out .= ' <span class="tk-badge tk-badge--side tk-badge--' . esc_attr( $side ) . '" title="' . esc_attr( self::SIDES[ $side ] ) . '">' . esc_html( self::SIDES_SHORT[ $side ] ) . '</span>';
			}
			$parts = array( self::witness_counts( $n, (int) ( $w['appearance_count'] ?? 0 ) ) );
			$range = self::date_range( $w['first_date'] ?? '', $w['last_date'] ?? '' );
			if ( $range ) {
				$parts[] = $range;
			}
			$out .= ' <span class="tk-wlist__meta">' . esc_html( implode( ' · ', array_filter( $parts ) ) ) . '</span>';
			if ( ! empty( $w['cases'] ) ) {
				$out .= ' <span class="tk-wlist__cases">' . self::case_badges( $w['cases'], false ) . '</span>';
			}
			$out .= '</li>';
		}
		return $out . '</ul>';
	}

	/**
	 * All witnesses by stage of the trial (prosecution, the defendant, defence), the most heard first; witnesses heard
	 * on one day are folded. Case filter buttons (assets/reading.js) hide the others; without JS everything shows.
	 *
	 * @param array $ws /v2/guide witnesses.
	 */
	public static function witnesses_grouped( array $ws ) {
		if ( ! $ws ) {
			return '<p class="tk-empty">' . esc_html__( 'עדיין אין עדים בחומר שפורסם.', 'trial-knowledge' ) . '</p>';
		}
		$groups = array();
		foreach ( $ws as $w ) {
			$groups[ TK_Render_Nav::witness_stage( $w, $ws ) ][] = $w;
		}
		$out  = '<div class="tk-wgroups" data-tk-filter dir="rtl" lang="he">';
		$out .= '<div class="tk-filter" role="group" aria-label="' . esc_attr__( 'סינון לפי תיק', 'trial-knowledge' ) . '"><span class="tk-muted">' . esc_html__( 'תיק:', 'trial-knowledge' ) . '</span> ' .
			'<button type="button" class="tk-filter__b is-on" data-case="" aria-pressed="true">' . esc_html__( 'הכול', 'trial-knowledge' ) . '</button>';
		foreach ( TK_Guides::CASE_KEYS as $k ) {
			$out .= ' <button type="button" class="tk-filter__b tk-case--' . esc_attr( $k ) . '" data-case="' . esc_attr( $k ) . '" aria-pressed="false">' . esc_html( $k ) . '</button>';
		}
		$out .= '</div>';
		foreach ( self::STAGE_GROUPS as $key => $label ) {
			if ( empty( $groups[ $key ] ) ) {
				continue;
			}
			$list = $groups[ $key ];
			usort(
				$list,
				static function ( $a, $b ) {
					$na = (int) ( $a['hearing_count'] ?? 0 ) + (int) ( $a['appearance_count'] ?? 0 );
					$nb = (int) ( $b['hearing_count'] ?? 0 ) + (int) ( $b['appearance_count'] ?? 0 );
					return ( $nb <=> $na ) ?: strcmp( (string) ( $a['first_date'] ?? '' ), (string) ( $b['first_date'] ?? '' ) );
				}
			);
			$main = $once = array();
			foreach ( $list as $w ) {
				if ( (int) ( $w['hearing_count'] ?? 0 ) + (int) ( $w['appearance_count'] ?? 0 ) > 1 || 'defendant' === $key ) {
					$main[] = $w;
				} else {
					$once[] = $w;
				}
			}
			$out .= '<section class="tk-sec tk-wgroup" id="tk-wg-' . esc_attr( $key ) . '"><h2 class="tk-sec__h">' . esc_html( $label ) .
				' <span class="tk-sec__count">' . count( $list ) . '</span></h2>';
			if ( $main ) {
				$out .= self::witnesses_list( $main );
			}
			if ( $once ) {
				$out .= '<details class="tk-fold"><summary class="tk-fold__s">' . esc_html( sprintf( __( 'עוד %d עדים שהעידו יום אחד', 'trial-knowledge' ), count( $once ) ) ) . '</summary>' .
					self::witnesses_list( $once, array( 'compact' => true ) ) . '</details>';
			}
			$out .= '</section>';
		}
		return $out . '</div>';
	}

	/**
	 * "3 דיונים מתומללים · 2 ימי עדות נוספים" — transcribed hearings and days known only from court notices.
	 *
	 * @param int $hearings    hearing_count.
	 * @param int $appearances appearance_count (days without a transcript).
	 */
	public static function witness_counts( $hearings, $appearances ) {
		$parts = array();
		if ( $hearings ) {
			$parts[] = self::days_label( $hearings );
		}
		if ( $appearances ) {
			$parts[] = 1 === $appearances ? __( 'עוד יום אחד לפי הודעת בית המשפט', 'trial-knowledge' ) : sprintf( __( 'עוד %d ימים לפי הודעות בית המשפט', 'trial-knowledge' ), $appearances );
			if ( ! $hearings ) {
				$parts = array( 1 === $appearances ? __( 'יום עדות אחד לפי הודעת בית המשפט', 'trial-knowledge' ) : sprintf( __( '%d ימי עדות לפי הודעות בית המשפט', 'trial-knowledge' ), $appearances ) );
			}
		}
		return $parts ? implode( ' · ', $parts ) : __( 'אין עדיין פרוטוקול של העדות', 'trial-knowledge' );
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
		$out .= TK_Render_Nav::bar( 'witnesses', array( array( __( 'עדים', 'trial-knowledge' ), TK_Public_Pages::section_url( 'witnesses' ) ), array( $w['name'], '' ) ) );
		$out .= '<header class="tk-head"><p class="tk-kicker">' . esc_html( self::STAGE_GROUPS[ TK_Render_Nav::witness_stage( self::summary_of( $w, $all ), $all ) ] ?? __( 'עדים במשפט', 'trial-knowledge' ) ) . '</p>';
		$out .= '<h1 class="tk-head__title">' . esc_html( $w['name'] ) . '</h1>';
		$meta = array();
		if ( ! empty( $w['label'] ) ) {
			$meta[] = '<span class="tk-badge tk-badge--label">' . esc_html( $w['label'] ) . '</span>';
		}
		if ( ! empty( $w['cases'] ) ) {
			$meta[] = self::case_badges( $w['cases'] );
		}
		$side = (string) ( $w['side'] ?? '' );
		if ( isset( self::SIDES[ $side ] ) ) {
			$meta[] = '<span class="tk-badge tk-badge--side tk-badge--' . esc_attr( $side ) . '">' . esc_html( self::SIDES[ $side ] ) . '</span>';
		}
		$hearings = (array) ( $w['hearings'] ?? array() );
		$apps     = (array) ( $w['appearances'] ?? array() );
		$n        = count( $hearings );
		$only     = array_values( array_filter( $apps, static function ( $a ) { return empty( $a['has_transcript'] ); } ) );
		$dates    = array_merge( array_column( $hearings, 'hearing_date' ), array_column( $only, 'date' ) );
		sort( $dates );
		$meta[] = '<span class="tk-muted">' . esc_html( self::witness_counts( $n, count( $only ) ) ) . ( $dates ? ' · ' . esc_html( self::date_range( $dates[0], end( $dates ) ) ) : '' ) . '</span>';
		$out   .= '<p class="tk-head__meta">' . implode( ' ', $meta ) . '</p></header>';

		// layer 1: who, and the gist of the testimony (first points; the rest folded)
		$role = self::block( $w, 'role' );
		$test = self::block( $w, 'testimony' );
		if ( $role ) {
			$out .= self::section( 'tk-w-role', self::BLOCKS['role'], self::prose( $role, $cits ) );
		}
		if ( $test ) {
			$body = self::prose( array_slice( $test, 0, 3 ), $cits );
			if ( count( $test ) > 3 ) {
				$body .= '<details class="tk-fold"><summary class="tk-fold__s">' . esc_html( sprintf( __( 'עוד %d נקודות מהעדות', 'trial-knowledge' ), count( $test ) - 3 ) ) . '</summary>' . self::prose( array_slice( $test, 3 ), $cits ) . '</details>';
			}
			$out .= self::section( 'tk-w-testimony', self::BLOCKS['testimony'], $body );
		}
		if ( ! $role && ! $test ) {
			if ( $n ) {
				$out .= '<p class="tk-notice tk-notice--soft">' . esc_html__( 'סקירה של העדות בהכנה. בינתיים מוצגים כאן עיקרי ימי העדות, מתוך תקצירי הדיונים שפורסמו.', 'trial-knowledge' ) . '</p>';
			} elseif ( $apps ) {
				$out .= '<p class="tk-notice tk-notice--soft">' . esc_html__( 'עדיין לא פורסם פרוטוקול של העדות. ימי העדות שלהלן ידועים מהודעות בית המשפט.', 'trial-knowledge' ) . '</p>';
			}
		}

		// layer 2: notable questions and answers
		$xs = (array) ( $w['notable_exchanges'] ?? array() );
		if ( $xs ) {
			$body = self::exchanges( array_slice( $xs, 0, 3 ), $cits, true );
			if ( count( $xs ) > 3 ) {
				$body .= '<details class="tk-fold"><summary class="tk-fold__s">' . esc_html( sprintf( __( 'עוד %d שאלות ותשובות', 'trial-knowledge' ), count( $xs ) - 3 ) ) . '</summary>' . self::exchanges( array_slice( $xs, 3 ), $cits, true ) . '</details>';
			}
			$out .= self::section( 'tk-w-qa', __( 'שאלות ותשובות מרכזיות', 'trial-knowledge' ), $body );
		}

		// layer 3: every day of testimony, transcribed or known from a notice, by month (folded after the first)
		$days = array();
		foreach ( $hearings as $h ) {
			$days[] = array( 'date' => $h['hearing_date'], 'h' => $h );
		}
		foreach ( $only as $a ) {
			$days[] = array( 'date' => $a['date'], 'a' => $a );
		}
		usort(
			$days,
			static function ( $a, $b ) {
				return strcmp( (string) $a['date'], (string) $b['date'] );
			}
		);
		if ( $days ) {
			$months = array();
			foreach ( $days as $d ) {
				$months[ substr( (string) $d['date'], 0, 7 ) ][] = $d;
			}
			$body = count( $days ) > 1 ? '<p class="tk-sec__note">' . esc_html__( 'לכל יום: מה עלה בו לפי תקציר הדיון, וקישור לדף הדיון ולפרוטוקול המלא.', 'trial-knowledge' ) . '</p>' : '';
			$i    = 0;
			foreach ( $months as $ym => $list ) {
				$items = '';
				foreach ( $list as $d ) {
					$items .= self::testimony_day( $d, $cits );
				}
				$label = self::fmt_date( $ym . '-01', 'month' ) . ' · ' . self::days_label( count( $list ) );
				$body .= count( $months ) > 1
					? '<details class="tk-fold tk-month"' . ( 0 === $i ? ' open' : '' ) . '><summary class="tk-fold__s">' . esc_html( $label ) . '</summary><ol class="tk-hlist">' . $items . '</ol></details>'
					: '<ol class="tk-hlist">' . $items . '</ol>';
				++$i;
			}
			$out .= self::section( 'tk-w-hearings', __( 'ימי העדות', 'trial-knowledge' ), $body );
		}

		// next / previous witness in the same stage, and the full list
		if ( $all ) {
			$out .= self::witness_pager( $w['slug'], $all );
		}
		return $out . '</article>';
	}

	/** The /v2/guide summary of a witness page's person (for its stage), or the page itself. */
	private static function summary_of( array $w, array $all ) {
		foreach ( $all as $x ) {
			if ( ( $x['slug'] ?? '' ) === ( $w['slug'] ?? '' ) ) {
				return $x;
			}
		}
		$dates = array_column( (array) ( $w['hearings'] ?? array() ), 'hearing_date' );
		sort( $dates );
		return array( 'label' => $w['label'] ?? null, 'side' => $w['side'] ?? null, 'first_date' => $dates[0] ?? '' );
	}

	/** One testimony day on a witness page. */
	private static function testimony_day( array $d, array $cits ) {
		if ( isset( $d['h'] ) ) {
			$h    = $d['h'];
			$url  = TK_Public_Pages::url( 'hearing', $h['id'] );
			$sent = (array) ( $h['digest_sentences'] ?? array() );
			$out  = '<li class="tk-hlist__item"><h3 class="tk-hlist__h"><a href="' . esc_url( $url ) . '">' . esc_html( sprintf( __( 'דיון מיום %s', 'trial-knowledge' ), self::fmt_date( $h['hearing_date'] ) ) ) . '</a></h3>';
			if ( $sent ) {
				$out .= self::sentences( array_slice( $sent, 0, 1 ), $cits );
				if ( count( $sent ) > 1 ) {
					$out .= '<details class="tk-fold tk-fold--inline"><summary class="tk-fold__s">' . esc_html__( 'עוד מהיום הזה', 'trial-knowledge' ) . '</summary>' . self::sentences( array_slice( $sent, 1 ), $cits ) . '</details>';
				}
			} else {
				$out .= '<p class="tk-muted">' . esc_html__( 'טרם פורסם תקציר לדיון זה.', 'trial-knowledge' ) . '</p>';
			}
			return $out . '</li>';
		}
		$a   = $d['a'];
		$sv  = (string) ( $a['source_version_id'] ?? '' );
		$out = '<li class="tk-hlist__item tk-hlist__item--notice"><h3 class="tk-hlist__h">' . esc_html( sprintf( __( 'יום עדות %s', 'trial-knowledge' ), self::fmt_date( $a['date'] ) ) ) . '</h3>';
		if ( ! empty( $a['description'] ) ) {
			$out .= '<p class="tk-glossable">' . esc_html( $a['description'] ) . '</p>';
		}
		$out .= '<p class="tk-muted tk-small">' . esc_html__( 'ידוע מהודעת בית המשפט; הפרוטוקול טרם פורסם.', 'trial-knowledge' ) .
			( preg_match( '/^sv_[0-9a-f]{26}$/', $sv ) ? ' <a href="' . esc_url( TK_Public_Pages::url( 'document', $sv ) ) . '">' . esc_html__( 'להודעה', 'trial-knowledge' ) . '</a>' : '' ) . '</p>';
		return $out . '</li>';
	}

	/** Previous / next witness of the same stage (the order of the witnesses page) and a link to all witnesses. */
	public static function witness_pager( $slug, array $all ) {
		$stage = '';
		foreach ( $all as $x ) {
			if ( ( $x['slug'] ?? '' ) === $slug ) {
				$stage = TK_Render_Nav::witness_stage( $x, $all );
			}
		}
		$same = array_values( array_filter( $all, static function ( $x ) use ( $stage, $all ) { return TK_Render_Nav::witness_stage( $x, $all ) === $stage; } ) );
		$pos  = array_search( $slug, array_column( $same, 'slug' ), true );
		$out  = '<nav class="tk-pager2" aria-label="' . esc_attr__( 'עדים נוספים', 'trial-knowledge' ) . '">';
		if ( false !== $pos && $pos > 0 ) {
			$p    = $same[ $pos - 1 ];
			$out .= '<a class="tk-pager2__prev" href="' . esc_url( TK_Public_Pages::url( 'witness', $p['slug'] ) ) . '"><span class="tk-muted">' . esc_html__( 'העד הקודם', 'trial-knowledge' ) . '</span> ' . esc_html( $p['name'] ) . '</a>';
		}
		$out .= '<a class="tk-pager2__all" href="' . esc_url( TK_Public_Pages::section_url( 'witnesses' ) ) . '">' . esc_html__( 'לכל העדים', 'trial-knowledge' ) . '</a>';
		if ( false !== $pos && $pos < count( $same ) - 1 ) {
			$nx   = $same[ $pos + 1 ];
			$out .= '<a class="tk-pager2__next" href="' . esc_url( TK_Public_Pages::url( 'witness', $nx['slug'] ) ) . '"><span class="tk-muted">' . esc_html__( 'העד הבא', 'trial-knowledge' ) . '</span> ' . esc_html( $nx['name'] ) . '</a>';
		}
		return $out . '</nav>';
	}

	/**
	 * Days a witness testified according to court notices (2.4): date, side, description, the notice.
	 *
	 * @param array $apps /v2/guide/witnesses/{slug} appearances.
	 */
	public static function appearances( array $apps ) {
		usort(
			$apps,
			static function ( $a, $b ) {
				return strcmp( (string) ( $a['date'] ?? '' ), (string) ( $b['date'] ?? '' ) );
			}
		);
		$out = '<p class="tk-sec__note">' . esc_html__( 'הודעות של בית המשפט שמתעדות מי העיד ומתי. הן לא מתעדות מה נאמר בעדות.', 'trial-knowledge' ) . '</p><ol class="tk-apps">';
		foreach ( $apps as $a ) {
			$side = (string) ( $a['side'] ?? '' );
			$out .= '<li class="tk-apps__item">';
			$out .= '<p class="tk-apps__head">' . ( ! empty( $a['date'] ) ? '<strong class="tk-apps__date">' . self::time_tag( $a['date'] ) . '</strong>' : '' );
			if ( isset( self::SIDES[ $side ] ) ) {
				$out .= ' <span class="tk-badge tk-badge--side tk-badge--' . esc_attr( $side ) . '">' . esc_html( self::SIDES[ $side ] ) . '</span>';
			}
			if ( ! empty( $a['has_transcript'] ) ) {
				$out .= ' <span class="tk-badge tk-badge--transcript">' . esc_html__( 'יש תמלול', 'trial-knowledge' ) . '</span>';
			}
			$out .= '</p>';
			if ( ! empty( $a['description'] ) ) {
				$out .= '<p class="tk-apps__desc tk-glossable">' . esc_html( $a['description'] ) . '</p>';
			}
			$sv = (string) ( $a['source_version_id'] ?? '' );
			if ( preg_match( '/^sv_[0-9a-f]{26}$/', $sv ) ) {
				$out .= '<p class="tk-apps__src"><span class="tk-muted">' . esc_html__( 'המקור:', 'trial-knowledge' ) . '</span> <a href="' . esc_url( TK_Public_Pages::url( 'document', $sv ) ) . '">' . esc_html( ! empty( $a['document_title'] ) ? $a['document_title'] : __( 'הודעת בית המשפט', 'trial-knowledge' ) ) . '</a></p>';
			}
			$out .= '</li>';
		}
		return $out . '</ol>';
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
		$out .= TK_Render_Nav::bar( 'cases', array( array( __( 'התיקים', 'trial-knowledge' ), home_url( '/#tk-cases' ) ), array( sprintf( __( 'תיק %s', 'trial-knowledge' ), $key ), '' ) ) );
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
			$secs['tk-c-alleged'] = array( self::BLOCKS['alleged'], self::prose( $x, $cits ) );
		}
		if ( $x = self::block( $c, 'charges' ) ) {
			$secs['tk-c-charges'] = array( self::BLOCKS['charges'], self::charges( $x, $cits ) );
		}
		if ( $x = self::block( $c, 'people' ) ) {
			$secs['tk-c-people'] = array( self::BLOCKS['people'], self::people( $x, $cits ) );
		}
		$ev = self::block( $c, 'events' );
		if ( $ev ) {
			$secs['tk-c-events'] = array( self::BLOCKS['events'], self::events( $ev, $cits ) .
				'<p><a class="tk-button" href="' . esc_url( $tl ) . '">' . esc_html__( 'התיק בציר הזמן המלא', 'trial-knowledge' ) . '</a></p>' );
		}
		if ( '4000' === (string) $key && class_exists( 'TK_P315' ) && TK_P315::data()['items'] ) {
			$secs['tk-c-315'] = array( __( '315 אירועי הסיקור', 'trial-knowledge' ), TK_P315::entry_card() );
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
				$name = '<a href="' . esc_url( TK_Public_Pages::url( 'witness', $slug ) ) . '">' . $name . '</a> <span class="tk-badge tk-badge--testified">' . esc_html__( 'העדות במשפט', 'trial-knowledge' ) . '</span>';
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
			$kind = isset( self::KINDS[ $e['kind'] ?? '' ] ) ? $e['kind'] : 'other';
			$nw   = array();
			foreach ( (array) ( $e['notice_witnesses'] ?? array() ) as $x ) {
				$x = is_array( $x ) ? ( $x['name'] ?? '' ) : $x;
				if ( is_string( $x ) && '' !== trim( $x ) ) {
					$nw[] = trim( $x );
				}
			}
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
				'sig'   => 'procedural' === ( $e['significance'] ?? '' ) ? 'procedural' : 'substantive',
				'nw'    => array_values( array_unique( $nw ) ),
			);
		}
		$cmap = array();
		foreach ( array_keys( $used ) as $id ) {
			$c           = $cits[ $id ];
			$cmap[ $id ] = array(
				'label' => sprintf( 'עמ׳ %d', (int) $c['page'] ),
				'title' => sprintf( 'עמ׳ %1$d, שורות %2$s', (int) $c['page'], TK_Render::nrange( (int) ( $c['line_start'] ?? 0 ), (int) ( $c['line_end'] ?? 0 ) ) ),
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
	 * Procedural documents are hidden by default (the JS toggle, or ?tk_all=1 without JS).
	 *
	 * @param array  $t    /v2/guide/timeline.
	 * @param string $case Preselected case filter.
	 * @param array  $opts all (bool: show procedural documents), show_url / hide_url (no-JS toggle links).
	 */
	public static function timeline( array $t, $case = '', array $opts = array() ) {
		$case    = TK_Guides::valid_case( $case ) ? $case : '';
		$all     = ! empty( $opts['all'] );
		$payload = self::timeline_payload( $t );
		$nproc   = 0;
		foreach ( $payload['events'] as $e ) {
			$nproc += 'procedural' === $e['sig'] ? 1 : 0;
		}
		$id      = 'tk-tl-' . substr( md5( (string) count( $payload['events'] ) . $case ), 0, 6 );
		$out     = '<div class="tk-tl" id="' . esc_attr( $id ) . '" dir="rtl" lang="he" data-case="' . esc_attr( $case ) . '" data-all="' . ( $all ? '1' : '0' ) . '">';
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
		if ( $nproc && ! $all && ! empty( $opts['show_url'] ) ) {
			$out .= '<p class="tk-doctoggle"><a href="' . esc_url( $opts['show_url'] ) . '" rel="nofollow">' . esc_html( sprintf( __( 'הצגת גם מסמכים פרוצדורליים (%d)', 'trial-knowledge' ), $nproc ) ) . '</a></p>';
		} elseif ( $nproc && $all && ! empty( $opts['hide_url'] ) ) {
			$out .= '<p class="tk-doctoggle"><a href="' . esc_url( $opts['hide_url'] ) . '">' . esc_html__( 'הסתרת מסמכים פרוצדורליים', 'trial-knowledge' ) . '</a></p>';
		}
		$year = null;
		$n    = 0;
		foreach ( $payload['events'] as $e ) {
			if ( ! $all && 'procedural' === $e['sig'] ) {
				continue;
			}
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
			$out  .= '<li class="tk-tl__fitem tk-tl__fitem--' . esc_attr( $e['track'] ) . ( 'hearing_day' === $e['kind'] ? ' tk-tl__fitem--notice' : '' ) . ( $e['cases'] ? ' tk-case--' . esc_attr( $e['cases'][0] ) : '' ) . '">' .
				self::time_tag( $e['date'], $e['p'] ) . ' <span class="tk-badge' . ( 'hearing_day' === $e['kind'] ? ' tk-badge--notice' : '' ) . '">' . esc_html( $track ) . '</span> ' . $title .
				( 'procedural' === $e['sig'] ? ' ' . TK_Render::procedural_badge() : '' ) .
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

	// ------------------------------------------------------------------ documents page (2.7)

	const DOC_TYPE_LABELS = array(
		'decision'   => 'החלטות',
		'motion'     => 'בקשות',
		'response'   => 'תגובות',
		'notice'     => 'הודעות',
		'indictment' => 'כתבי אישום',
		'affidavit'  => 'תצהירים',
		'exhibit'    => 'מוצגים',
		'other'      => 'אחר',
	);

	const DOCS_PER_PAGE = 30;

	/**
	 * All documents with filters that work as a plain GET form (no JS): type, year, words, procedural too.
	 *
	 * @param array $items /v2/documents items (all types), newest first.
	 * @param array $q     type, year, q, all (bool), p (page, 1-based).
	 * @param string $base URL of the page.
	 */
	public static function documents_page( array $items, array $q, $base ) {
		$type  = isset( self::DOC_TYPE_LABELS[ $q['type'] ?? '' ] ) ? $q['type'] : '';
		$year  = preg_match( '/^\d{4}$/', (string) ( $q['year'] ?? '' ) ) ? $q['year'] : '';
		$words = trim( (string) ( $q['q'] ?? '' ) );
		$all   = ! empty( $q['all'] );
		$page  = max( 1, (int) ( $q['p'] ?? 1 ) );

		$years = array();
		$count = array();
		foreach ( $items as $it ) {
			$y = substr( (string) ( $it['document_date'] ?? '' ), 0, 4 );
			if ( preg_match( '/^\d{4}$/', $y ) ) {
				$years[ $y ] = 1;
			}
			$t           = (string) ( $it['source_type'] ?? 'other' );
			$count[ $t ] = ( $count[ $t ] ?? 0 ) + 1;
		}
		krsort( $years );
		$hidden = 0;
		$shown  = array();
		foreach ( $items as $it ) {
			if ( $type && ( $it['source_type'] ?? '' ) !== $type ) {
				continue;
			}
			if ( $year && substr( (string) ( $it['document_date'] ?? '' ), 0, 4 ) !== $year ) {
				continue;
			}
			if ( '' !== $words ) {
				$hay = TK_Render::display_title( $it ) . ' ' . ( $it['title'] ?? '' ) . ' ' . ( is_string( $it['brief']['summary'] ?? null ) ? $it['brief']['summary'] : '' );
				foreach ( preg_split( '/\s+/u', $words ) as $w ) {
					if ( '' !== $w && false === mb_stripos( $hay, $w ) ) {
						continue 2;
					}
				}
			}
			if ( ! $all && 'procedural' === TK_Render::significance( $it ) ) {
				++$hidden;
				continue;
			}
			$shown[] = $it;
		}

		$out  = '<form class="tk-docfilter" method="get" action="' . esc_url( $base ) . '" role="search" aria-label="' . esc_attr__( 'סינון מסמכים', 'trial-knowledge' ) . '">';
		$out .= '<label><span>' . esc_html__( 'סוג', 'trial-knowledge' ) . '</span><select name="tk_type_f"><option value="">' . esc_html__( 'כל הסוגים', 'trial-knowledge' ) . '</option>';
		foreach ( self::DOC_TYPE_LABELS as $k => $l ) {
			if ( ! empty( $count[ $k ] ) ) {
				$out .= '<option value="' . esc_attr( $k ) . '"' . ( $k === $type ? ' selected' : '' ) . '>' . esc_html( $l . ' (' . $count[ $k ] . ')' ) . '</option>';
			}
		}
		$out .= '</select></label>';
		$out .= '<label><span>' . esc_html__( 'שנה', 'trial-knowledge' ) . '</span><select name="tk_year"><option value="">' . esc_html__( 'כל השנים', 'trial-knowledge' ) . '</option>';
		foreach ( array_keys( $years ) as $y ) {
			$out .= '<option value="' . esc_attr( (string) $y ) . '"' . ( (string) $y === $year ? ' selected' : '' ) . '>' . esc_html( (string) $y ) . '</option>';
		}
		$out .= '</select></label>';
		$out .= '<label class="tk-docfilter__q"><span>' . esc_html__( 'מילים', 'trial-knowledge' ) . '</span><input type="search" name="tk_q" value="' . esc_attr( $words ) . '" placeholder="' . esc_attr__( 'למשל: חסיון, ישועה, תדירות', 'trial-knowledge' ) . '"></label>';
		$out .= '<label class="tk-docfilter__all"><input type="checkbox" name="tk_all" value="1"' . ( $all ? ' checked' : '' ) . '> ' . esc_html__( 'גם מסמכים פרוצדורליים', 'trial-knowledge' ) . '</label>';
		$out .= '<button type="submit" class="tk-button">' . esc_html__( 'סינון', 'trial-knowledge' ) . '</button>';
		if ( $type || $year || '' !== $words || $all ) {
			$out .= ' <a class="tk-docfilter__reset" href="' . esc_url( $base ) . '">' . esc_html__( 'ניקוי', 'trial-knowledge' ) . '</a>';
		}
		$out .= '</form>';

		$total = count( $shown );
		$pages = max( 1, (int) ceil( $total / self::DOCS_PER_PAGE ) );
		$page  = min( $page, $pages );
		$out  .= '<p class="tk-docfilter__n" aria-live="polite">' . esc_html( 1 === $total ? __( 'מסמך אחד', 'trial-knowledge' ) : sprintf( __( '%d מסמכים', 'trial-knowledge' ), $total ) ) .
			( $hidden ? ' <span class="tk-muted">' . esc_html( sprintf( __( '(ועוד %d פרוצדורליים — מועדים, ארכות, העתקים — מוסתרים)', 'trial-knowledge' ), $hidden ) ) . '</span>' : '' ) . '</p>';
		$out  .= TK_Render::documents( array( 'items' => array_slice( $shown, ( $page - 1 ) * self::DOCS_PER_PAGE, self::DOCS_PER_PAGE ) ), array( 'mode' => 'all' ) );
		if ( $pages > 1 ) {
			$args = array_map( 'rawurlencode', array_filter( array( 'tk_type_f' => $type, 'tk_year' => $year, 'tk_q' => $words, 'tk_all' => $all ? '1' : '' ) ) ); // add_query_arg does not encode
			$out .= '<nav class="tk-pager" aria-label="' . esc_attr__( 'עמודים', 'trial-knowledge' ) . '">';
			if ( $page > 1 ) {
				$out .= '<a class="tk-button" href="' . esc_url( add_query_arg( $args + array( 'tk_p' => $page - 1 ), $base ) ) . '">' . esc_html__( 'הקודמים', 'trial-knowledge' ) . '</a>';
			}
			$out .= '<span class="tk-pager__where">' . esc_html( sprintf( __( 'עמוד %1$d מתוך %2$d', 'trial-knowledge' ), $page, $pages ) ) . '</span>';
			if ( $page < $pages ) {
				$out .= '<a class="tk-button" href="' . esc_url( add_query_arg( $args + array( 'tk_p' => $page + 1 ), $base ) ) . '">' . esc_html__( 'הבאים', 'trial-knowledge' ) . '</a>';
			}
			$out .= '</nav>';
		}
		return '<div class="tk-guide tk-docs" dir="rtl" lang="he">' . $out . '</div>';
	}

	// ------------------------------------------------------------------ document brief (2.4)

	/**
	 * Top of a document page when a brief is published: title (H1), the archive title as a subtitle,
	 * summary sentences with citation chips, a procedural note and the hearing-day box.
	 * Returns '' without a brief (the page then looks as before).
	 *
	 * @param array $doc   /v2/documents/{sv} document (with brief).
	 * @param array $slugs witness name → slug (TK_Guides::slug_map()).
	 */
	public static function document_brief( array $doc, array $slugs = array() ) {
		$b = $doc['brief'] ?? null;
		if ( ! is_array( $b ) || empty( $b['title'] ) || ! is_string( $b['title'] ) ) {
			return '';
		}
		$cits = self::cit_map( $b['citations'] ?? array() );
		$out  = '<header class="tk-brief" dir="rtl" lang="he">';
		$out .= '<h1 class="tk-brief__title">' . esc_html( $b['title'] ) . '</h1>';
		if ( ! empty( $doc['title'] ) && $doc['title'] !== $b['title'] ) {
			$out .= '<p class="tk-brief__orig"><span class="tk-muted">' . esc_html__( 'שם במסמך:', 'trial-knowledge' ) . '</span> ' . esc_html( $doc['title'] ) . '</p>';
		}
		if ( ! empty( $b['summary_sentences'] ) ) {
			$out .= '<div class="tk-brief__sum">' . self::sentences( (array) $b['summary_sentences'], $cits, 'tk-sentences tk-sentences--brief' ) . '</div>';
		} elseif ( ! empty( $b['summary'] ) && is_string( $b['summary'] ) ) {
			$out .= '<p class="tk-brief__sum tk-glossable">' . esc_html( $b['summary'] ) . '</p>';
		}
		if ( 'procedural' === ( $b['significance'] ?? '' ) ) {
			$out .= '<p class="tk-brief__sig">' . TK_Render::procedural_badge() . ' <span class="tk-muted">' . esc_html__( 'מסמך פרוצדורלי', 'trial-knowledge' ) .
				( ! empty( $b['significance_reason'] ) ? ': ' . esc_html( $b['significance_reason'] ) : '' ) . '</span></p>';
		}
		$days = array_filter( (array) ( $b['hearing_days'] ?? array() ), 'is_array' );
		if ( $days ) {
			$out .= self::hearing_days_box( $days, $slugs, $cits );
		}
		$out .= '<p class="tk-muted tk-small">' . esc_html__( 'התקציר נכתב בעזרת מודל שפה מתוך המסמך, וכל משפט בו מקושר לעמוד שבו הוא מופיע. המסמך המלא, שמופיע למטה, הוא הקובע.', 'trial-knowledge' ) . '</p>';
		return $out . '</header>';
	}

	/**
	 * "יום דיון" box: date, who testified (linked to witness pages, with side), next hearing date.
	 *
	 * @param array $days  brief hearing_days.
	 * @param array $slugs name → slug.
	 * @param array $cits  cit_map.
	 */
	public static function hearing_days_box( array $days, array $slugs, array $cits = array() ) {
		$out = '<aside class="tk-hday" aria-label="' . esc_attr__( 'יום דיון', 'trial-knowledge' ) . '">';
		$out .= '<h2 class="tk-hday__h">' . esc_html( count( $days ) > 1 ? __( 'ימי דיון', 'trial-knowledge' ) : __( 'יום דיון', 'trial-knowledge' ) ) . '</h2>';
		foreach ( $days as $d ) {
			$out .= '<dl class="tk-hday__dl">';
			if ( ! empty( $d['hearing_date'] ) ) {
				$out .= '<div><dt>' . esc_html__( 'תאריך', 'trial-knowledge' ) . '</dt><dd>' . self::time_tag( $d['hearing_date'] ) . self::chips( $d['citation_ids'] ?? array(), $cits ) . '</dd></div>';
			}
			$ws = array_filter( (array) ( $d['witnesses'] ?? array() ), 'is_array' );
			if ( $ws ) {
				$out .= '<div><dt>' . esc_html( __( 'עדים', 'trial-knowledge' ) ) . '</dt><dd><ul class="tk-hday__ws">';
				foreach ( $ws as $w ) {
					$side = (string) ( $w['side'] ?? '' );
					$out .= '<li>' . self::witness_link( (string) ( $w['name'] ?? '' ), $slugs ) .
						( isset( self::SIDES[ $side ] ) ? ' <span class="tk-badge tk-badge--side tk-badge--' . esc_attr( $side ) . '">' . esc_html( self::SIDES[ $side ] ) . '</span>' : '' ) .
						( ! empty( $w['description'] ) ? ' <span class="tk-hday__desc tk-glossable">' . esc_html( $w['description'] ) . '</span>' : '' ) . '</li>';
				}
				$out .= '</ul></dd></div>';
			}
			if ( ! empty( $d['next_hearing_date'] ) ) {
				$out .= '<div><dt>' . esc_html__( 'הדיון הבא', 'trial-knowledge' ) . '</dt><dd>' . self::time_tag( $d['next_hearing_date'] ) . '</dd></div>';
			}
			$out .= '</dl>';
		}
		$out .= '<p class="tk-muted tk-small">' . esc_html__( 'לפי הודעת בית המשפט. ההודעה מתעדת מי העיד ומתי, לא את תוכן העדות.', 'trial-knowledge' ) . '</p>';
		return $out . '</aside>';
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
		$out  = '<div class="tk-glossary" dir="rtl" lang="he">';
		$out .= '<section class="tk-sec tk-sec--steps" id="tk-steps"><h2 class="tk-sec__h">' . esc_html__( 'המשפט הפלילי בחמישה צעדים', 'trial-knowledge' ) . '</h2>' . TK_Render_Nav::five_steps() . '</section>';
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
		$out .= TK_Render_Nav::bar( 'timeline', array( array( __( 'ציר הזמן', 'trial-knowledge' ), TK_Public_Pages::section_url( 'timeline' ) ), array( sprintf( __( 'דיון מיום %s', 'trial-knowledge' ), self::fmt_date( $h['hearing_date'] ) ), '' ) ) );
		$out .= '<header class="tk-head"><p class="tk-kicker">' . esc_html__( 'דיון בבית המשפט', 'trial-knowledge' ) . '</p>';
		$out .= '<h1 class="tk-head__title">' . esc_html( sprintf( __( 'דיון מיום %s', 'trial-knowledge' ), self::fmt_date( $h['hearing_date'] ) ) ) . '</h1>';
		$out .= '<dl class="tk-meta">';
		if ( ! empty( $h['witnesses'] ) ) {
			$ws = array();
			foreach ( $h['witnesses'] as $raw ) {
				$ws[] = self::witness_link( $raw, $slugs );
			}
			$out .= '<div><dt>' . esc_html( __( 'עדים', 'trial-knowledge' ) ) . '</dt><dd>' . implode( ', ', $ws ) . '</dd></div>';
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
		$out .= '</div>' . self::hearing_pager( (array) ( $opts['neighbors'] ?? array() ) );
		return $out . '</div>';
	}

	/** Previous / next hearing. */
	public static function hearing_pager( array $nb ) {
		if ( empty( $nb['prev'] ) && empty( $nb['next'] ) ) {
			return '';
		}
		$out = '<nav class="tk-pager2" aria-label="' . esc_attr__( 'דיונים סמוכים', 'trial-knowledge' ) . '">';
		if ( ! empty( $nb['prev'] ) ) {
			$out .= '<a class="tk-pager2__prev" href="' . esc_url( TK_Public_Pages::url( 'hearing', $nb['prev']['id'] ) ) . '"><span class="tk-muted">' . esc_html__( 'הדיון הקודם', 'trial-knowledge' ) . '</span> ' . esc_html( self::fmt_date( $nb['prev']['date'] ) ) . '</a>';
		}
		$out .= '<a class="tk-pager2__all" href="' . esc_url( TK_Public_Pages::section_url( 'timeline' ) ) . '">' . esc_html__( 'לציר הזמן', 'trial-knowledge' ) . '</a>';
		if ( ! empty( $nb['next'] ) ) {
			$out .= '<a class="tk-pager2__next" href="' . esc_url( TK_Public_Pages::url( 'hearing', $nb['next']['id'] ) ) . '"><span class="tk-muted">' . esc_html__( 'הדיון הבא', 'trial-knowledge' ) . '</span> ' . esc_html( self::fmt_date( $nb['next']['date'] ) ) . '</a>';
		}
		return $out . '</nav>';
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
		if ( ! empty( $t['pdf_url'] ) && TK_Settings_Store::show_pdf() ) {
			$out .= '<a class="tk-button tk-button--pdf" href="' . esc_url( $t['pdf_url'] ) . '" rel="nofollow">' . esc_html__( 'PDF המקורי', 'trial-knowledge' ) . '</a> ';
		}
		if ( $sv && preg_match( '/^sv_[0-9a-f]{26}$/', $sv ) ) {
			$out .= '<a class="tk-button" href="' . esc_url( TK_Public_Pages::url( 'document', $sv ) ) . '">' . esc_html__( 'לעמוד המסמך', 'trial-knowledge' ) . '</a>';
		}
		return $out . '</p>';
	}
}
