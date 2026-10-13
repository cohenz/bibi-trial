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

	const ACTION = 'tk_questions';

	public static function init() {
		add_action( 'admin_post_' . self::ACTION, array( __CLASS__, 'handle' ) );
	}

	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_REVIEW ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		TK_Questions::maybe_upgrade();
		$state = isset( $_GET['tk_state'] ) ? sanitize_key( wp_unslash( $_GET['tk_state'] ) ) : 'pending'; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- read-only filter
		if ( 'all' !== $state && ! in_array( $state, TK_Questions::STATES, true ) ) {
			$state = 'pending';
		}
		echo '<div class="wrap tk-admin" dir="rtl"><h1>' . esc_html__( 'שאלות מבקרים', 'trial-knowledge' ) . '</h1>';
		if ( isset( $_GET['tk_msg'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification.Recommended
			echo '<div class="notice notice-info is-dismissible"><p>' . esc_html( sanitize_text_field( wp_unslash( $_GET['tk_msg'] ) ) ) . '</p></div>'; // phpcs:ignore WordPress.Security.NonceVerification.Recommended
		}
		echo self::render( TK_Questions::rows( 'all' === $state ? '' : $state ), TK_Questions::counts(), $state, (array) get_option( TK_Questions::OPT_LAST, array() ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render()
		echo '</div>';
	}

	/**
	 * @param array  $rows   Rows of the current tab.
	 * @param array  $counts state → count.
	 * @param string $state  Current tab.
	 * @param array  $last   Last sync (at, result | error).
	 */
	public static function render( array $rows, array $counts, $state, array $last ) {
		$base  = admin_url( 'admin.php?page=trial-knowledge-questions' );
		$names = array( 'pending' => 'ממתינות', 'shown' => 'מוצגות באתר', 'hidden' => 'מוסתרות', 'all' => 'הכול' );
		$out   = '<p>' . esc_html__( 'שאלות שמבקרים שאלו ונענו. שאלה מופיעה בעמוד "שאלות ותשובות" רק אחרי שתאשרו אותה כאן. התור מתעדכן כל שעה.', 'trial-knowledge' ) . ' ';
		$out  .= '<a href="' . esc_url( TK_Public_Pages::section_url( 'questions' ) ) . '" target="_blank" rel="noopener">' . esc_html__( 'לעמוד הציבורי', 'trial-knowledge' ) . '</a></p>';
		$out  .= '<p class="description">' . esc_html( self::last_line( $last ) ) . '</p>';
		$out  .= '<ul class="subsubsub">';
		$tabs  = array();
		foreach ( $names as $k => $label ) {
			$n      = 'all' === $k ? array_sum( $counts ) : (int) ( $counts[ $k ] ?? 0 );
			$tabs[] = '<li><a href="' . esc_url( add_query_arg( 'tk_state', $k, $base ) ) . '"' . ( $k === $state ? ' class="current" aria-current="page"' : '' ) . '>' . esc_html( $label ) . ' <span class="count">(' . $n . ')</span></a></li>';
		}
		$out .= implode( ' | ', $tabs ) . '</ul><br class="clear">';
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
