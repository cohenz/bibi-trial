<?php
/**
 * Review and publication: queue of review tasks; artifact detail with writer
 * output, verifier output and cited sources side by side; approve / reject /
 * request changes / publish / unpublish. Every action is a signed API call
 * that the API audits; WordPress adds capability and nonce checks.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Admin_Review {

	public static function init() {
		add_action( 'wp_ajax_tk_review_tasks', array( __CLASS__, 'ajax_tasks' ) );
		add_action( 'wp_ajax_tk_artifact', array( __CLASS__, 'ajax_artifact' ) );
		add_action( 'wp_ajax_tk_review_action', array( __CLASS__, 'ajax_review' ) );
		add_action( 'wp_ajax_tk_publish_action', array( __CLASS__, 'ajax_publish' ) );
		add_action( 'wp_ajax_tk_object_review', array( __CLASS__, 'ajax_object_review' ) );
	}

	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_REVIEW ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		$can_publish = current_user_can( TK_Permissions::CAP_PUBLISH );
		?>
		<div class="wrap tk-admin" dir="rtl" data-can-publish="<?php echo $can_publish ? '1' : '0'; ?>">
			<h1><?php esc_html_e( 'ביקורת ופרסום', 'trial-knowledge' ); ?></h1>
			<p class="description"><?php esc_html_e( 'שום פריט אינו מתפרסם בלי אישור מפורש. פריטים שנכשלו בשערי הציטוט אינם ניתנים לאישור.', 'trial-knowledge' ); ?></p>
			<div class="tk-review">
				<div class="tk-review__queue tk-card">
					<h2><?php esc_html_e( 'תור ביקורת', 'trial-knowledge' ); ?> <button type="button" class="button" id="tk-refresh-tasks"><?php esc_html_e( 'רענון', 'trial-knowledge' ); ?></button></h2>
					<ul id="tk-tasks" class="tk-tasks" aria-live="polite"></ul>
				</div>
				<div class="tk-review__detail tk-card" id="tk-artifact" tabindex="-1" aria-live="polite">
					<p class="tk-muted"><?php esc_html_e( 'בחרו פריט מהתור.', 'trial-knowledge' ); ?></p>
				</div>
			</div>
		</div>
		<?php
	}

	private static function fail( TK_Api_Error $e ) {
		wp_send_json_error( array( 'message' => $e->getMessage(), 'code' => $e->api_code, 'details' => $e->details ), $e->status >= 400 && $e->status < 600 ? $e->status : 502 );
	}

	private static function uuid( $key ) {
		$v = isset( $_POST[ $key ] ) ? sanitize_text_field( wp_unslash( $_POST[ $key ] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing -- verified by caller
		if ( ! preg_match( '/^[0-9a-f-]{36}$/', $v ) ) {
			wp_send_json_error( array( 'message' => 'invalid id' ), 400 );
		}
		return $v;
	}

	public static function ajax_tasks() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_REVIEW, 'tk_review' );
		try {
			wp_send_json_success( tk_api()->get( '/v2/admin/review-tasks', true ) );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
	}

	public static function ajax_artifact() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_REVIEW, 'tk_review' );
		$id = self::uuid( 'artifact_id' );
		try {
			wp_send_json_success( tk_api()->get( '/v2/admin/artifacts/' . $id, true ) );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
	}

	public static function ajax_review() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_REVIEW, 'tk_review' );
		$id       = self::uuid( 'artifact_id' );
		$decision = isset( $_POST['decision'] ) ? sanitize_key( wp_unslash( $_POST['decision'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing
		$notes    = isset( $_POST['notes'] ) ? sanitize_textarea_field( wp_unslash( $_POST['notes'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing
		$map      = array( 'approve' => 'approve', 'reject' => 'reject', 'request_changes' => 'revise' );
		if ( ! isset( $map[ $decision ] ) ) {
			wp_send_json_error( array( 'message' => 'invalid decision' ), 400 );
		}
		try {
			wp_send_json_success( tk_api()->post( '/v2/admin/artifacts/' . $id . '/review', array( 'decision' => $map[ $decision ], 'notes' => $notes ), true ) );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
	}

	public static function ajax_publish() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_PUBLISH, 'tk_publish' );
		$id   = self::uuid( 'artifact_id' );
		$what = isset( $_POST['what'] ) ? sanitize_key( wp_unslash( $_POST['what'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing
		try {
			if ( 'publish' === $what ) {
				$res = tk_api()->post( '/v2/admin/artifacts/' . $id . '/publish', array( 'include_sources' => ! empty( $_POST['include_sources'] ) ), true ); // phpcs:ignore WordPress.Security.NonceVerification.Missing
			} elseif ( 'unpublish' === $what ) {
				$reason = isset( $_POST['reason'] ) ? sanitize_text_field( wp_unslash( $_POST['reason'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing
				$res    = tk_api()->post( '/v2/admin/artifacts/' . $id . '/unpublish', array( 'reason' => $reason ? $reason : 'unpublished from WordPress' ), true );
			} else {
				wp_send_json_error( array( 'message' => 'invalid action' ), 400 );
			}
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		TK_Cache::purge( array( 'lists', 'claims' ) );
		wp_send_json_success( $res );
	}

	public static function ajax_object_review() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_REVIEW, 'tk_review' );
		$type     = isset( $_POST['object_type'] ) ? sanitize_key( wp_unslash( $_POST['object_type'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing
		$id       = isset( $_POST['object_id'] ) ? sanitize_text_field( wp_unslash( $_POST['object_id'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing
		$decision = isset( $_POST['decision'] ) ? sanitize_key( wp_unslash( $_POST['decision'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing
		$map      = array( 'approve' => 'approve', 'reject' => 'reject', 'request_changes' => 'revise' );
		if ( ! in_array( $type, array( 'qa_exchange', 'judicial_statement' ), true ) || ! isset( $map[ $decision ] ) || ! preg_match( '/^[A-Za-z0-9_-]{6,64}$/', $id ) ) {
			wp_send_json_error( array( 'message' => 'invalid request' ), 400 );
		}
		try {
			wp_send_json_success( tk_api()->post( '/v2/admin/objects/' . $type . '/' . $id . '/review', array( 'decision' => $map[ $decision ] ), true ) );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
	}
}
