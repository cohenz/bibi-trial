<?php
/**
 * "שאלות מבקרים" (2.7.8): the approval table for the public questions page. Every answered question arrives as
 * "ממתינה"; the admin shows or hides it, fixes how it reads, sets its topic, and accepts a newer answer to a question
 * that is already shown. Nothing reaches the site without a click here.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Admin_Questions {

	const ACTION      = 'tk_questions';
	const HELD_ACTION = 'tk_questions_held';

	public static function init() {
		add_action( 'admin_post_' . self::ACTION, array( __CLASS__, 'handle' ) );
		add_action( 'admin_post_' . self::HELD_ACTION, array( __CLASS__, 'handle_held' ) );
	}

	/** 2.7.10: answers the automatic checks held, still undecided — from the API (nothing is stored for them here). */
	public static function held_items() {
		$res = tk_api()->get( '/v2/admin/answers?status=requires_human_review&visitors=true&limit=50', true );
		return array_values(
			array_filter(
				(array) ( $res['items'] ?? array() ),
				static function ( $it ) {
					return empty( $it['human_decision'] );
				}
			)
		);
	}

	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_REVIEW ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		TK_Questions::maybe_upgrade();
		$state = isset( $_GET['tk_state'] ) ? sanitize_key( wp_unslash( $_GET['tk_state'] ) ) : 'pending'; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- read-only filter
		if ( ! in_array( $state, array( 'all', 'held' ), true ) && ! in_array( $state, TK_Questions::STATES, true ) ) {
			$state = 'pending';
		}
		echo '<div class="wrap tk-admin" dir="rtl"><h1>' . esc_html__( 'שאלות מבקרים', 'trial-knowledge' ) . '</h1>';
		if ( isset( $_GET['tk_msg'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification.Recommended
			echo '<div class="notice notice-info is-dismissible"><p>' . esc_html( sanitize_text_field( wp_unslash( $_GET['tk_msg'] ) ) ) . '</p></div>'; // phpcs:ignore WordPress.Security.NonceVerification.Recommended
		}
		$held  = array();
		$error = '';
		try {
			$held = self::held_items();
		} catch ( TK_Api_Error $e ) {
			$error = $e->getMessage();
		}
		$counts         = TK_Questions::counts();
		$counts['held'] = count( $held );
		if ( 'held' === $state ) {
			$details = array();
			foreach ( array_slice( $held, 0, 15 ) as $it ) {
				try {
					$details[] = (array) tk_api()->get( '/v2/admin/answers/' . rawurlencode( (string) $it['answer_id'] ), true );
				} catch ( TK_Api_Error $e ) {
					$error = $e->getMessage();
				}
			}
			echo self::tabs( $counts, $state ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped
			echo '' !== $error ? '<div class="notice notice-error"><p>' . esc_html( $error ) . '</p></div>' : ''; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
			echo self::render_held( $details ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render_held()
		} else {
			echo self::render( TK_Questions::rows( 'all' === $state ? '' : $state ), $counts, $state, (array) get_option( TK_Questions::OPT_LAST, array() ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render()
		}
		echo '</div>';
	}

	/**
	 * @param array  $rows   Rows of the current tab.
	 * @param array  $counts state → count.
	 * @param string $state  Current tab.
	 * @param array  $last   Last sync (at, result | error).
	 */
	public static function render( array $rows, array $counts, $state, array $last ) {
		$out   = '<p>' . esc_html__( 'שאלות שמבקרים שאלו ונענו. שאלה מופיעה בעמוד "שאלות ותשובות" רק אחרי שתאשרו אותה כאן. התור מתעדכן כל שעה.', 'trial-knowledge' ) . ' ';
		$out  .= '<a href="' . esc_url( TK_Public_Pages::section_url( 'questions' ) ) . '" target="_blank" rel="noopener">' . esc_html__( 'לעמוד הציבורי', 'trial-knowledge' ) . '</a></p>';
		$out  .= '<p class="description">' . esc_html( self::last_line( $last ) ) . '</p>';
		$out  .= self::tabs( $counts, $state );
		$out .= '<form method="post" action="' . esc_url( admin_url( 'admin-post.php' ) ) . '">' . wp_nonce_field( self::ACTION, '_wpnonce', true, false ) .
			'<input type="hidden" name="action" value="' . esc_attr( self::ACTION ) . '"><input type="hidden" name="tk_state" value="' . esc_attr( $state ) . '">';
		$out .= '<p><button type="submit" class="button" name="do" value="sync">' . esc_html__( 'בדיקת שאלות חדשות עכשיו', 'trial-knowledge' ) . '</button> ';
		if ( $rows ) {
			$out .= '<button type="submit" class="button button-primary" name="do" value="bulk:shown">' . esc_html__( 'הצגת המסומנות', 'trial-knowledge' ) . '</button> ' .
				'<button type="submit" class="button" name="do" value="bulk:hidden">' . esc_html__( 'הסתרת המסומנות', 'trial-knowledge' ) . '</button> ' .
				'<button type="submit" class="button" name="do" value="save">' . esc_html__( 'שמירת השינויים בטבלה', 'trial-knowledge' ) . '</button>';
		}
		$out .= '</p>';
		if ( ! $rows ) {
			return $out . '<p>' . esc_html__( 'אין שאלות בלשונית הזו.', 'trial-knowledge' ) . '</p></form>';
		}
		$out .= '<table class="widefat striped tk-qadmin"><thead><tr><td class="check-column"><input type="checkbox" class="tk-qadmin__all" aria-label="' . esc_attr__( 'סימון הכול', 'trial-knowledge' ) . '"></td>' .
			'<th>' . esc_html__( 'השאלה (כפי שתוצג)', 'trial-knowledge' ) . '</th><th>' . esc_html__( 'נושא', 'trial-knowledge' ) . '</th><th>' . esc_html__( 'פתיחות', 'trial-knowledge' ) . '</th>' .
			'<th>' . esc_html__( 'מצב', 'trial-knowledge' ) . '</th><th>' . esc_html__( 'פעולה', 'trial-knowledge' ) . '</th></tr></thead><tbody>';
		$snames = array( 'pending' => 'ממתינה', 'shown' => 'מוצגת', 'hidden' => 'מוסתרת' );
		foreach ( $rows as $r ) {
			$k   = (string) $r['qkey'];
			$env = json_decode( (string) $r['envelope'], true );
			$out .= '<tr><th scope="row" class="check-column"><input type="checkbox" name="sel[]" value="' . esc_attr( $k ) . '"></th><td>' .
				'<input type="text" class="large-text" name="rows[' . esc_attr( $k ) . '][display_question]" value="' . esc_attr( TK_Questions::label( $r ) ) . '" aria-label="' . esc_attr__( 'נוסח השאלה', 'trial-knowledge' ) . '">';
			if ( '' !== trim( (string) $r['display_question'] ) ) {
				$out .= '<p class="description">' . esc_html__( 'במקור:', 'trial-knowledge' ) . ' ' . esc_html( (string) $r['question'] ) . '</p>';
			}
			$out .= '<details><summary>' . esc_html( sprintf( __( 'התשובה (%s)', 'trial-knowledge' ), substr( (string) $r['answered_at'], 0, 10 ) ) ) . '</summary>' .
				( is_array( $env ) ? TK_Render::answer( $env ) : '' ) . '</details>';
			if ( '' !== (string) $r['next_envelope'] ) {
				$next = json_decode( (string) $r['next_envelope'], true );
				$out .= '<details class="tk-qadmin__next"><summary><strong>' . esc_html__( 'יש תשובה חדשה יותר — לא מוצגת עד שתאשרו', 'trial-knowledge' ) . '</strong></summary>' .
					( is_array( $next ) ? TK_Render::answer( $next ) : '' ) . '</details>';
			}
			$out .= '</td><td><select name="rows[' . esc_attr( $k ) . '][topic]">';
			foreach ( TK_Questions::TOPICS as $tk => $tl ) {
				$out .= '<option value="' . esc_attr( $tk ) . '"' . ( (string) $tk === (string) $r['topic'] ? ' selected' : '' ) . '>' . esc_html( $tl ) . '</option>';
			}
			$out .= '</select></td><td>' . (int) $r['opens'] . '</td><td>' . esc_html( $snames[ $r['state'] ] ?? (string) $r['state'] ) . '</td><td>';
			if ( 'shown' !== $r['state'] ) {
				$out .= '<button type="submit" class="button button-primary" name="do" value="shown:' . esc_attr( $k ) . '">' . esc_html__( 'הצגה', 'trial-knowledge' ) . '</button> ';
			}
			if ( 'hidden' !== $r['state'] ) {
				$out .= '<button type="submit" class="button" name="do" value="hidden:' . esc_attr( $k ) . '">' . esc_html__( 'הסתרה', 'trial-knowledge' ) . '</button> ';
			}
			if ( '' !== (string) $r['next_envelope'] ) {
				$out .= '<button type="submit" class="button" name="do" value="accept:' . esc_attr( $k ) . '">' . esc_html__( 'החלפה בתשובה החדשה', 'trial-knowledge' ) . '</button>';
			}
			$out .= '</td></tr>';
		}
		return $out . '</tbody></table></form>';
	}

	/** The tabs: the questions' states, all, and the answers held for the editor. */
	public static function tabs( array $counts, $state ) {
		$base  = admin_url( 'admin.php?page=trial-knowledge-questions' );
		$names = array( 'pending' => 'ממתינות', 'shown' => 'מוצגות באתר', 'hidden' => 'מוסתרות', 'all' => 'הכול', 'held' => 'תשובות שנעצרו לבדיקה' );
		$tabs  = array();
		foreach ( $names as $k => $label ) {
			$n      = 'all' === $k ? array_sum( array_intersect_key( $counts, array_flip( TK_Questions::STATES ) ) ) : (int) ( $counts[ $k ] ?? 0 );
			$tabs[] = '<li><a href="' . esc_url( add_query_arg( 'tk_state', $k, $base ) ) . '"' . ( $k === $state ? ' class="current" aria-current="page"' : '' ) . '>' . esc_html( $label ) . ' <span class="count">(' . $n . ')</span></a></li>';
		}
		return '<ul class="subsubsub">' . implode( ' | ', $tabs ) . '</ul><br class="clear">';
	}

	/** Why the automatic checks held an answer, in plain words. @param array $gate gate_report. */
	public static function why_held( array $gate ) {
		$names = array(
			'support'          => 'במשפט מסוים יש מעט מילים משותפות עם הקטע שהוא מצטט (בדיקה מכנית)',
			'verifier'         => 'הבודק האוטומטי לא אישר חלק מהמשפטים',
			'citation'         => 'משפט מצטט קטע שאינו מפורסם או לא קיים',
			'judicial_wording' => 'נוסח שנשמע כמו החלטה של בית המשפט, בלי החלטה מצוטטת',
			'absolute_wording' => 'נוסח מוחלט ("הוכח", "הופרך")',
		);
		$out = array();
		foreach ( (array) ( $gate['gates'] ?? array() ) as $g ) {
			if ( empty( $g['passed'] ) ) {
				$out[] = $names[ $g['gate'] ?? '' ] ?? (string) ( $g['gate'] ?? '' );
			}
		}
		if ( ! empty( $gate['risk_flags'] ) ) {
			$out[] = 'נושא רגיש: ' . implode( ', ', (array) $gate['risk_flags'] );
		}
		return $out;
	}

	/**
	 * Answers held for the editor: the writer's draft section by section, what the checks said about each, a box to
	 * leave a section out (ticked for what the verifier did not approve), approve or reject. @param array $items details.
	 */
	public static function render_held( array $items ) {
		$out = '<p>' . esc_html__( 'תשובות שנכתבו אבל נעצרו בבדיקה האוטומטית. בינתיים המבקר רואה רק קטעים מהפרוטוקול. אישור מפרסם את התשובה (בלי המשפטים המסומנים "להשמיט"): מי שישאל את השאלה שוב יקבל אותה, והיא תיכנס ללשונית "ממתינות" לעמוד השאלות.', 'trial-knowledge' ) . '</p>';
		if ( ! $items ) {
			return $out . '<p>' . esc_html__( 'אין תשובות שמחכות לבדיקה.', 'trial-knowledge' ) . '</p>';
		}
		$kinds = array( 'allegation' => 'מה טוען כתב האישום', 'defense' => 'לטובת ההגנה', 'prosecution' => 'התביעה', 'court_position' => 'בית המשפט', 'why' => 'הסבר', 'supports' => 'מחזק', 'weakens' => 'מחליש', 'status' => 'סטטוס', 'limitation' => 'הסתייגות' );
		foreach ( $items as $a ) {
			$id    = (string) ( $a['answer_id'] ?? '' );
			$draft = (array) ( $a['writer']['output'] ?? array() );
			$v     = array();
			foreach ( (array) ( $a['verifier']['output']['assertions'] ?? array() ) as $x ) {
				$v[ (string) ( $x['path'] ?? '' ) ] = $x;
			}
			$weak = array();
			foreach ( (array) ( $a['gate_report']['gates'] ?? array() ) as $g ) {
				foreach ( (array) ( $g['details'] ?? array() ) as $d ) {
					if ( ! empty( $d['path'] ) ) {
						$weak[ (string) $d['path'] ] = true;
					}
				}
			}
			$out .= '<div class="tk-held postbox" style="padding:12px 16px;margin-block:16px"><h2 style="margin-top:0">' . esc_html( (string) ( $a['question'] ?? '' ) ) . '</h2>' .
				'<p class="description">' . esc_html( substr( (string) ( $a['created_at'] ?? '' ), 0, 16 ) . ' · ' . __( 'למה נעצרה:', 'trial-knowledge' ) . ' ' . ( implode( ' · ', self::why_held( (array) ( $a['gate_report'] ?? array() ) ) ) ?: '—' ) ) . '</p>';
			if ( empty( $draft['sections'] ) ) {
				$out .= '<p>' . esc_html__( 'אין טיוטה כתובה לתשובה הזו (הכתיבה נכשלה). אפשר רק לדחות.', 'trial-knowledge' ) . '</p>';
			}
			$out .= '<form method="post" action="' . esc_url( admin_url( 'admin-post.php' ) ) . '">' . wp_nonce_field( self::HELD_ACTION . '_' . $id, '_wpnonce', true, false ) .
				'<input type="hidden" name="action" value="' . esc_attr( self::HELD_ACTION ) . '"><input type="hidden" name="answer_id" value="' . esc_attr( $id ) . '">';
			if ( ! empty( $draft['sections'] ) ) {
				$sv   = $v['answer_short'] ?? array();
				$out .= '<p><strong>' . esc_html__( 'בקצרה:', 'trial-knowledge' ) . '</strong> ' . esc_html( (string) ( $draft['answer_short'] ?? '' ) ) . self::verdict( $sv, isset( $weak['answer_short'] ) ) . '</p>';
				$out .= '<table class="widefat striped"><thead><tr><th>' . esc_html__( 'להשמיט', 'trial-knowledge' ) . '</th><th>' . esc_html__( 'סוג', 'trial-knowledge' ) . '</th><th>' . esc_html__( 'המשפט', 'trial-knowledge' ) . '</th><th>' . esc_html__( 'מה אמרו הבדיקות', 'trial-knowledge' ) . '</th></tr></thead><tbody>';
				foreach ( (array) $draft['sections'] as $i => $sec ) {
					$path = 'sections/' . $i;
					$x    = $v[ $path ] ?? array();
					$bad  = $x && ( 'yes' !== ( $x['supported'] ?? '' ) || empty( $x['attribution_ok'] ) || ! empty( $x['judicial_overstatement'] ) || ! empty( $x['false_premise'] ) );
					$out .= '<tr><td><input type="checkbox" name="omit[]" value="' . esc_attr( $path ) . '"' . ( $bad ? ' checked' : '' ) . ' aria-label="' . esc_attr__( 'להשמיט את המשפט', 'trial-knowledge' ) . '"></td>' .
						'<td>' . esc_html( $kinds[ $sec['kind'] ?? '' ] ?? (string) ( $sec['kind'] ?? '' ) ) . '</td><td>' . esc_html( (string) ( $sec['text'] ?? '' ) ) . '</td><td>' . self::verdict( $x, isset( $weak[ $path ] ) ) . '</td></tr>';
				}
				$out .= '</tbody></table>';
			}
			$out .= '<p>' . ( ! empty( $draft['sections'] ) ? '<button type="submit" class="button button-primary" name="decision" value="approve">' . esc_html__( 'אישור ופרסום', 'trial-knowledge' ) . '</button> ' : '' ) .
				'<button type="submit" class="button" name="decision" value="reject">' . esc_html__( 'דחייה (להשאיר רק קטעים)', 'trial-knowledge' ) . '</button></p></form></div>';
		}
		return $out;
	}

	/** One line on what the verifier and the mechanical check said about a sentence. */
	private static function verdict( array $x, $weak ) {
		$parts = array();
		if ( $x ) {
			$ok      = 'yes' === ( $x['supported'] ?? '' ) && ! empty( $x['attribution_ok'] ) && empty( $x['judicial_overstatement'] ) && empty( $x['false_premise'] );
			$parts[] = $ok ? '✓ ' . __( 'הבודק אישר', 'trial-knowledge' ) : '✗ ' . __( 'הבודק לא אישר', 'trial-knowledge' ) . ( ! empty( $x['note'] ) ? ': ' . (string) $x['note'] : '' );
		}
		if ( $weak ) {
			$parts[] = __( 'מעט מילים משותפות עם הקטע המצוטט', 'trial-knowledge' );
		}
		return $parts ? ' <span class="description">' . esc_html( implode( ' · ', $parts ) ) . '</span>' : '';
	}

	public static function handle_held() {
		if ( ! current_user_can( TK_Permissions::CAP_REVIEW ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ), 403 );
		}
		$id = isset( $_POST['answer_id'] ) ? sanitize_text_field( wp_unslash( $_POST['answer_id'] ) ) : '';
		check_admin_referer( self::HELD_ACTION . '_' . $id );
		$decision = isset( $_POST['decision'] ) ? sanitize_key( wp_unslash( $_POST['decision'] ) ) : '';
		$omit     = isset( $_POST['omit'] ) ? array_values( array_filter( array_map( 'sanitize_text_field', (array) wp_unslash( $_POST['omit'] ) ), static function ( $p ) {
			return 1 === preg_match( '#^sections/[0-9]{1,2}$#', $p );
		} ) ) : array();
		$back     = add_query_arg( array( 'page' => 'trial-knowledge-questions', 'tk_state' => 'held' ), admin_url( 'admin.php' ) );
		if ( ! preg_match( '/^[0-9a-f-]{36}$/', $id ) || ! in_array( $decision, array( 'approve', 'reject' ), true ) ) {
			wp_safe_redirect( add_query_arg( 'tk_msg', rawurlencode( __( 'בקשה לא תקינה.', 'trial-knowledge' ) ), $back ) );
			exit;
		}
		try {
			$res = (array) tk_api()->post( '/v2/admin/answers/' . $id . '/review', array( 'decision' => $decision, 'omit' => $omit ), true );
			if ( 'approve' === $decision ) {
				$env = (array) ( $res['envelope'] ?? array() );
				$row = TK_Questions::merge(
					TK_Questions::get( TK_Questions::qkey( (string) ( $env['normalized_question'] ?? '' ) ) ),
					array( 'answer_id' => $id, 'question' => (string) ( $env['question'] ?? '' ), 'normalized_question' => (string) ( $env['normalized_question'] ?? '' ), 'answer_status' => (string) ( $res['answer_status'] ?? 'answered' ), 'created_at' => gmdate( 'c' ), 'envelope' => $env ),
					gmdate( 'Y-m-d H:i:s' )
				);
				if ( $row ) {
					TK_Questions::put( $row );
				}
				$msg = sprintf( __( 'התשובה פורסמה (%d משפטים הושמטו). היא בלשונית "ממתינות" לעמוד השאלות.', 'trial-knowledge' ), count( $omit ) );
			} else {
				$msg = __( 'התשובה נדחתה; המבקרים ימשיכו לראות רק את הקטעים.', 'trial-knowledge' );
			}
		} catch ( TK_Api_Error $e ) {
			$msg = $e->getMessage();
		}
		wp_safe_redirect( add_query_arg( 'tk_msg', rawurlencode( $msg ), $back ) );
		exit;
	}

	private static function last_line( array $last ) {
		if ( empty( $last['at'] ) ) {
			return __( 'עדיין לא נבדקו שאלות חדשות.', 'trial-knowledge' );
		}
		if ( ! empty( $last['error'] ) ) {
			return sprintf( __( 'בדיקה אחרונה: %1$s UTC — שגיאה: %2$s', 'trial-knowledge' ), $last['at'], $last['error'] );
		}
		$r = (array) ( $last['result'] ?? array() );
		return sprintf( __( 'בדיקה אחרונה: %1$s UTC — %2$d חדשות, %3$d עודכנו.', 'trial-knowledge' ), $last['at'], (int) ( $r['new'] ?? 0 ), (int) ( $r['updated'] ?? 0 ) );
	}

	/**
	 * What the form asks for: [action, keys]. Pure, for tests.
	 *
	 * @param string $do  The pressed button's value.
	 * @param array  $sel Ticked row keys.
	 */
	public static function parse_do( $do, array $sel ) {
		$do = (string) $do;
		if ( in_array( $do, array( 'sync', 'save' ), true ) ) {
			return array( $do, array() );
		}
		if ( preg_match( '/^bulk:(shown|hidden)$/', $do, $m ) ) {
			return array( $m[1], array_values( array_filter( $sel, array( __CLASS__, 'is_key' ) ) ) );
		}
		if ( preg_match( '/^(shown|hidden|accept):([0-9a-f]{64})$/', $do, $m ) ) {
			return array( $m[1], array( $m[2] ) );
		}
		return array( '', array() );
	}

	public static function is_key( $k ) {
		return is_string( $k ) && 1 === preg_match( '/^[0-9a-f]{64}$/', $k );
	}

	public static function handle() {
		if ( ! current_user_can( TK_Permissions::CAP_REVIEW ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ), 403 );
		}
		check_admin_referer( self::ACTION );
		$state = isset( $_POST['tk_state'] ) ? sanitize_key( wp_unslash( $_POST['tk_state'] ) ) : 'pending';
		$do    = isset( $_POST['do'] ) ? sanitize_text_field( wp_unslash( $_POST['do'] ) ) : '';
		$sel   = isset( $_POST['sel'] ) ? array_map( 'sanitize_key', (array) wp_unslash( $_POST['sel'] ) ) : array();
		$rows  = isset( $_POST['rows'] ) && is_array( $_POST['rows'] ) ? wp_unslash( $_POST['rows'] ) : array(); // phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized -- sanitized per field below
		$msg   = '';
		// the edits in the table (wording, topic) are kept whatever button was pressed
		$saved = 0;
		foreach ( $rows as $k => $f ) {
			if ( ! self::is_key( $k ) || ! is_array( $f ) ) {
				continue;
			}
			$change = array( 'topic' => sanitize_key( (string) ( $f['topic'] ?? '' ) ) );
			if ( isset( $f['display_question'] ) ) {
				$change['display_question'] = sanitize_text_field( (string) $f['display_question'] );
			}
			$saved += TK_Questions::update( $k, $change ) ? 1 : 0;
		}
		list( $what, $keys ) = self::parse_do( $do, $sel );
		if ( 'sync' === $what ) {
			try {
				$r   = TK_Questions::sync();
				$msg = sprintf( __( 'נבדק: %1$d שאלות חדשות, %2$d עודכנו.', 'trial-knowledge' ), $r['new'], $r['updated'] );
			} catch ( TK_Api_Error $e ) {
				$msg = $e->getMessage();
			}
		} elseif ( in_array( $what, array( 'shown', 'hidden' ), true ) ) {
			foreach ( $keys as $k ) {
				TK_Questions::update( $k, array( 'state' => $what ) );
			}
			$msg = sprintf( 'shown' === $what ? __( '%d שאלות מוצגות עכשיו באתר.', 'trial-knowledge' ) : __( '%d שאלות הוסתרו.', 'trial-knowledge' ), count( $keys ) );
		} elseif ( 'accept' === $what ) {
			foreach ( $keys as $k ) {
				TK_Questions::update( $k, array( 'accept_update' => true ) );
			}
			$msg = __( 'התשובה החדשה מוצגת עכשיו.', 'trial-knowledge' );
		} else {
			$msg = __( 'השינויים נשמרו.', 'trial-knowledge' );
		}
		wp_safe_redirect( add_query_arg( array( 'page' => 'trial-knowledge-questions', 'tk_state' => $state, 'tk_msg' => rawurlencode( $msg ) ), admin_url( 'admin.php' ) ) );
		exit;
	}
}
