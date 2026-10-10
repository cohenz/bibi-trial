<?php
/**
 * Sources: choose PDFs, upload them directly to object storage (R2/S3) with a
 * presigned URL, create ingestion jobs and follow them. The browser never
 * receives storage or API credentials; it only gets a short-lived presigned URL.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Admin_Sources {

	public static function init() {
		add_action( 'wp_ajax_tk_presign', array( __CLASS__, 'ajax_presign' ) );
		add_action( 'wp_ajax_tk_create_job', array( __CLASS__, 'ajax_create_job' ) );
		add_action( 'wp_ajax_tk_jobs', array( __CLASS__, 'ajax_jobs' ) );
		add_action( 'wp_ajax_tk_job', array( __CLASS__, 'ajax_job' ) );
		add_action( 'wp_ajax_tk_retry_job', array( __CLASS__, 'ajax_retry' ) );
	}

	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_SOURCES ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		?>
		<div class="wrap tk-admin" dir="rtl">
			<h1><?php esc_html_e( 'מקורות וקליטה', 'trial-knowledge' ); ?></h1>
			<?php if ( ! tk_api()->admin_configured() ) : ?>
				<div class="notice notice-warning"><p><?php esc_html_e( 'יש להגדיר כתובת API ומפתח שירות במסך ההגדרות.', 'trial-knowledge' ); ?></p></div>
			<?php endif; ?>
			<form id="tk-upload-form" class="tk-card" novalidate>
				<h2><?php esc_html_e( 'העלאת פרוטוקולים (PDF)', 'trial-knowledge' ); ?></h2>
				<p><label for="tk-files"><?php esc_html_e( 'קבצים', 'trial-knowledge' ); ?></label>
					<input type="file" id="tk-files" accept="application/pdf" multiple required></p>
				<p><label for="tk-date"><?php esc_html_e( 'תאריך הדיון (אם ידוע; אחרת יזוהה מהפרוטוקול)', 'trial-knowledge' ); ?></label>
					<input type="date" id="tk-date"></p>
				<p><label for="tk-crs"><?php esc_html_e( 'מעמד בתיק', 'trial-knowledge' ); ?></label>
					<select id="tk-crs">
						<option value="filed"><?php esc_html_e( 'פרוטוקול רשמי של בית המשפט', 'trial-knowledge' ); ?></option>
						<option value="unknown"><?php esc_html_e( 'לא ידוע', 'trial-knowledge' ); ?></option>
						<option value="external"><?php esc_html_e( 'מקור חיצוני', 'trial-knowledge' ); ?></option>
					</select></p>
				<p><button type="submit" class="button button-primary"><?php esc_html_e( 'העלאה ויצירת משימות קליטה', 'trial-knowledge' ); ?></button></p>
				<ol id="tk-upload-log" class="tk-log" aria-live="polite"></ol>
			</form>
			<div class="tk-card">
				<h2><?php esc_html_e( 'משימות קליטה', 'trial-knowledge' ); ?> <button type="button" class="button" id="tk-refresh-jobs"><?php esc_html_e( 'רענון', 'trial-knowledge' ); ?></button></h2>
				<table class="widefat striped" id="tk-jobs"><thead><tr>
					<th><?php esc_html_e( 'נוצר', 'trial-knowledge' ); ?></th><th><?php esc_html_e( 'מסמך', 'trial-knowledge' ); ?></th>
					<th><?php esc_html_e( 'סטטוס', 'trial-knowledge' ); ?></th><th><?php esc_html_e( 'שלב', 'trial-knowledge' ); ?></th>
					<th><?php esc_html_e( 'פעולות', 'trial-knowledge' ); ?></th></tr></thead><tbody></tbody></table>
				<div id="tk-job-detail" aria-live="polite"></div>
			</div>
		</div>
		<?php
	}

	private static function fail( TK_Api_Error $e ) {
		wp_send_json_error( array( 'message' => $e->getMessage(), 'code' => $e->api_code, 'details' => $e->details ), $e->status >= 400 && $e->status < 600 ? $e->status : 502 );
	}

	public static function ajax_presign() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SOURCES, 'tk_upload' );
		$filename = isset( $_POST['filename'] ) ? sanitize_file_name( wp_unslash( $_POST['filename'] ) ) : '';
		$size     = isset( $_POST['size'] ) ? absint( $_POST['size'] ) : 0;
		$sha      = isset( $_POST['sha256'] ) ? strtolower( sanitize_text_field( wp_unslash( $_POST['sha256'] ) ) ) : '';
		if ( ! $filename || ! $size || ! preg_match( '/^[0-9a-f]{64}$/', $sha ) || ! preg_match( '/\.pdf$/i', $filename ) ) {
			wp_send_json_error( array( 'message' => __( 'קובץ לא תקין (נדרש PDF).', 'trial-knowledge' ) ), 400 );
		}
		try {
			$res = tk_api()->post( '/v2/admin/uploads/presign', array( 'filename' => $filename, 'mime_type' => 'application/pdf', 'size_bytes' => $size, 'sha256' => $sha ), true );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		wp_send_json_success( $res );
	}

	public static function ajax_create_job() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SOURCES, 'tk_upload' );
		$upload_id = isset( $_POST['upload_id'] ) ? sanitize_text_field( wp_unslash( $_POST['upload_id'] ) ) : '';
		$title     = isset( $_POST['title'] ) ? sanitize_text_field( wp_unslash( $_POST['title'] ) ) : '';
		$date      = isset( $_POST['hearing_date'] ) ? sanitize_text_field( wp_unslash( $_POST['hearing_date'] ) ) : '';
		$crs       = isset( $_POST['crs'] ) ? sanitize_key( wp_unslash( $_POST['crs'] ) ) : 'unknown';
		if ( ! preg_match( '/^[0-9a-f-]{36}$/', $upload_id ) ) {
			wp_send_json_error( array( 'message' => 'invalid upload id' ), 400 );
		}
		$doc = array( 'title' => $title ? $title : __( 'פרוטוקול', 'trial-knowledge' ), 'court_record_status' => in_array( $crs, array( 'filed', 'unknown', 'external' ), true ) ? $crs : 'unknown' );
		if ( preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date ) ) {
			$doc['hearing_date'] = $date;
		}
		try {
			$res = tk_api()->post( '/v2/admin/ingestion-jobs', array( 'upload_id' => $upload_id, 'document' => $doc ), true );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		wp_send_json_success( $res );
	}

	public static function ajax_jobs() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SOURCES, 'tk_jobs' );
		try {
			$res = tk_api()->get( '/v2/admin/ingestion-jobs?limit=50', true );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		wp_send_json_success( $res );
	}

	public static function ajax_job() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SOURCES, 'tk_jobs' );
		$id = isset( $_POST['job_id'] ) ? sanitize_text_field( wp_unslash( $_POST['job_id'] ) ) : '';
		if ( ! preg_match( '/^[0-9a-f-]{36}$/', $id ) ) {
			wp_send_json_error( array( 'message' => 'invalid job id' ), 400 );
		}
		try {
			$res = tk_api()->get( '/v2/admin/ingestion-jobs/' . $id, true );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		wp_send_json_success( $res );
	}

	public static function ajax_retry() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SOURCES, 'tk_jobs' );
		$id = isset( $_POST['job_id'] ) ? sanitize_text_field( wp_unslash( $_POST['job_id'] ) ) : '';
		if ( ! preg_match( '/^[0-9a-f-]{36}$/', $id ) ) {
			wp_send_json_error( array( 'message' => 'invalid job id' ), 400 );
		}
		try {
			$res = tk_api()->post( '/v2/admin/ingestion-jobs/' . $id . '/retry', new stdClass(), true );
		} catch ( TK_Api_Error $e ) {
			self::fail( $e );
		}
		wp_send_json_success( $res );
	}
}
