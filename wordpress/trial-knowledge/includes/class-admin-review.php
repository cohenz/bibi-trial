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
		add_action( 'wp_ajax_tk_review_card', array( __CLASS__, 'ajax_card' ) );
		add_action( 'wp_ajax_tk_review_decide', array( __CLASS__, 'ajax_decide' ) );
	}

	/**
	 * 2.6 quick review: one item at a time — what it is, why it waits for you (in plain words), the text with the
	 * problem marked, and Yes / No. A decision moves straight to the next item; it is sent after a few seconds,
	 * so "בטל" can still take it back. No confirmation dialogs.
	 */
	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_REVIEW ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		wp_enqueue_script( 'trial-knowledge-review', TK_URL . 'assets/review.js', array(), TK_VERSION, true );
		wp_localize_script(
			'trial-knowledge-review',
			'TKReview',
			array(
				'ajax'       => admin_url( 'admin-ajax.php' ),
				'nonce'      => wp_create_nonce( 'tk_review' ),
				'canPublish' => current_user_can( TK_Permissions::CAP_PUBLISH ),
			)
		);
		?>
		<div class="wrap tk-admin tk-qr" dir="rtl">
			<h1><?php esc_html_e( 'ביקורת ופרסום', 'trial-knowledge' ); ?></h1>
			<div class="tk-qr__bar">
				<div class="tk-qr__filters" role="group" aria-label="<?php esc_attr_e( 'אילו פריטים להציג', 'trial-knowledge' ); ?>">
					<button type="button" class="tk-qr__chip is-on" data-filter="all"><?php esc_html_e( 'הכול', 'trial-knowledge' ); ?> <span data-count="all">…</span></button>
					<button type="button" class="tk-qr__chip" data-filter="issue"><?php esc_html_e( 'יש מה לבדוק', 'trial-knowledge' ); ?> <span data-count="issue">…</span></button>
					<button type="button" class="tk-qr__chip" data-filter="clean"><?php esc_html_e( 'עברו את כל הבדיקות', 'trial-knowledge' ); ?> <span data-count="clean">…</span></button>
				</div>
				<p class="tk-qr__progress" aria-live="polite"></p>
			</div>
			<div class="tk-qr__card" id="tk-qr-card" tabindex="-1" aria-live="polite"><p class="tk-muted"><?php esc_html_e( 'טוען…', 'trial-knowledge' ); ?></p></div>
			<div class="tk-qr__toast" id="tk-qr-toast" role="status" hidden></div>
			<p class="description tk-qr__keys"><?php esc_html_e( 'קיצורי מקלדת: Y (כן) · N (לא) · S או ← (דלג) · U (ביטול ההחלטה האחרונה).', 'trial-knowledge' ); ?></p>
		</div>
		<?php
	}

	/** Public page of the reviewed object (to see it in context). */
	private static function object_url( $type, $id ) {
		if ( 'document' === $type && preg_match( '/^sv_[0-9a-f]{26}$/', $id ) ) {
			return TK_Public_Pages::url( 'document', $id );
		}
		if ( 'hearing' === $type && preg_match( '/^hr_[0-9a-f]{26}$/', $id ) ) {
			return TK_Public_Pages::url( 'hearing', $id );
		}
		return '';
	}

	/** One review card: the artifact (writer output, gates, verifier, cited sources) plus display context. */
	public static function ajax_card() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_REVIEW, 'tk_review' );
		$id = self::uuid( 'artifact_id' );
		try {
			$d = tk_api()->get( '/v2/admin/artifacts/' . $id, true );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		$a   = (array) ( $d['artifact'] ?? array() );
		$ctx = array( 'url' => self::object_url( (string) ( $a['object_type'] ?? '' ), (string) ( $a['object_id'] ?? '' ) ) );
		if ( 'hearing' === ( $a['object_type'] ?? '' ) ) {
			try {
				$h               = tk_api()->get( '/v2/hearings/' . rawurlencode( (string) $a['object_id'] ) );
				$ctx['date']     = $h['hearing']['hearing_date'] ?? '';
				$ctx['witnesses'] = $h['hearing']['witnesses'] ?? array();
			} catch ( TK_Api_Error $e ) {
				$ctx['date'] = '';
			}
		}
		$d['context'] = $ctx;
		wp_send_json_success( $d );
	}

	/**
	 * Yes / No on one item. Yes = approve, then publish when approval alone did not (cited source passages are
	 * published with it, so its citations work). No = reject. Review objects (Q/A, judicial statements) likewise.
	 */
	public static function ajax_decide() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_REVIEW, 'tk_review' );
		$yes  = isset( $_POST['decision'] ) && 'yes' === sanitize_key( wp_unslash( $_POST['decision'] ) ); // phpcs:ignore WordPress.Security.NonceVerification.Missing
		$kind = isset( $_POST['kind'] ) ? sanitize_key( wp_unslash( $_POST['kind'] ) ) : 'artifact'; // phpcs:ignore WordPress.Security.NonceVerification.Missing
		try {
			if ( 'artifact' !== $kind ) {
				$oid = isset( $_POST['object_id'] ) ? sanitize_text_field( wp_unslash( $_POST['object_id'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Missing
				if ( ! in_array( $kind, array( 'qa_exchange', 'judicial_statement' ), true ) || ! preg_match( '/^[A-Za-z0-9_-]{6,64}$/', $oid ) ) {
					wp_send_json_error( array( 'message' => 'invalid request' ), 400 );
				}
				$res = tk_api()->post( '/v2/admin/objects/' . $kind . '/' . $oid . '/review', array( 'decision' => $yes ? 'approve' : 'reject' ), true );
				wp_send_json_success( array( 'review_state' => $res['review_state'] ?? ( $yes ? 'approved' : 'rejected' ) ) );
			}
			$id  = self::uuid( 'artifact_id' );
			$res = tk_api()->post( '/v2/admin/artifacts/' . $id . '/review', array( 'decision' => $yes ? 'approve' : 'reject', 'notes' => 'quick review' ), true );
			$state = (string) ( $res['review_state'] ?? '' );
			if ( $yes && 'published' !== $state && current_user_can( TK_Permissions::CAP_PUBLISH ) ) {
				tk_api()->post( '/v2/admin/artifacts/' . $id . '/publish', array( 'include_sources' => true ), true );
				$state = 'published';
			}
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		if ( $yes ) {
			TK_Cache::purge( array( 'lists', 'guide', 'timeline' ) );
		}
		wp_send_json_success( array( 'review_state' => $state ) );
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
			$res = tk_api()->post( '/v2/admin/artifacts/' . $id . '/review', array( 'decision' => $map[ $decision ], 'notes' => $notes ), true );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		if ( 'approve' === $decision ) {
			// approved guides and digests publish immediately (ADR-0014/0015); do not wait for the webhook
			TK_Cache::purge( array( 'lists', 'guide', 'timeline' ) );
		}
		wp_send_json_success( $res );
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
		TK_Cache::purge( array( 'lists', 'claims', 'guide', 'timeline' ) );
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
