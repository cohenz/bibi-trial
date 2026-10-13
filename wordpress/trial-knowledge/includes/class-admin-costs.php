<?php
/**
 * "עלויות שאלות" (2.7.1): what "שאלו" costs per day — questions (new / stored / free / refused for the daily
 * budget), tokens of the new answers and their cost — and the limits in force. Read-only; the limits and the
 * thinking level are set in Railway (NTK_ASK_DAILY_LIMIT, NTK_ASK_VISITOR_DAILY_LIMIT, NTK_ASK_THINKING).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Admin_Costs {

	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_SETTINGS ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		echo '<div class="wrap tk-admin" dir="rtl"><h1>' . esc_html__( 'עלויות שאלות', 'trial-knowledge' ) . '</h1>';
		try {
			$u = tk_api()->get( '/v2/admin/ask/usage?days=30', true );
		} catch ( TK_Api_Error $e ) {
			echo '<div class="notice notice-error"><p>' . esc_html( $e->getMessage() ) . '</p></div></div>';
			return;
		}
		echo self::render( (array) $u ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render()
		echo '</div>';
	}

	/** @param array $u /v2/admin/ask/usage. */
	public static function render( array $u ) {
		$lim  = (array) ( $u['limits'] ?? array() );
		$th   = (array) ( $u['thinking'] ?? array() );
		$pr   = (array) ( $u['prices_per_million'] ?? array() );
		$days = (array) ( $u['days'] ?? array() );
		$out  = '<p>' . esc_html( sprintf( __( 'מגבלות: %1$s תשובות חדשות ביום לכל האתר, %2$s לכל גולש, %3$s שאלות בדקה. תשובה שכבר נשמרה, סירוב או "אין חומר" — בחינם ולא נספרים.', 'trial-knowledge' ),
			self::n( $lim['daily'] ?? '' ), self::n( $lim['per_visitor_daily'] ?? '' ), self::n( $lim['per_minute'] ?? '' ) ) ) . '</p>';
		$out .= '<p class="description">' . esc_html( sprintf( __( 'חשיבת המודל: כותב %1$s, בודק %2$s. מחיר למיליון טוקנים: קלט %3$s$, פלט וחשיבה %4$s$.', 'trial-knowledge' ),
			(string) ( $th['writer'] ?? '' ), (string) ( $th['verifier'] ?? '' ), (string) ( $pr['input'] ?? '' ), (string) ( $pr['output_and_thinking'] ?? '' ) ) ) . '</p>';
		$out .= '<p><strong>' . esc_html( sprintf( __( 'סה״כ 30 יום: %1$s$', 'trial-knowledge' ), number_format( (float) ( $u['total_cost_usd'] ?? 0 ), 2 ) ) ) . '</strong>';
		if ( null !== ( $u['avg_cost_per_new_answer_usd'] ?? null ) ) {
			$out .= ' · ' . esc_html( sprintf( __( 'ממוצע לתשובה חדשה: %s$', 'trial-knowledge' ), number_format( (float) $u['avg_cost_per_new_answer_usd'], 3 ) ) );
		}
		$out .= '</p><table class="widefat striped"><thead><tr>';
		foreach ( array( 'יום', 'שאלות', 'חדשות', 'שמורות', 'בחינם', 'נחסמו (מכסה)', 'טוקנים קלט', 'פלט', 'חשיבה', 'עלות $' ) as $h ) {
			$out .= '<th>' . esc_html( $h ) . '</th>';
		}
		$out .= '</tr></thead><tbody>';
		foreach ( $days as $d ) {
			$q    = (array) ( $d['questions'] ?? array() );
			$out .= '<tr><td>' . esc_html( TK_Render_Guides::fmt_date( (string) ( $d['day'] ?? '' ) ) ) . '</td>';
			foreach ( array( $q['total'] ?? 0, $d['new_answers'] ?? 0, $q['cached'] ?? 0, $q['free'] ?? 0, $q['limited'] ?? 0, $d['input_tokens'] ?? 0, $d['output_tokens'] ?? 0, $d['thinking_tokens'] ?? 0 ) as $v ) {
				$out .= '<td>' . esc_html( self::n( $v ) ) . '</td>';
			}
			$out .= '<td>' . esc_html( number_format( (float) ( $d['cost_usd'] ?? 0 ), 3 ) ) . '</td></tr>';
		}
		return $out . '</tbody></table>';
	}

	private static function n( $v ) {
		return is_numeric( $v ) ? number_format( (float) $v ) : (string) $v;
	}
}
