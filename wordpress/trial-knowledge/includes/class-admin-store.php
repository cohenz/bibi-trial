<?php
/**
 * Admin screen "עותק מקומי" (2.5): the local copy of the published content that readers are
 * served from — size, stale rows, last changes sync, full sync progress, and actions.
 * Readers never see any of this.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Admin_Store {

	const NONCE = 'tk_store';

	const KIND_LABELS = array(
		'guide'          => 'עמוד הבית (guide)',
		'case'           => 'מדריכי תיקים',
		'witness'        => 'עמודי עדים',
		'guide_timeline' => 'ציר הזמן הכפול',
		'glossary'       => 'מילון',
		'hearing'        => 'דיונים',
		'transcript'     => 'פרוטוקולים (חלונות של 25 עמ׳)',
		'document'       => 'מסמכים (חלונות של 25 עמ׳)',
		'list'           => 'רשימות מסמכים',
		'claim'          => 'כרטיסי טענה',
		'answer'         => 'תשובות',
		'citation'       => 'ציטוטים',
		'timeline'       => 'ציר דיונים',
		'other'          => 'אחר',
	);

	public static function init() {
		add_action( 'wp_ajax_tk_store_status', array( __CLASS__, 'ajax_status' ) );
		add_action( 'wp_ajax_tk_store_changes', array( __CLASS__, 'ajax_changes' ) );
		add_action( 'wp_ajax_tk_store_full', array( __CLASS__, 'ajax_full' ) );
		add_action( 'wp_ajax_tk_store_clear', array( __CLASS__, 'ajax_clear' ) );
	}

	private static function when( $ts ) {
		$ts = (int) $ts;
		if ( ! $ts ) {
			return '—';
		}
		return function_exists( 'wp_date' ) ? wp_date( 'd.m.Y H:i', $ts ) : gmdate( 'd.m.Y H:i', $ts );
	}

	private static function size( $bytes ) {
		return function_exists( 'size_format' ) ? (string) size_format( (int) $bytes, 1 ) : number_format( $bytes / 1048576, 1 ) . ' MB';
	}

	/** Everything the screen shows, as display strings (also the polling response). */
	public static function status() {
		$s       = TK_Store::stats();
		$full    = TK_Sync::full_status();
		$changes = get_option( TK_Sync::OPT_CHANGES, array() );
		$refresh = get_option( TK_Sync::OPT_REFRESH, array() );
		$changes = is_array( $changes ) ? $changes : array();
		$refresh = is_array( $refresh ) ? $refresh : array();

		if ( empty( $changes['time'] ) ) {
			$ch = __( 'טרם רץ', 'trial-knowledge' );
		} elseif ( empty( $changes['ok'] ) ) {
			$ch = sprintf( __( '%1$s — נכשל: %2$s', 'trial-knowledge' ), self::when( $changes['time'] ), (string) ( $changes['error'] ?? '' ) );
		} else {
			$c  = (array) ( $changes['counts'] ?? array() );
			$ch = sprintf(
				__( '%1$s — הצליח: %2$d דיונים, %3$d מסמכים, %4$d מדריכים, %5$d טענות השתנו%6$s; %7$d עותקים סומנו לרענון', 'trial-knowledge' ),
				self::when( $changes['time'] ),
				(int) ( $c['hearings'] ?? 0 ),
				(int) ( $c['documents'] ?? 0 ),
				(int) ( $c['guides'] ?? 0 ),
				(int) ( $c['claims'] ?? 0 ),
				! empty( $changes['lists_changed'] ) ? __( ', הרשימות השתנו', 'trial-knowledge' ) : '',
				(int) ( $changes['marked'] ?? 0 )
			);
		}

		$labels = array(
			'idle'      => __( 'טרם רץ', 'trial-knowledge' ),
			'running'   => __( 'בתהליך', 'trial-knowledge' ),
			'done'      => __( 'הושלם', 'trial-knowledge' ),
			'failed'    => __( 'נכשל', 'trial-knowledge' ),
			'cancelled' => __( 'בוטל', 'trial-knowledge' ),
		);
		$pct    = $full['total'] ? (int) floor( 100 * $full['position'] / $full['total'] ) : 0;
		$fl     = sprintf(
			__( '%1$s · התחיל %2$s · הסתיים %3$s · %4$d/%5$d (%6$d%%) · נטענו %7$d, קיימים %8$d, לא פורסמו %9$d, נכשלו %10$d, הוסרו %11$d', 'trial-knowledge' ),
			$labels[ $full['status'] ] ?? $full['status'],
			self::when( $full['started'] ),
			self::when( $full['finished'] ),
			(int) $full['position'],
			(int) $full['total'],
			$pct,
			(int) $full['fetched'],
			(int) $full['skipped'],
			(int) $full['missing'],
			(int) $full['failed'],
			(int) $full['pruned']
		);
		if ( $full['error'] ) {
			$fl .= ' · ' . sprintf( __( 'שגיאה אחרונה: %s', 'trial-knowledge' ), $full['error'] );
		}

		$rf = empty( $refresh['time'] ) ? __( 'טרם רץ', 'trial-knowledge' ) : sprintf(
			__( '%1$s — רועננו %2$d, הוסרו %3$d, נכשלו %4$d, ממתינים %5$d%6$s', 'trial-knowledge' ),
			self::when( $refresh['time'] ),
			(int) $refresh['fetched'],
			(int) $refresh['deleted'],
			(int) $refresh['failed'],
			(int) $refresh['remaining'],
			! empty( $refresh['down'] ) ? __( ' (ה־API אינו זמין; ניסיון חוזר בעוד 10 דקות)', 'trial-knowledge' ) : ''
		);

		$kinds = array();
		foreach ( $s['kinds'] as $k => $v ) {
			$kinds[] = array( 'label' => self::KIND_LABELS[ $k ] ?? $k, 'count' => number_format( $v['count'] ), 'size' => self::size( $v['bytes'] ) );
		}
		$next = wp_next_scheduled( TK_Sync::HOOK_CHANGES );
		return array(
			'count'        => number_format( $s['count'] ),
			'size'         => self::size( $s['bytes'] ),
			'stale'        => number_format( $s['stale'] ),
			'failed'       => number_format( $s['failed'] ),
			'kinds'        => $kinds,
			'changes'      => $ch,
			'since'        => (string) get_option( TK_Sync::OPT_SINCE, '' ),
			'next_changes' => $next ? self::when( $next ) : '—',
			'refresh'      => $rf,
			'full'         => $fl,
			'full_running' => 'running' === $full['status'],
			'busy'         => 'running' === $full['status'] || TK_Store::pending() > 0,
			'full_pct'     => $pct,
			'cron_off'     => defined( 'DISABLE_WP_CRON' ) && DISABLE_WP_CRON,
		);
	}

	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_SETTINGS ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		$st = self::status();
		?>
		<div class="wrap tk-admin" dir="rtl" id="tk-store">
			<h1><?php esc_html_e( 'עותק מקומי', 'trial-knowledge' ); ?></h1>
			<p class="description"><?php esc_html_e( 'ה־API מכין ומפרסם את התוכן; הקוראים מקבלים אותו מהעותק המקומי במסד הנתונים של האתר, גם כשה־API אינו זמין. עותק שסומן לרענון ממשיך להיות מוצג עד שהגרסה החדשה נטענת ברקע. שאלות (Ask), קובצי ה־PDF ומסכי הניהול ממשיכים לפנות ל־API ישירות.', 'trial-knowledge' ); ?></p>
			<?php if ( $st['cron_off'] ) : ?>
				<div class="notice notice-warning inline"><p><?php esc_html_e( 'DISABLE_WP_CRON מוגדר: ודאו שקיים cron של המערכת שמריץ את wp-cron.php, אחרת הסנכרון יתקדם רק כשמסך זה פתוח.', 'trial-knowledge' ); ?></p></div>
			<?php endif; ?>
			<div class="tk-card">
				<table class="widefat striped tk-store-table">
					<tbody>
						<tr><th scope="row"><?php esc_html_e( 'אובייקטים שמורים', 'trial-knowledge' ); ?></th><td data-tk="count"><?php echo esc_html( $st['count'] ); ?></td></tr>
						<tr><th scope="row"><?php esc_html_e( 'נפח כולל', 'trial-knowledge' ); ?></th><td data-tk="size"><?php echo esc_html( $st['size'] ); ?></td></tr>
						<tr><th scope="row"><?php esc_html_e( 'ממתינים לרענון', 'trial-knowledge' ); ?></th><td data-tk="stale"><?php echo esc_html( $st['stale'] ); ?></td></tr>
						<tr><th scope="row"><?php esc_html_e( 'רענון נכשל שוב ושוב (ינוסה בסנכרון המלא)', 'trial-knowledge' ); ?></th><td data-tk="failed"><?php echo esc_html( $st['failed'] ); ?></td></tr>
						<tr><th scope="row"><?php esc_html_e( 'סנכרון שינויים אחרון', 'trial-knowledge' ); ?></th><td data-tk="changes"><?php echo esc_html( $st['changes'] ); ?></td></tr>
						<tr><th scope="row"><?php esc_html_e( 'הסנכרון הבא (כל 15 דקות)', 'trial-knowledge' ); ?></th><td data-tk="next_changes"><?php echo esc_html( $st['next_changes'] ); ?></td></tr>
						<tr><th scope="row"><?php esc_html_e( 'רענון אחרון ברקע', 'trial-knowledge' ); ?></th><td data-tk="refresh"><?php echo esc_html( $st['refresh'] ); ?></td></tr>
						<tr><th scope="row"><?php esc_html_e( 'סנכרון מלא (יומי)', 'trial-knowledge' ); ?></th><td><span data-tk="full"><?php echo esc_html( $st['full'] ); ?></span>
							<progress max="100" value="<?php echo esc_attr( (string) $st['full_pct'] ); ?>" data-tk-progress <?php echo $st['full_running'] ? '' : 'hidden'; ?>></progress></td></tr>
					</tbody>
				</table>
			</div>
			<p class="tk-actions">
				<button type="button" class="button" data-tk-store="tk_store_changes"><?php esc_html_e( 'סנכרון שינויים עכשיו', 'trial-knowledge' ); ?></button>
				<button type="button" class="button button-primary" data-tk-store="tk_store_full"><?php esc_html_e( 'סנכרון מלא', 'trial-knowledge' ); ?></button>
				<button type="button" class="button button-link-delete" data-tk-store="tk_store_clear" data-tk-confirm="<?php esc_attr_e( 'לרוקן את העותק המקומי? עד שייטען מחדש, כל צפייה בעמוד תפנה ל־API.', 'trial-knowledge' ); ?>"><?php esc_html_e( 'ניקוי העותק', 'trial-knowledge' ); ?></button>
			</p>
			<p class="tk-muted" id="tk-store-msg" aria-live="polite"></p>
			<h2><?php esc_html_e( 'לפי סוג', 'trial-knowledge' ); ?></h2>
			<table class="widefat striped">
				<thead><tr><th><?php esc_html_e( 'סוג', 'trial-knowledge' ); ?></th><th><?php esc_html_e( 'מספר', 'trial-knowledge' ); ?></th><th><?php esc_html_e( 'נפח', 'trial-knowledge' ); ?></th></tr></thead>
				<tbody id="tk-store-kinds">
				<?php foreach ( $st['kinds'] as $k ) : ?>
					<tr><td><?php echo esc_html( $k['label'] ); ?></td><td><?php echo esc_html( $k['count'] ); ?></td><td><?php echo esc_html( $k['size'] ); ?></td></tr>
				<?php endforeach; ?>
				</tbody>
			</table>
		</div>
		<?php
	}

	/** Polling: returns the status; while a full sync runs, the open screen also advances it (works without WP-Cron). */
	public static function ajax_status() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SETTINGS, self::NONCE );
		if ( ! empty( $_POST['step'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification.Missing -- verified in require_ajax
			$full = TK_Sync::full_status();
			if ( 'running' === $full['status'] ) {
				TK_Sync::run_full_step( 10, 8 );
			} elseif ( TK_Store::pending() > 0 ) {
				TK_Sync::run_refresh( 10, 8 );
			}
		}
		wp_send_json_success( self::status() );
	}

	public static function ajax_changes() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SETTINGS, self::NONCE );
		$r = TK_Sync::run_changes();
		wp_send_json_success( array_merge( self::status(), array( 'message' => empty( $r['ok'] ) ? __( 'סנכרון השינויים נכשל.', 'trial-knowledge' ) : __( 'סנכרון השינויים הושלם; העותקים שסומנו יתרעננו ברקע.', 'trial-knowledge' ) ) ) );
	}

	public static function ajax_full() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SETTINGS, self::NONCE );
		$st = TK_Sync::start_full();
		wp_send_json_success( array_merge( self::status(), array( 'message' => 'running' === $st['status'] ? __( 'הסנכרון המלא נוסף לתור ורץ ברקע.', 'trial-knowledge' ) : __( 'לא ניתן להתחיל סנכרון מלא: ', 'trial-knowledge' ) . $st['error'] ) ) );
	}

	public static function ajax_clear() {
		TK_Permissions::require_ajax( TK_Permissions::CAP_SETTINGS, self::NONCE );
		TK_Sync::cancel_full();
		wp_clear_scheduled_hook( TK_Sync::HOOK_REFRESH );
		TK_Store::truncate();
		wp_send_json_success( array_merge( self::status(), array( 'message' => __( 'העותק המקומי רוקן.', 'trial-knowledge' ) ) ) );
	}
}
