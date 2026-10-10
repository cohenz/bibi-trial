<?php
/**
 * Settings screen and connection test.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Admin_Settings {

	public static function init() {
		add_action( 'admin_menu', array( __CLASS__, 'menu' ) );
		add_action( 'admin_post_tk_save_settings', array( __CLASS__, 'save' ) );
		add_action( 'wp_ajax_tk_test_connection', array( __CLASS__, 'test_connection' ) );
		add_action( 'admin_enqueue_scripts', array( __CLASS__, 'assets' ) );
	}

	public static function menu() {
		add_menu_page( __( 'מאגר המשפט', 'trial-knowledge' ), __( 'מאגר המשפט', 'trial-knowledge' ), TK_Permissions::CAP_REVIEW, 'trial-knowledge', array( 'TK_Admin_Review', 'page' ), 'dashicons-book-alt', 58 );
		add_submenu_page( 'trial-knowledge', __( 'ביקורת ופרסום', 'trial-knowledge' ), __( 'ביקורת ופרסום', 'trial-knowledge' ), TK_Permissions::CAP_REVIEW, 'trial-knowledge', array( 'TK_Admin_Review', 'page' ) );
		add_submenu_page( 'trial-knowledge', __( 'מקורות וקליטה', 'trial-knowledge' ), __( 'מקורות וקליטה', 'trial-knowledge' ), TK_Permissions::CAP_SOURCES, 'trial-knowledge-sources', array( 'TK_Admin_Sources', 'page' ) );
		add_submenu_page( 'trial-knowledge', __( 'הגדרות', 'trial-knowledge' ), __( 'הגדרות', 'trial-knowledge' ), TK_Permissions::CAP_SETTINGS, 'trial-knowledge-settings', array( __CLASS__, 'page' ) );
	}

	public static function assets( $hook ) {
		if ( false === strpos( (string) $hook, 'trial-knowledge' ) ) {
			return;
		}
		wp_enqueue_style( 'trial-knowledge-admin', TK_URL . 'assets/admin.css', array(), TK_VERSION );
		wp_enqueue_script( 'trial-knowledge-admin', TK_URL . 'assets/admin.js', array(), TK_VERSION, true );
		wp_localize_script(
			'trial-knowledge-admin',
			'TKAdmin',
			array(
				'ajax'   => admin_url( 'admin-ajax.php' ),
				'nonces' => array(
					'test'    => wp_create_nonce( 'tk_test_connection' ),
					'upload'  => wp_create_nonce( 'tk_upload' ),
					'jobs'    => wp_create_nonce( 'tk_jobs' ),
					'review'  => wp_create_nonce( 'tk_review' ),
					'publish' => wp_create_nonce( 'tk_publish' ),
				),
				'i18n'   => array(
					'hashing'   => __( 'מחשב טביעת אצבע (SHA-256)…', 'trial-knowledge' ),
					'uploading' => __( 'מעלה ישירות לאחסון…', 'trial-knowledge' ),
					'creating'  => __( 'יוצר משימת קליטה…', 'trial-knowledge' ),
					'failed'    => __( 'נכשל', 'trial-knowledge' ),
					'done'      => __( 'הושלם', 'trial-knowledge' ),
					'exists'    => __( 'הקובץ כבר קיים באחסון; לא הועלה שוב.', 'trial-knowledge' ),
					'confirm'   => __( 'לבצע את הפעולה?', 'trial-knowledge' ),
				),
			)
		);
	}

	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_SETTINGS ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		$cfg = TK_Settings_Store::get();
		?>
		<div class="wrap tk-admin" dir="rtl">
			<h1><?php esc_html_e( 'הגדרות מאגר המשפט', 'trial-knowledge' ); ?></h1>
			<?php if ( isset( $_GET['saved'] ) ) : // phpcs:ignore WordPress.Security.NonceVerification.Recommended ?>
				<div class="notice notice-success"><p><?php esc_html_e( 'ההגדרות נשמרו.', 'trial-knowledge' ); ?></p></div>
			<?php endif; ?>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
				<input type="hidden" name="action" value="tk_save_settings">
				<?php wp_nonce_field( 'tk_save_settings' ); ?>
				<table class="form-table" role="presentation">
					<tr><th scope="row"><label for="tk_api_base"><?php esc_html_e( 'כתובת ה־Knowledge API', 'trial-knowledge' ); ?></label></th>
						<td><input type="url" id="tk_api_base" name="api_base" class="regular-text code" dir="ltr" value="<?php echo esc_attr( $cfg['api_base'] ); ?>" placeholder="https://api.example.org"></td></tr>
					<tr><th scope="row"><label for="tk_key_id"><?php esc_html_e( 'מזהה מפתח שירות (Key ID)', 'trial-knowledge' ); ?></label></th>
						<td><input type="text" id="tk_key_id" name="key_id" class="regular-text code" dir="ltr" value="<?php echo esc_attr( $cfg['key_id'] ); ?>" autocomplete="off"></td></tr>
					<tr><th scope="row"><label for="tk_secret"><?php esc_html_e( 'סוד מפתח השירות', 'trial-knowledge' ); ?></label></th>
						<td>
						<?php if ( TK_Settings_Store::secret_from_constant() ) : ?>
							<p><?php esc_html_e( 'הסוד מוגדר ב־wp-config.php (TK_API_SECRET).', 'trial-knowledge' ); ?></p>
						<?php else : ?>
							<input type="password" id="tk_secret" name="secret" class="regular-text code" dir="ltr" value="" autocomplete="new-password" placeholder="<?php echo $cfg['secret'] ? esc_attr__( '•••••• (שמור; השאירו ריק כדי לא לשנות)', 'trial-knowledge' ) : ''; ?>">
							<p class="description"><?php esc_html_e( 'מומלץ להגדיר TK_API_SECRET ב־wp-config.php. אם נשמר כאן, הוא מוצפן ואינו נשלח לדפדפן.', 'trial-knowledge' ); ?></p>
						<?php endif; ?>
						</td></tr>
					<tr><th scope="row"><label for="tk_webhook"><?php esc_html_e( 'סוד webhook לניקוי מטמון', 'trial-knowledge' ); ?></label></th>
						<td><input type="password" id="tk_webhook" name="webhook_secret" class="regular-text code" dir="ltr" value="" autocomplete="new-password" placeholder="<?php echo $cfg['webhook_secret'] ? '••••••' : ''; ?>">
						<p class="description"><?php echo esc_html( sprintf( __( 'כתובת ה־webhook להגדרה ב־API (WP_CALLBACK_URL): %s', 'trial-knowledge' ), rest_url( 'trial-knowledge/v1/webhook' ) ) ); ?></p></td></tr>
					<tr><th scope="row"><label for="tk_ttl"><?php esc_html_e( 'זמן מטמון (שניות)', 'trial-knowledge' ); ?></label></th>
						<td><input type="number" id="tk_ttl" name="cache_ttl" min="30" max="86400" value="<?php echo esc_attr( (string) $cfg['cache_ttl'] ); ?>"></td></tr>
					<tr><th scope="row"><label for="tk_slug"><?php esc_html_e( 'נתיב העמודים הציבוריים', 'trial-knowledge' ); ?></label></th>
						<td><input type="text" id="tk_slug" name="public_slug" dir="ltr" value="<?php echo esc_attr( $cfg['public_slug'] ); ?>"></td></tr>
					<tr><th scope="row"><label for="tk_disclosure"><?php esc_html_e( 'הצהרת עדשה (מוצגת בכל כרטיס טענה)', 'trial-knowledge' ); ?></label></th>
						<td><textarea id="tk_disclosure" name="disclosure" rows="3" class="large-text"><?php echo esc_textarea( $cfg['disclosure'] ); ?></textarea></td></tr>
				</table>
				<?php submit_button( __( 'שמירה', 'trial-knowledge' ) ); ?>
			</form>
			<h2><?php esc_html_e( 'בדיקת חיבור', 'trial-knowledge' ); ?></h2>
			<p><button type="button" class="button" id="tk-test-connection"><?php esc_html_e( 'בדיקת חיבור ל־API', 'trial-knowledge' ); ?></button></p>
			<pre id="tk-test-result" class="tk-pre" aria-live="polite"></pre>
		</div>
		<?php
	}

	public static function save() {
		if ( ! current_user_can( TK_Permissions::CAP_SETTINGS ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ), 403 );
		}
		check_admin_referer( 'tk_save_settings' );
		$base = isset( $_POST['api_base'] ) ? esc_url_raw( wp_unslash( $_POST['api_base'] ) ) : '';
		if ( $base && 0 !== strpos( $base, 'https://' ) && ! preg_match( '#^http://(localhost|127\.0\.0\.1)#', $base ) ) {
			$base = ''; // HTTPS required outside local development.
		}
		TK_Settings_Store::save(
			array(
				'api_base'       => untrailingslashit( $base ),
				'key_id'         => isset( $_POST['key_id'] ) ? sanitize_text_field( wp_unslash( $_POST['key_id'] ) ) : '',
				'secret'         => isset( $_POST['secret'] ) ? trim( (string) wp_unslash( $_POST['secret'] ) ) : '', // phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized -- secret, stored encrypted
				'webhook_secret' => isset( $_POST['webhook_secret'] ) ? trim( (string) wp_unslash( $_POST['webhook_secret'] ) ) : '', // phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized
				'cache_ttl'      => isset( $_POST['cache_ttl'] ) ? max( 30, min( 86400, absint( $_POST['cache_ttl'] ) ) ) : 300,
				'public_slug'    => isset( $_POST['public_slug'] ) ? sanitize_title( wp_unslash( $_POST['public_slug'] ) ) : 'trial',
				'disclosure'     => isset( $_POST['disclosure'] ) ? sanitize_textarea_field( wp_unslash( $_POST['disclosure'] ) ) : '',
			)
		);
		TK_Cache::purge_all();
		flush_rewrite_rules();
		wp_safe_redirect( admin_url( 'admin.php?page=trial-knowledge-settings&saved=1' ) );
		exit;
	}

	public static function test_connection() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SETTINGS, 'tk_test_connection' );
		$client = new TK_Api_Client( TK_Settings_Store::get() );
		$out    = array();
		try {
			$out['ready'] = $client->get( '/v2/ready' );
		} catch ( TK_Api_Error $e ) {
			$out['ready'] = array( 'error' => $e->getMessage() );
		}
		try {
			$out['whoami'] = $client->get( '/v2/admin/whoami', true );
		} catch ( TK_Api_Error $e ) {
			$out['whoami'] = array( 'error' => $e->api_code . ': ' . $e->getMessage() );
		}
		wp_send_json_success( $out );
	}
}
