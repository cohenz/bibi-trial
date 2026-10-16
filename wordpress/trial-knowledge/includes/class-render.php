<?php
/**
 * Server-side HTML for blocks, shortcodes and virtual pages.
 * All output is escaped; content comes only from published API objects.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Render {

	const LEVELS = array(
		'question_or_comment' => 'שאלה או הערה של שופט — אינה החלטה',
		'interim_observation' => 'הערת ביניים של ההרכב — אינה הכרעה סופית',
		'procedural_decision' => 'החלטה דיונית',
		'substantive_ruling'  => 'הכרעה מהותית',
	);

	const STATUS = array(
		'unverified'             => 'טרם אומת',
		'source_backed'          => 'נתמך במקור',
		'multi_source_supported' => 'נתמך בכמה מקורות',
		'court_recognized'       => 'הוכר בבית המשפט',
		'court_determined'       => 'נקבע בבית המשפט',
		'disputed'               => 'שנוי במחלוקת',
		'partially_supported'    => 'נתמך חלקית',
		'weakened'               => 'הראיות שנאספו מחלישות את הטענה',
		'rejected'               => 'נדחה',
		'pending'                => 'טרם הוכרע',
		'superseded'             => 'הוחלף',
	);

	const RECORD = array(
		'filed'                     => 'הוגש לתיק',
		'admitted'                  => 'התקבל כראיה',
		'marked_for_identification' => 'סומן לזיהוי',
		'referenced_in_court'       => 'אוזכר בדיון',
		'excluded'                  => 'הוצא מהתיק',
		'not_filed'                 => 'לא הוגש',
		'external'                  => 'מקור חיצוני — אינו חלק מתיק בית המשפט',
		'unknown'                   => 'מעמד בתיק לא ידוע',
	);

	const TYPES = array(
		'protocol'   => 'פרוטוקול דיון',
		'decision'   => 'החלטה',
		'motion'     => 'בקשה',
		'response'   => 'תגובה',
		'notice'     => 'הודעה',
		'affidavit'  => 'תצהיר',
		'indictment' => 'כתב אישום',
		'exhibit'    => 'מוצג',
		'other'      => 'מסמך',
	);

	/**
	 * "1–8" kept in reading order inside Hebrew text: between two numbers the dash takes the paragraph's RTL
	 * direction and "1–8" would show as "8–1". Wrapped in a left-to-right isolate (LRI … PDI).
	 */
	public static function nrange( $a, $b ) {
		return "\u{2066}" . $a . '–' . $b . "\u{2069}";
	}

	public static function type_label( $type ) {
		return self::TYPES[ $type ] ?? self::TYPES['other'];
	}

	public static function error_box( $message ) {
		return '<div class="tk-notice tk-notice--error" role="status">' . esc_html( $message ) . '</div>';
	}

	public static function unavailable() {
		return self::error_box( __( 'המידע אינו זמין כרגע. נסו שוב בעוד כמה דקות.', 'trial-knowledge' ) );
	}

	public static function citation_url( $source_unit_id ) {
		return TK_Public_Pages::url( 'source', $source_unit_id );
	}

	/** Compact citation for running text (digests): "עמ׳ 118", details in the tooltip. */
	public static function citation_chip( array $c ) {
		$title = sprintf( __( 'עמ׳ %1$d, שורות %2$s', 'trial-knowledge' ), (int) $c['page'], self::nrange( (int) $c['line_start'], (int) $c['line_end'] ) ) .
			( ! empty( $c['speaker'] ) ? ' · ' . $c['speaker'] : '' );
		return '<a class="tk-chip" href="' . esc_url( self::citation_url( $c['source_unit_id'] ) ) . '" title="' . esc_attr( $title ) . '">' .
			esc_html( sprintf( __( 'עמ׳ %d', 'trial-knowledge' ), (int) $c['page'] ) ) . '</a>';
	}

	/** "עמ׳ 10, ש׳ 6–7 · עו"ד בן צור" — one row of a sources list. */
	public static function citation_row_label( array $c ) {
		$ls    = (int) ( $c['line_start'] ?? 0 );
		$le    = (int) ( $c['line_end'] ?? $ls );
		$lines = $ls ? ( $ls === $le || ! $le ? sprintf( __( 'ש׳ %d', 'trial-knowledge' ), $ls ) : sprintf( __( 'ש׳ %s', 'trial-knowledge' ), self::nrange( $ls, $le ) ) ) : '';
		$label = sprintf( __( 'עמ׳ %d', 'trial-knowledge' ), (int) ( $c['page'] ?? 0 ) ) . ( $lines ? ', ' . $lines : '' );
		return array( $label, (string) ( $c['speaker'] ?? '' ) );
	}

	/**
	 * Sources of one sentence as a single small pill at its end (2.6). One source: the pill links to it.
	 * Several: "מקורות · N" opens a list on hover, keyboard focus or tap; each row links to its source.
	 *
	 * @param array $items Each: array( 'id' => source_unit_id, 'c' => citation array|null ).
	 */
	public static function sources_pill( array $items ) {
		if ( ! $items ) {
			return '';
		}
		self::enqueue_reading();
		usort(
			$items,
			static function ( $a, $b ) {
				$pa = isset( $a['c']['page'] ) ? (int) $a['c']['page'] * 1000 + (int) ( $a['c']['line_start'] ?? 0 ) : PHP_INT_MAX;
				$pb = isset( $b['c']['page'] ) ? (int) $b['c']['page'] * 1000 + (int) ( $b['c']['line_start'] ?? 0 ) : PHP_INT_MAX;
				return $pa <=> $pb;
			}
		);
		$rows = array();
		foreach ( $items as $it ) {
			if ( is_array( $it['c'] ) && isset( $it['c']['page'] ) ) {
				list( $label, $who ) = self::citation_row_label( $it['c'] );
			} else {
				list( $label, $who ) = array( __( 'המקור בתיק', 'trial-knowledge' ), '' );
			}
			$rows[] = array( self::citation_url( $it['id'] ), $label, $who );
		}
		if ( 1 === count( $rows ) ) {
			$r = $rows[0];
			return ' <a class="tk-srcs tk-srcs--one" href="' . esc_url( $r[0] ) . '" title="' . esc_attr( $r[1] . ( $r[2] ? ' · ' . $r[2] : '' ) ) . '">' . esc_html__( 'מקור', 'trial-knowledge' ) . '</a>';
		}
		$id  = 'tk-srcs-' . substr( md5( wp_json_encode( $rows ) . wp_rand() ), 0, 10 );
		$out = ' <span class="tk-srcs" data-tk-srcs><button type="button" class="tk-srcs__btn" aria-expanded="false" aria-controls="' . esc_attr( $id ) . '">' .
			esc_html__( 'מקורות', 'trial-knowledge' ) . ' <span class="tk-srcs__n">' . count( $rows ) . '</span></button>' .
			'<span class="tk-srcs__pop" id="' . esc_attr( $id ) . '" role="list">';
		foreach ( $rows as $r ) {
			$out .= '<a role="listitem" class="tk-srcs__row" href="' . esc_url( $r[0] ) . '"><span class="tk-srcs__loc">' . esc_html( $r[1] ) . '</span>' .
				( $r[2] ? '<span class="tk-srcs__who">' . esc_html( $r[2] ) . '</span>' : '' ) . '</a>';
		}
		return $out . '</span></span>';
	}

	/** Small script for the sources pills and the collapsible transcript pages (footer; printed once). */
	public static function enqueue_reading() {
		if ( function_exists( 'wp_enqueue_script' ) ) {
			wp_enqueue_script( 'trial-knowledge-reading' );
		}
	}

	/** ⓘ with a short note shown on hover, focus or tap (2.6). */
	public static function info_tip( $text ) {
		$text = trim( (string) $text );
		if ( '' === $text ) {
			return '';
		}
		return '<span class="tk-info" tabindex="0" role="note" aria-label="' . esc_attr( $text ) . '" data-tip="' . esc_attr( $text ) . '">i</span>';
	}

	/** Short form of a verified Q/A label: "אישר" / "הכחיש", the full wording in the tooltip. */
	public static function qa_badge( $label ) {
		$label = (string) $label;
		$short = false !== strpos( $label, 'הכחיש' ) ? 'הכחיש' : ( false !== strpos( $label, 'אישר' ) ? 'אישר' : $label );
		$cls   = 'הכחיש' === $short ? 'deny' : 'affirm';
		return '<span class="tk-badge tk-badge--qa tk-badge--' . $cls . '" title="' . esc_attr( $label ) . '">' . esc_html( $short ) . '</span>';
	}

	public static function citation_link( array $c ) {
		$label = sprintf(
			/* translators: 1: page 2: line start 3: line end */
			(int) $c['line_start'] === (int) $c['line_end'] ? __( 'עמ׳ %1$d, שורה %2$s', 'trial-knowledge' ) : __( 'עמ׳ %1$d, שורות %2$s', 'trial-knowledge' ),
			(int) $c['page'],
			(int) $c['line_start'] === (int) $c['line_end'] ? (string) (int) $c['line_start'] : self::nrange( (int) $c['line_start'], (int) $c['line_end'] )
		);
		$speaker = ! empty( $c['speaker'] ) ? ' · ' . $c['speaker'] : '';
		return '<a class="tk-cite" href="' . esc_url( self::citation_url( $c['source_unit_id'] ) ) . '">' .
			'<span class="tk-cite__loc">' . esc_html( $label ) . '</span><span class="tk-cite__who">' . esc_html( $speaker ) . '</span></a>';
	}

	private static function points( array $points, array $cits, $empty ) {
		if ( empty( $points ) ) {
			return '<p class="tk-empty">' . esc_html( $empty ) . '</p>';
		}
		$out = '<ul class="tk-points">';
		foreach ( $points as $p ) {
			$links = array();
			foreach ( (array) $p['citation_ids'] as $cid ) {
				if ( isset( $cits[ $cid ] ) ) {
					$links[] = self::citation_link( $cits[ $cid ] );
				}
			}
			$rec  = isset( self::RECORD[ $p['court_record_status'] ] ) ? self::RECORD[ $p['court_record_status'] ] : '';
			$out .= '<li class="tk-point"><p>' . esc_html( $p['summary'] ) . '</p>' .
				'<p class="tk-point__meta"><span class="tk-badge">' . esc_html( $rec ) . '</span> ' . implode( ' ', $links ) . '</p></li>';
		}
		return $out . '</ul>';
	}

	/**
	 * Claim card with the four boxes of spec §2. Order of boxes may follow the
	 * editorial lens; the content does not change.
	 *
	 * @param array $card Response of GET /v2/claims/{id}.
	 * @param array $opts Options: heading_level, show_disclosure.
	 */
	public static function claim_card( array $card, array $opts = array() ) {
		$b    = $card['bundle'];
		$cits = array();
		foreach ( $b['citations'] as $c ) {
			$cits[ $c['source_unit_id'] ] = $c;
		}
		$h      = isset( $opts['heading_level'] ) ? max( 2, min( 4, (int) $opts['heading_level'] ) ) : 2;
		$status = isset( $card['status_as_of']['status'] ) ? $card['status_as_of']['status'] : $b['status'];
		$cfg    = TK_Settings_Store::get();
		$court  = '<p class="tk-empty">' . esc_html__( 'לא נמצאה בחומר שמופה עמדה של בית המשפט בנושא.', 'trial-knowledge' ) . '</p>';
		if ( ! empty( $b['court_position'] ) ) {
			$cp    = $b['court_position'];
			$links = array();
			foreach ( $cp['citation_ids'] as $cid ) {
				if ( isset( $cits[ $cid ] ) ) {
					$links[] = self::citation_link( $cits[ $cid ] );
				}
			}
			$court = '<p><span class="tk-level tk-level--' . esc_attr( $cp['level'] ) . '">' . esc_html( self::LEVELS[ $cp['level'] ] ?? $cp['level'] ) .
				'</span></p><p>' . esc_html( $cp['summary'] ) . '</p><p class="tk-point__meta">' . implode( ' ', $links ) . '</p>';
		}
		$out  = '<article class="tk-claim" dir="rtl" lang="he" aria-labelledby="tk-claim-' . esc_attr( $b['claim_id'] ) . '">';
		$out .= '<header class="tk-claim__head"><h' . $h . ' id="tk-claim-' . esc_attr( $b['claim_id'] ) . '" class="tk-claim__q">' . esc_html( $b['question'] ) . '</h' . $h . '>';
		$out .= '<p class="tk-claim__short">' . esc_html( $b['answer_short'] ?? '' ) . '</p>';
		$out .= '<p class="tk-claim__meta"><span class="tk-status tk-status--' . esc_attr( $status ) . '">' . esc_html( self::STATUS[ $status ] ?? $status ) . '</span> ';
		$out .= '<time datetime="' . esc_attr( $b['as_of'] ) . '">' . esc_html( sprintf( __( 'נכון ל־%s', 'trial-knowledge' ), substr( $b['as_of'], 0, 10 ) ) ) . '</time></p></header>';
		$out .= '<section class="tk-box tk-box--claim"><h' . ( $h + 1 ) . '>' . esc_html__( 'מה נטען ומי טוען זאת?', 'trial-knowledge' ) . '</h' . ( $h + 1 ) . '><p>' . esc_html( $b['claim_text'] ) . '</p></section>';
		$out .= '<section class="tk-box tk-box--support"><h' . ( $h + 1 ) . '>' . esc_html__( 'מה מחזק את הטענה?', 'trial-knowledge' ) . '</h' . ( $h + 1 ) . '>' . self::points( $b['support'], $cits, __( 'לא נמצא חומר מחזק בחומר שמופה.', 'trial-knowledge' ) ) . '</section>';
		$out .= '<section class="tk-box tk-box--weakness"><h' . ( $h + 1 ) . '>' . esc_html__( 'מה מחליש או סותר אותה?', 'trial-knowledge' ) . '</h' . ( $h + 1 ) . '>' . self::points( $b['weakness'], $cits, __( 'לא נמצא חומר מחליש בחומר שמופה.', 'trial-knowledge' ) ) . '</section>';
		$out .= '<section class="tk-box tk-box--court"><h' . ( $h + 1 ) . '>' . esc_html__( 'מה אמר או קבע בית המשפט?', 'trial-knowledge' ) . '</h' . ( $h + 1 ) . '>' . $court . '</section>';
		if ( ! empty( $b['unresolved_questions'] ) ) {
			$out .= '<section class="tk-box tk-box--open"><h' . ( $h + 1 ) . '>' . esc_html__( 'שאלות פתוחות', 'trial-knowledge' ) . '</h' . ( $h + 1 ) . '><ul>';
			foreach ( $b['unresolved_questions'] as $q ) {
				$out .= '<li>' . esc_html( $q ) . '</li>';
			}
			$out .= '</ul></section>';
		}
		if ( ! isset( $opts['show_disclosure'] ) || $opts['show_disclosure'] ) {
			$out .= '<footer class="tk-claim__disclosure"><p>' . esc_html( $b['disclosure'] ?? $cfg['disclosure'] ) . '</p></footer>';
		}
		return $out . '</article>';
	}

	/**
	 * @param array $c Response of GET /v2/citations/{id}.
	 */
	public static function citation( array $c ) {
		$cit  = $c['citation'];
		$doc  = $c['document'];
		$out  = '<figure class="tk-source" dir="rtl" lang="he">';
		$out .= '<blockquote class="tk-source__quote" cite="' . esc_url( $cit['permalink'] ) . '"><p class="tk-source__speaker">' . esc_html( (string) $cit['speaker'] ) . '</p>';
		$out .= '<p class="tk-source__text">' . nl2br( esc_html( $c['text'] ) ) . '</p>';
		foreach ( (array) $c['turn_continuations'] as $part ) {
			$out .= '<p class="tk-source__text tk-source__cont">' . nl2br( esc_html( $part['raw_text'] ) ) . ' <span class="tk-muted">' .
				esc_html( sprintf( __( '(המשך בעמ׳ %1$d, שורות %2$s)', 'trial-knowledge' ), $part['page_no'], self::nrange( (int) $part['line_start'], (int) $part['line_end'] ) ) ) . '</span></p>';
		}
		$out .= '</blockquote><figcaption>';
		$out .= '<p><strong>' . esc_html( $doc['title'] ) . '</strong></p>';
		$out .= '<p>' . esc_html( sprintf( __( 'עמוד %1$d, שורות %2$s', 'trial-knowledge' ), $cit['page'], self::nrange( (int) $cit['line_start'], (int) $cit['line_end'] ) ) ) . '</p>';
		if ( ! empty( $c['synthetic_lines'] ) ) {
			$out .= '<p class="tk-muted">' . esc_html__( 'במסמך זה אין מספור שורות מודפס; מספרי השורות חושבו בקליטה.', 'trial-knowledge' ) . '</p>';
		}
		$out .= '<p><span class="tk-badge">' . esc_html( self::RECORD[ $cit['court_record_status'] ] ?? '' ) . '</span></p>';
		if ( ! empty( $c['exchange']['public_wording'] ) && in_array( $c['exchange']['review_state'], array( 'machine_verified', 'approved', 'published' ), true ) ) {
			$out .= '<p class="tk-exchange">' . esc_html( $c['exchange']['public_wording'] ) . '</p>';
		}
		if ( ! empty( $doc['canonical_url'] ) ) {
			$out .= '<p><a href="' . esc_url( $doc['canonical_url'] ) . '" rel="noopener nofollow">' . esc_html__( 'למסמך הרשמי', 'trial-knowledge' ) . '</a></p>';
		}
		$in_context = self::in_context_url( $c );
		if ( $in_context ) {
			$out .= '<p><a class="tk-button" href="' . esc_url( $in_context ) . '">' . esc_html__( 'לקטע בתוך המסמך המלא', 'trial-knowledge' ) . '</a></p>';
		}
		if ( ! empty( $c['superseded_by_version'] ) ) {
			$out .= '<p class="tk-notice">' . esc_html__( 'קיימת גרסה מתוקנת של המסמך; ציטוט זה מתייחס לגרסה המקורית.', 'trial-knowledge' ) . '</p>';
		}
		$out .= '<p class="tk-muted">SHA-256: <code>' . esc_html( substr( $doc['content_sha256'], 0, 16 ) ) . '…</code></p>';
		$out .= '</figcaption></figure>';
		if ( ! empty( $c['context'] ) ) {
			$out .= '<details class="tk-context"><summary>' . esc_html__( 'הקשר: קטעים סמוכים', 'trial-knowledge' ) . '</summary><ol>';
			foreach ( $c['context'] as $n ) {
				$out .= '<li><a href="' . esc_url( self::citation_url( $n['id'] ) ) . '">' . esc_html( (string) $n['speaker_label'] ) . '</a>: ' . esc_html( wp_trim_words( $n['raw_text'], 40 ) ) . '</li>';
			}
			$out .= '</ol></details>';
		}
		return $out;
	}

	/** Link to a unit inside its full transcript/document page, on the right page of text. */
	public static function in_context_url( array $c ) {
		$cit  = $c['citation'];
		$page = (int) $cit['page'];
		$from = TK_Paths::window_start( $page ); // the same 25-page window the page requests (one stored copy)
		if ( ! empty( $c['hearing_id'] ) ) {
			$url = TK_Public_Pages::url( 'hearing', $c['hearing_id'] );
		} elseif ( ! empty( $cit['source_version_id'] ) ) {
			$url = TK_Public_Pages::url( 'document', $cit['source_version_id'] );
		} else {
			return '';
		}
		return add_query_arg( 'tk_p', $from, $url ) . '#' . rawurlencode( $cit['source_unit_id'] );
	}

	private static function pager( array $t, $base_url, $fragment = '' ) {
		$frag = $fragment ? '#' . rawurlencode( $fragment ) : '';
		$out  = '<nav class="tk-pager" aria-label="' . esc_attr__( 'עמודי המסמך', 'trial-knowledge' ) . '">';
		if ( ! empty( $t['prev_page_from'] ) ) {
			$out .= '<a class="tk-button" href="' . esc_url( add_query_arg( 'tk_p', (int) $t['prev_page_from'], $base_url ) . $frag ) . '">' . esc_html__( '→ עמודים קודמים', 'trial-knowledge' ) . '</a> ';
		}
		$out .= '<span class="tk-pager__where">' . esc_html( sprintf( __( 'עמודים %1$s מתוך %2$d', 'trial-knowledge' ), self::nrange( (int) $t['page_from'], (int) $t['page_to'] ), $t['page_count'] ) ) . '</span>';
		if ( ! empty( $t['next_page_from'] ) ) {
			$out .= ' <a class="tk-button" href="' . esc_url( add_query_arg( 'tk_p', (int) $t['next_page_from'], $base_url ) . $frag ) . '">' . esc_html__( 'עמודים הבאים ←', 'trial-knowledge' ) . '</a>';
		}
		if ( ! empty( $t['pdf_url'] ) && TK_Settings_Store::show_pdf() ) {
			$out .= ' <a class="tk-button tk-button--pdf" href="' . esc_url( $t['pdf_url'] ) . '" rel="nofollow">' . esc_html__( 'PDF המקורי', 'trial-knowledge' ) . '</a>';
		}
		return $out . '</nav>';
	}

	/**
	 * Full text of a protocol or document, page by page, every unit linkable.
	 *
	 * @param array  $t        Response of /v2/hearings/{id}/transcript or /v2/documents/{sv}.
	 * @param string $base_url Page URL without tk_p (may carry tk_tab).
	 * @param string $fragment Anchor appended to pager links (keeps the hearing tab open).
	 */
	public static function transcript( array $t, $base_url, $fragment = '' ) {
		$pages = array();
		foreach ( (array) $t['units'] as $u ) {
			$pages[ (int) $u['page'] ][] = $u;
		}
		// Short texts stay open; longer ones start collapsed, one page opened at a time by the reader (2.6).
		$collapse = count( $pages ) > 3;
		self::enqueue_reading();
		$out      = '<section class="tk-transcript' . ( $collapse ? ' tk-transcript--collapsible' : '' ) . '" dir="rtl" lang="he" data-tk-transcript>' . self::pager( $t, $base_url, $fragment );
		$tip      = self::info_tip( TK_Settings_Store::ocr_disclaimer() );
		if ( $collapse || $tip ) {
			$out .= '<div class="tk-transcript__bar">';
			if ( $tip ) {
				$out .= '<span class="tk-transcript__note">' . esc_html__( 'טקסט שחולץ מהמסמך', 'trial-knowledge' ) . ' ' . $tip . '</span>';
			}
			if ( $collapse ) {
				$out .= '<span class="tk-transcript__tools" hidden><button type="button" class="tk-linkbtn" data-tk-pages="open">' . esc_html__( 'פתיחת כל העמודים', 'trial-knowledge' ) . '</button>' .
					'<button type="button" class="tk-linkbtn" data-tk-pages="close">' . esc_html__( 'סגירת כל העמודים', 'trial-knowledge' ) . '</button></span>';
			}
			$out .= '</div>';
		}
		foreach ( $pages as $no => $units ) {
			$who = array();
			foreach ( $units as $u ) {
				$sp = trim( (string) ( $u['speaker'] ?? '' ) );
				if ( '' !== $sp && ! in_array( $sp, $who, true ) ) {
					$who[] = $sp;
				}
			}
			$head = '<span class="tk-tpage__no">' . esc_html( sprintf( __( 'עמוד %d', 'trial-knowledge' ), $no ) ) . '</span>';
			if ( $who ) {
				$more  = count( $who ) > 3 ? ' ' . sprintf( __( 'ועוד %d', 'trial-knowledge' ), count( $who ) - 3 ) : '';
				$head .= '<span class="tk-tpage__who">' . esc_html( implode( ' · ', array_slice( $who, 0, 3 ) ) . $more ) . '</span>';
			}
			$list = '<ol class="tk-transcript__units">';
			foreach ( $units as $u ) {
				$type  = preg_replace( '/[^a-z_]/', '', (string) $u['unit_type'] );
				$list .= '<li id="' . esc_attr( $u['id'] ) . '" class="tk-u tk-u--' . esc_attr( $type ) . '">';
				$list .= '<a class="tk-u__lines" href="' . esc_url( self::citation_url( $u['id'] ) ) . '" title="' . esc_attr__( 'קישור קבוע לקטע', 'trial-knowledge' ) . '">' .
					esc_html( $u['line_start'] === $u['line_end'] ? (string) $u['line_start'] : self::nrange( $u['line_start'], $u['line_end'] ) ) . '</a>';
				// many protocols print the speaker at the start of the turn; do not show it twice
				if ( ! empty( $u['speaker'] ) && 'caption' !== $type && 0 !== strpos( ltrim( (string) $u['text'] ), (string) $u['speaker'] ) ) {
					$list .= '<span class="tk-u__speaker">' . esc_html( $u['speaker'] ) . '</span>';
				}
				$list .= '<span class="tk-u__text">' . nl2br( esc_html( $u['text'] ) ) . '</span>';
				if ( ! empty( $u['exchange_label'] ) ) {
					$list .= ' ' . self::qa_badge( $u['exchange_label'] );
				}
				$list .= '</li>';
			}
			$list .= '</ol>';
			if ( $collapse ) {
				$out .= '<details class="tk-tpage" id="page-' . (int) $no . '"><summary class="tk-tpage__head">' . $head .
					'<button type="button" class="tk-linkbtn tk-tpage__only" data-tk-only hidden>' . esc_html__( 'רק עמוד זה', 'trial-knowledge' ) . '</button></summary>' . $list . '</details>';
			} else {
				$out .= '<h3 class="tk-transcript__page" id="page-' . (int) $no . '">' . esc_html( sprintf( __( 'עמוד %d', 'trial-knowledge' ), $no ) ) . '</h3>' . $list;
			}
		}
		if ( ! $pages ) {
			$out .= '<p class="tk-muted">' . esc_html__( 'אין טקסט בעמודים אלה.', 'trial-knowledge' ) . '</p>';
		}
		return $out . self::pager( $t, $base_url, $fragment ) . '</section>';
	}

	/** Title shown for a document: the brief title when published (2.4), else the archive title. */
	public static function display_title( array $doc ) {
		if ( ! empty( $doc['display_title'] ) ) {
			return (string) $doc['display_title'];
		}
		if ( ! empty( $doc['brief']['title'] ) && is_string( $doc['brief']['title'] ) ) {
			return $doc['brief']['title'];
		}
		return (string) ( $doc['title'] ?? '' );
	}

	/** substantive|procedural|'' (no brief yet). */
	public static function significance( array $doc ) {
		$s = $doc['significance'] ?? ( $doc['brief']['significance'] ?? '' );
		return in_array( $s, array( 'substantive', 'procedural' ), true ) ? $s : '';
	}

	public static function procedural_badge() {
		return '<span class="tk-badge tk-badge--procedural" title="' . esc_attr__( 'מסמך שעוסק רק בלוגיסטיקה של ההליך: מועדים, ארכות, הקלטות, העתקים', 'trial-knowledge' ) . '">' . esc_html__( 'פרוצדורלי', 'trial-knowledge' ) . '</span>';
	}

	/**
	 * Document list (2.4: brief title and one-line summary, procedural documents hidden by default).
	 *
	 * @param array $d    Response of GET /v2/documents.
	 * @param array $opts mode: 'all' (no toggle) | 'substantive' (procedural hidden) | 'with_procedural' (shown via toggle);
	 *                    hidden_count (int|null, procedural documents not shown); show_url / hide_url (toggle links).
	 */
	public static function documents( array $d, array $opts = array() ) {
		$items  = (array) ( $d['items'] ?? array() );
		$mode   = in_array( $opts['mode'] ?? 'all', array( 'all', 'substantive', 'with_procedural' ), true ) ? ( $opts['mode'] ?? 'all' ) : 'all';
		$hidden = isset( $opts['hidden_count'] ) && null !== $opts['hidden_count'] ? (int) $opts['hidden_count'] : null;
		$toggle = '';
		if ( 'substantive' === $mode && 0 !== $hidden && ! empty( $opts['show_url'] ) ) {
			$label  = null === $hidden ? __( 'הצגת גם מסמכים פרוצדורליים', 'trial-knowledge' ) : sprintf( __( 'הצגת גם מסמכים פרוצדורליים (%d)', 'trial-knowledge' ), $hidden );
			$toggle = '<p class="tk-doctoggle"><span class="tk-muted">' . esc_html__( 'מוצגים מסמכים מהותיים. מסמכים פרוצדורליים (מועדים, ארכות, העתקים) מוסתרים.', 'trial-knowledge' ) . '</span> <a class="tk-button tk-doctoggle__a" href="' . esc_url( $opts['show_url'] ) . '" rel="nofollow">' . esc_html( $label ) . '</a></p>';
		} elseif ( 'with_procedural' === $mode && ! empty( $opts['hide_url'] ) ) {
			$toggle = '<p class="tk-doctoggle"><span class="tk-muted">' . esc_html__( 'מוצגים כל המסמכים, כולל פרוצדורליים.', 'trial-knowledge' ) . '</span> <a class="tk-button tk-doctoggle__a" href="' . esc_url( $opts['hide_url'] ) . '">' . esc_html__( 'הסתרת מסמכים פרוצדורליים', 'trial-knowledge' ) . '</a></p>';
		}
		if ( ! $items ) {
			$empty = 'substantive' === $mode && $hidden ? __( 'אין מסמכים מהותיים להצגה.', 'trial-knowledge' ) : __( 'עדיין לא פורסמו מסמכים.', 'trial-knowledge' );
			return '<div class="tk-doclist" dir="rtl" lang="he">' . $toggle . '<p class="tk-empty">' . esc_html( $empty ) . '</p></div>';
		}
		$out = '<div class="tk-doclist" dir="rtl" lang="he">' . $toggle . '<ul class="tk-documents">';
		foreach ( $items as $it ) {
			$sig     = self::significance( $it );
			$summary = isset( $it['brief']['summary'] ) && is_string( $it['brief']['summary'] ) ? trim( $it['brief']['summary'] ) : '';
			$out    .= '<li class="tk-documents__item' . ( 'procedural' === $sig ? ' tk-documents__item--procedural' : '' ) . '">';
			$out    .= '<a class="tk-documents__title" href="' . esc_url( TK_Public_Pages::url( 'document', $it['source_version_id'] ) ) . '">' . esc_html( self::display_title( $it ) ) . '</a>';
			if ( '' !== $summary ) {
				$out .= '<p class="tk-documents__summary">' . esc_html( $summary ) . '</p>';
			}
			$out .= '<p class="tk-documents__meta"><span class="tk-badge">' . esc_html( self::type_label( $it['source_type'] ?? 'other' ) ) . '</span>';
			if ( 'procedural' === $sig ) {
				$out .= ' ' . self::procedural_badge();
			}
			if ( ! empty( $it['document_date'] ) ) {
				$out .= ' <time datetime="' . esc_attr( substr( $it['document_date'], 0, 10 ) ) . '">' . esc_html( TK_Render_Guides::fmt_date( $it['document_date'] ) ) . '</time>';
			}
			if ( ! empty( $it['page_count'] ) ) {
				$out .= ' <span class="tk-muted">' . esc_html( sprintf( _n( 'עמוד %d', '%d עמודים', (int) $it['page_count'], 'trial-knowledge' ), (int) $it['page_count'] ) ) . '</span>';
			}
			$out .= '</p></li>';
		}
		return $out . '</ul></div>';
	}

	/**
	 * @param array $t Response of GET /v2/timeline.
	 */
	public static function timeline( array $t, $as_of = '' ) {
		$items = array();
		foreach ( (array) $t['events'] as $e ) {
			$items[] = array( substr( $e['occurred_at'], 0, 10 ), 'event-' . $e['event_type'], $e['title'], $e['description'] ?? '', '' );
		}
		foreach ( (array) ( $t['documents'] ?? array() ) as $doc ) {
			if ( empty( $doc['document_date'] ) ) {
				continue;
			}
			$label   = self::type_label( $doc['source_type'] );
			$title   = 0 === strpos( $doc['title'], $label ) ? $doc['title'] : $label . ': ' . $doc['title'];
			$items[] = array( $doc['document_date'], 'document-' . preg_replace( '/[^a-z_]/', '', $doc['source_type'] ), $title, '', TK_Public_Pages::url( 'document', $doc['source_version_id'] ) );
		}
		foreach ( (array) $t['hearings'] as $h ) {
			$w       = ! empty( $h['witnesses'] ) ? implode( ', ', $h['witnesses'] ) : '';
			$items[] = array( $h['hearing_date'], 'hearing', sprintf( __( 'דיון: %s', 'trial-knowledge' ), $h['hearing_date'] ), $w, TK_Public_Pages::url( 'hearing', $h['id'] ) );
		}
		usort(
			$items,
			static function ( $a, $b ) {
				return strcmp( $a[0], $b[0] );
			}
		);
		$out  = '<div class="tk-timeline" dir="rtl" lang="he">';
		$out .= '<form class="tk-timeline__asof" method="get"><label>' . esc_html__( 'מצב נכון לתאריך', 'trial-knowledge' ) .
			' <input type="date" name="tk_as_of" value="' . esc_attr( $as_of ) . '"></label> <button type="submit">' . esc_html__( 'הצג', 'trial-knowledge' ) . '</button></form>';
		$out .= '<ol class="tk-timeline__list">';
		foreach ( $items as $it ) {
			$title = $it[4] ? '<a href="' . esc_url( $it[4] ) . '">' . esc_html( $it[2] ) . '</a>' : esc_html( $it[2] );
			$out  .= '<li class="tk-timeline__item tk-timeline__item--' . esc_attr( $it[1] ) . '"><time datetime="' . esc_attr( $it[0] ) . '">' . esc_html( $it[0] ) . '</time> ' .
				'<span class="tk-timeline__title">' . $title . '</span>' . ( $it[3] ? '<span class="tk-timeline__desc">' . esc_html( $it[3] ) . '</span>' : '' ) . '</li>';
		}
		return $out . '</ol></div>';
	}

	public static function ask_form( array $attrs = array() ) {
		$id     = 'tk-ask-' . wp_rand( 1000, 999999 );
		$prompt = isset( $attrs['placeholder'] ) ? $attrs['placeholder'] : __( 'שאלו שאלה על המשפט…', 'trial-knowledge' );
		// how much material an answer is drawn from, for the waiting panel (2.7.3); nothing if the guide is unavailable
		$scope = '';
		try {
			$home   = TK_Guides::home();
			$counts = (array) ( $home['counts'] ?? array() );
			$scope  = ' data-hearings="' . (int) ( $counts['hearings'] ?? 0 ) . '" data-witnesses="' . count( (array) ( $home['witnesses'] ?? array() ) ) .
				'" data-documents="' . (int) array_sum( array_map( 'intval', (array) ( $counts['documents'] ?? array() ) ) ) . '"';
		} catch ( TK_Api_Error $e ) {
			$scope = '';
		}
		return '<div class="tk-ask" dir="rtl" lang="he" data-endpoint="' . esc_url( rest_url( 'trial-knowledge/v1/ask' ) ) . '"' . $scope . '>' .
			'<form class="tk-ask__form" novalidate><label for="' . esc_attr( $id ) . '" class="tk-ask__label">' . esc_html__( 'שאלו את המשפט', 'trial-knowledge' ) . '</label>' .
			'<textarea id="' . esc_attr( $id ) . '" class="tk-ask__q" name="question" rows="2" maxlength="500" required placeholder="' . esc_attr( $prompt ) . '"></textarea>' .
			'<button type="submit" class="tk-ask__btn">' . esc_html__( 'שאלו', 'trial-knowledge' ) . '</button></form>' .
			TK_Render_Nav::ask_examples() .
			'<p class="tk-ask__more"><a href="' . esc_url( TK_Public_Pages::section_url( 'questions' ) ) . '">' . esc_html__( 'שאלות שמבקרים כבר שאלו, והתשובות להן ←', 'trial-knowledge' ) . '</a></p>' .
			'<div class="tk-ask__out" aria-live="polite" aria-busy="false"></div>' .
			'<p class="tk-ask__note tk-muted">' . esc_html__( 'התשובות נשענות רק על חומר שפורסם במאגר, עם ציטוט לכל קביעה. ייתכנו טעויות; המקור הוא הקובע.', 'trial-knowledge' ) . '</p></div>';
	}

	/**
	 * @param array $env AnswerEnvelope.
	 */
	public static function answer( array $env ) {
		$cits = array();
		foreach ( $env['citations'] as $c ) {
			$cits[ $c['source_unit_id'] ] = $c;
		}
		$labels = array(
			'why'            => 'למה',
			'supports'       => 'מה מחזק?',
			'weakens'        => 'מה מחליש או סותר?',
			'court_position' => 'מה אמר בית המשפט?',
			'status'         => 'סטטוס',
			'limitation'     => 'הסתייגות',
			'allegation'     => 'טענת התביעה',
			'defense'        => 'מה התגלה בדיונים',
			'significance'   => 'המשמעות',
			'prosecution'    => 'תשובת התביעה',
		);
		$out = '<article class="tk-answer tk-answer--' . esc_attr( $env['answer_status'] ) . '" dir="rtl" lang="he"><p class="tk-answer__short">' . esc_html( $env['answer_short'] ) . '</p>';
		// consecutive sections of kind defense form one section "מה התגלה בדיונים" (2.7.5); 2.7.12: as paragraphs,
		// each with its sources — a numbered list of fragments read as a list of talking points
		$groups = array();
		foreach ( $env['sections'] as $s ) {
			$last = count( $groups ) - 1;
			if ( 'defense' === $s['kind'] && $last >= 0 && 'defense' === $groups[ $last ]['kind'] ) {
				$groups[ $last ]['items'][] = $s;
			} else {
				$groups[] = array( 'kind' => $s['kind'], 'items' => array( $s ) );
			}
		}
		foreach ( $groups as $g ) {
			$paras = array();
			foreach ( $g['items'] as $s ) {
				$links = array();
				foreach ( $s['citation_ids'] as $cid ) {
					if ( isset( $cits[ $cid ] ) ) {
						$links[] = self::citation_link( $cits[ $cid ] );
					}
				}
				$paras[] = '<p>' . esc_html( $s['text'] ) . '</p>' . ( $links ? '<p class="tk-point__meta">' . implode( ' ', $links ) . '</p>' : '' );
			}
			$body = count( $paras ) > 1 ? '<div class="tk-answer__paras">' . implode( '', array_map( static function ( $p ) {
				return '<div class="tk-answer__para">' . $p . '</div>';
			}, $paras ) ) . '</div>' : $paras[0];
			$out .= '<section class="tk-answer__sec tk-answer__sec--' . esc_attr( $g['kind'] ) . '"><h3>' . esc_html( $labels[ $g['kind'] ] ?? $g['kind'] ) . '</h3>' . $body . '</section>';
		}
		if ( empty( $env['sections'] ) || 'requires_human_review' === $env['answer_status'] ) {
			if ( $cits ) {
				$out .= '<ul class="tk-answer__sources">';
				foreach ( $cits as $c ) {
					$out .= '<li>' . self::citation_link( $c ) . '</li>';
				}
				$out .= '</ul>';
			}
		}
		$out .= '<p class="tk-answer__meta tk-muted">' . esc_html( sprintf( __( 'נכון ל־%1$s · גרסת מאגר %2$s', 'trial-knowledge' ), substr( $env['as_of'], 0, 10 ), $env['corpus_version'] ) ) .
			' · <a href="' . esc_url( TK_Public_Pages::url( 'answer', $env['answer_id'] ) ) . '">' . esc_html__( 'קישור קבוע', 'trial-knowledge' ) . '</a></p>';
		if ( ! empty( $env['latest_permalink'] ) ) {
			$out .= '<p class="tk-notice">' . esc_html__( 'זוהי גרסה היסטורית של התשובה. קיימת גרסה עדכנית יותר.', 'trial-knowledge' ) . '</p>';
		}
		return $out . '</article>';
	}
}
