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
		$aid = isset( $_GET['tk_answer'] ) ? sanitize_text_field( wp_unslash( $_GET['tk_answer'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- read-only view
		if ( '' !== $aid ) {
			try {
				echo self::render_answer( (array) tk_api()->get( '/v2/admin/answers/' . rawurlencode( $aid ), true ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render_answer()
			} catch ( TK_Api_Error $e ) {
				echo '<div class="notice notice-error"><p>' . esc_html( $e->getMessage() ) . '</p></div>';
			}
			echo '</div>';
			return;
		}
		echo self::render( (array) $u ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render()
		try {
			echo self::render_answers( (array) tk_api()->get( '/v2/admin/answers?limit=30', true ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render_answers()
		} catch ( TK_Api_Error $e ) {
			echo '<p class="description">' . esc_html( $e->getMessage() ) . '</p>';
		}
		echo '</div>';
	}

	/** 2.7.7: the latest answers, each linking to why the engine decided what it did. @param array $r /v2/admin/answers. */
	public static function render_answers( array $r ) {
		$names = array( 'answered' => 'נענתה', 'requires_human_review' => 'נעצרה לבדיקה', 'false_premise_corrected' => 'תוקנה הנחה', 'insufficient_published_evidence' => 'אין חומר', 'refused' => 'סורבה' );
		$out   = '<h2>' . esc_html__( 'תשובות אחרונות', 'trial-knowledge' ) . '</h2><table class="widefat striped"><thead><tr><th>מתי</th><th>שאלה</th><th>מצב</th><th>הנחיה</th></tr></thead><tbody>';
		foreach ( (array) ( $r['items'] ?? array() ) as $a ) {
			$url  = add_query_arg( array( 'page' => 'trial-knowledge-costs', 'tk_answer' => (string) $a['answer_id'] ), admin_url( 'admin.php' ) );
			$out .= '<tr><td>' . esc_html( substr( (string) ( $a['created_at'] ?? '' ), 0, 16 ) ) . '</td><td><a href="' . esc_url( $url ) . '">' . esc_html( (string) ( $a['question'] ?? '' ) ) . '</a></td><td>' .
				esc_html( $names[ $a['answer_status'] ?? '' ] ?? (string) ( $a['answer_status'] ?? '' ) ) . '</td><td>' . esc_html( (string) ( $a['prompt_version'] ?? '' ) ) . '</td></tr>';
		}
		return $out . '</tbody></table>';
	}

	/** One answer: the gates, the verifier's verdict per sentence and the writer's draft. @param array $a /v2/admin/answers/{id}. */
	public static function render_answer( array $a ) {
		$back = add_query_arg( array( 'page' => 'trial-knowledge-costs' ), admin_url( 'admin.php' ) );
		$g    = (array) ( $a['gate_report'] ?? array() );
		$out  = '<p><a href="' . esc_url( $back ) . '">← ' . esc_html__( 'לכל התשובות', 'trial-knowledge' ) . '</a></p><h2>' . esc_html( (string) ( $a['question'] ?? '' ) ) . '</h2>';
		$out .= '<p>' . esc_html( sprintf( 'מצב: %1$s · שערים: %2$s · דגלים: %3$s', (string) ( $a['answer_status'] ?? '' ), (string) ( $g['state'] ?? '' ), implode( ', ', (array) ( $g['risk_flags'] ?? array() ) ) ?: '—' ) ) . '</p>';
		$out .= '<h3>שערים שנכשלו</h3><ul>';
		$failed = 0;
		foreach ( (array) ( $g['gates'] ?? array() ) as $gate ) {
			if ( empty( $gate['passed'] ) ) {
				++$failed;
				$out .= '<li><strong>' . esc_html( (string) ( $gate['gate'] ?? '' ) ) . '</strong>: <code>' . esc_html( mb_substr( wp_json_encode( $gate['details'] ?? array(), JSON_UNESCAPED_UNICODE ), 0, 1500 ) ) . '</code></li>';
			}
		}
		$out .= ( $failed ? '' : '<li>אין</li>' ) . '</ul>';
		$ret  = (array) ( $g['retrieval'] ?? array() );
		$out .= '<p class="description">' . esc_html( sprintf( 'שליפה: הגנה %1$s · חיפוש %2$s · סקירות עדים %3$s · תקצירים %4$s', (string) ( $ret['defense'] ?? 0 ), (string) ( $ret['search_relevant'] ?? $ret['search'] ?? 0 ), count( (array) ( $ret['witness_guides'] ?? array() ) ), count( (array) ( $ret['digests'] ?? array() ) ) ) ) . '</p>';
		$v = (array) ( $a['verifier']['output'] ?? array() );
		if ( $v ) {
			$out .= '<h3>' . esc_html( sprintf( 'הבודק: %s', (string) ( $v['verdict'] ?? '' ) ) ) . '</h3><table class="widefat striped"><thead><tr><th>משפט</th><th>נתמך</th><th>ייחוס תקין</th><th>הערה</th></tr></thead><tbody>';
			foreach ( (array) ( $v['assertions'] ?? array() ) as $x ) {
				$out .= '<tr><td>' . esc_html( (string) ( $x['path'] ?? '' ) ) . '</td><td>' . esc_html( (string) ( $x['supported'] ?? '' ) ) . '</td><td>' . ( empty( $x['attribution_ok'] ) ? '✗' : '✓' ) . '</td><td>' . esc_html( (string) ( $x['note'] ?? '' ) ) . '</td></tr>';
			}
			$out .= '</tbody></table>';
			foreach ( (array) ( $v['omitted_counterevidence'] ?? array() ) as $o ) {
				$out .= '<p>' . esc_html( 'חומר סותר שהושמט: ' . (string) ( $o['note'] ?? '' ) . ' (' . implode( ', ', (array) ( $o['source_unit_ids'] ?? array() ) ) . ')' ) . '</p>';
			}
		}
		$w = (array) ( $a['writer']['output'] ?? array() );
		if ( $w ) {
			$out .= '<h3>טיוטת הכותב</h3><p><em>answer_short</em>: ' . esc_html( (string) ( $w['answer_short'] ?? '' ) ) . '</p><ol>';
			foreach ( (array) ( $w['sections'] ?? array() ) as $i => $sec ) {
				$out .= '<li value="' . esc_attr( (string) $i ) . '"><code>' . esc_html( (string) ( $sec['kind'] ?? '' ) ) . '</code> ' . esc_html( (string) ( $sec['text'] ?? '' ) ) . '</li>';
			}
			$out .= '</ol>';
		}
		return $out;
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
