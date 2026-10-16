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

	/** 2.7.13: what a document can be. "auto" = protocol unless it has no speakers and no attendance list. */
	const KINDS = array(
		'auto'      => 'זיהוי אוטומטי',
		'protocol'  => 'פרוטוקול דיון',
		'decision'  => 'החלטה של בית המשפט',
		'motion'    => 'בקשה / עתירה',
		'response'  => 'תגובה',
		'notice'    => 'הודעה',
		'affidavit' => 'תצהיר',
		'exhibit'   => 'מוצג',
		'other'     => 'אחר (מכתב, בקשת חנינה וכו׳)',
	);

	/** The API's kind for a choice in the form, and whether it is left to the system. Pure, for tests. */
	public static function kind_fields( $kind ) {
		$kind = (string) $kind;
		if ( ! isset( self::KINDS[ $kind ] ) || 'auto' === $kind ) {
			return array( 'source_type' => 'protocol', 'auto_kind' => true );
		}
		return array( 'source_type' => $kind );
	}

	public static function init() {
		add_action( 'wp_ajax_tk_presign', array( __CLASS__, 'ajax_presign' ) );
		add_action( 'wp_ajax_tk_create_job', array( __CLASS__, 'ajax_create_job' ) );
		add_action( 'wp_ajax_tk_jobs', array( __CLASS__, 'ajax_jobs' ) );
		add_action( 'wp_ajax_tk_job', array( __CLASS__, 'ajax_job' ) );
		add_action( 'wp_ajax_tk_retry_job', array( __CLASS__, 'ajax_retry' ) );
		add_action( 'admin_post_tk_source_action', array( __CLASS__, 'source_action' ) );
		add_action( 'admin_post_tk_build_digests', array( __CLASS__, 'build_digests' ) );
	}

	/** 2.7.14: published hearings that have no digest yet (digests are built on request), latest first. @param array $hearings /v2/hearings items. */
	public static function hearings_without_digest( array $hearings, $max = 12 ) {
		$out = array();
		foreach ( $hearings as $h ) {
			if ( empty( $h['has_digest'] ) && ! empty( $h['id'] ) ) {
				$out[] = $h;
			}
		}
		usort( $out, function ( $a, $b ) {
			return strcmp( (string) ( $b['hearing_date'] ?? '' ), (string) ( $a['hearing_date'] ?? '' ) );
		} );
		return array_slice( $out, 0, $max );
	}

	public static function render_digests( array $hearings ) {
		$out = '<div class="tk-card" id="tk-digests"><h2>' . esc_html__( 'דיונים בלי סיכום', 'trial-knowledge' ) . '</h2>';
		$out .= '<p class="description">' . esc_html__( 'סיכום דיון נבנה במודל (כמה סנטים לדיון ארוך) ומתפרסם רק אם עבר את הבדיקות. מסמנים ובונים.', 'trial-knowledge' ) . '</p>';
		if ( ! $hearings ) {
			return $out . '<p>' . esc_html__( 'לכל הדיונים שפורסמו יש סיכום.', 'trial-knowledge' ) . '</p></div>';
		}
		$out .= '<form method="post" action="' . esc_url( admin_url( 'admin-post.php' ) ) . '">' . wp_nonce_field( 'tk_build_digests', '_wpnonce', true, false ) .
			'<input type="hidden" name="action" value="tk_build_digests"><ul>';
		foreach ( $hearings as $h ) {
			$out .= '<li><label><input type="checkbox" name="hearings[]" value="' . esc_attr( (string) $h['id'] ) . '"> ' .
				esc_html( (string) ( $h['hearing_date'] ?? '' ) . ' · ' . implode( ', ', (array) ( $h['witnesses'] ?? array() ) ) ) . '</label></li>';
		}
		return $out . '</ul><p><button class="button">' . esc_html__( 'בניית סיכום לדיונים המסומנים', 'trial-knowledge' ) . '</button></p></form></div>';
	}

	public static function build_digests() {
		if ( ! current_user_can( TK_Permissions::CAP_SOURCES ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ), 403 );
		}
		check_admin_referer( 'tk_build_digests' );
		$ids  = array_values( array_filter( array_map( 'sanitize_text_field', (array) wp_unslash( $_POST['hearings'] ?? array() ) ), function ( $i ) {
			return (bool) preg_match( '/^hr_[0-9a-f]{26}$/', $i );
		} ) );
		$back = admin_url( 'admin.php?page=trial-knowledge-sources' );
		if ( ! $ids ) {
			wp_safe_redirect( add_query_arg( 'tk_msg', rawurlencode( __( 'לא סומנו דיונים.', 'trial-knowledge' ) ), $back ) );
			exit;
		}
		try {
			tk_api()->post( '/v2/admin/digests/build', array( 'hearing_ids' => $ids, 'limit' => count( $ids ) ), true );
			$msg = sprintf( 'נשלחה בניית סיכום ל־%d דיונים. הסיכום יופיע אחרי שיעבור את הבדיקות.', count( $ids ) );
		} catch ( TK_Api_Error $e ) {
			$msg = $e->getMessage();
		}
		wp_safe_redirect( add_query_arg( 'tk_msg', rawurlencode( $msg ), $back ) );
		exit;
	}

	const OWNERS = array( 'הרשות השופטת', 'באי כוח נאשם 1 (נתניהו)', 'באי כוח נאשמים 2–3 (אלוביץ\')', 'באי כוח נאשם 4 (מוזס)', 'המאשימה (הפרקליטות)', 'צד שלישי / תקשורת' );

	/**
	 * 2.7.13: the latest uploads whose source was not published, with what they look like and what to do with them.
	 * An upload is published only by an action here (or by the inbox's policy).
	 */
	public static function pending_sources() {
		// 2.7.15: one call (it was a preview request per job — up to a hundred — and the screen froze for half a minute)
		$out = array();
		foreach ( (array) ( tk_api()->get( '/v2/admin/sources/pending?limit=15&n=4', true )['items'] ?? array() ) as $pv ) {
			$out[] = (array) $pv;
		}
		return $out;
	}

	/** @param array $items pending_sources(). @param array|null $fix a published source being re-typed. */
	public static function render_pending( array $items, $fix = null ) {
		$out = '<div class="tk-card" id="tk-pending"><h2>' . esc_html__( 'מסמכים שהועלו ולא פורסמו', 'trial-knowledge' ) . '</h2>';
		$out .= '<p class="description">' . esc_html__( 'מסמך שהועלה מכאן נקלט (טקסט, חיפוש, ציטוטים) אבל לא מופיע באתר ולא בתשובות עד שמפרסמים אותו. כאן רואים מה הוא, מתקנים את הסוג אם צריך, ומפרסמים או מסירים.', 'trial-knowledge' ) . '</p>';
		if ( ! $items ) {
			$out .= '<p>' . esc_html__( 'אין מסמכים שמחכים.', 'trial-knowledge' ) . '</p>';
		}
		foreach ( $items as $it ) {
			$out .= self::source_form( $it, true );
		}
		$out .= '<h3>' . esc_html__( 'תיקון סוג של מסמך שכבר פורסם', 'trial-knowledge' ) . '</h3>' .
			'<form method="get" action="' . esc_url( admin_url( 'admin.php' ) ) . '"><input type="hidden" name="page" value="trial-knowledge-sources">' .
			'<label for="tk-fix-sv">' . esc_html__( 'מזהה המקור (sv_… מכתובת עמוד המסמך)', 'trial-knowledge' ) . '</label> ' .
			'<input type="text" id="tk-fix-sv" name="tk_sv" pattern="sv_[0-9a-f]{26}" size="34"> <button class="button">' . esc_html__( 'הצגה', 'trial-knowledge' ) . '</button></form>';
		if ( $fix ) {
			// 2.7.14: an unpublished source opened by its id gets the full actions (publish / withdraw)
			$out .= self::source_form( $fix, 'published' !== ( $fix['publication_state'] ?? '' ) );
		}
		return $out . '</div>';
	}

	private static function source_form( array $it, $pending ) {
		$sv    = (string) ( $it['id'] ?? '' );
		$kinds = array_diff_key( self::KINDS, array( 'auto' => 1 ) );
		$out   = '<div class="postbox" style="padding:10px 14px;margin-block:12px"><h3 style="margin:0 0 .3em">' . esc_html( (string) ( $it['title'] ?? $it['job_title'] ?? $sv ) ) . '</h3>';
		$out  .= '<p class="description">' . esc_html(
			sprintf(
				'%1$s · %2$s · %3$s עמודים · %4$s קטעים · %5$s%6$s',
				$kinds[ $it['source_type'] ?? '' ] ?? (string) ( $it['source_type'] ?? '' ),
				(string) ( $it['source_owner'] ?? '' ),
				(string) ( $it['page_count'] ?? '?' ),
				(string) ( $it['unit_count'] ?? '?' ),
				! empty( $it['hearing_id'] ) ? 'נקלט כדיון מיום ' . (string) ( $it['hearing_date'] ?? '' ) : 'מסמך',
				' · ' . $sv
			)
		) . '</p>';
		foreach ( (array) ( $it['same_file'] ?? array() ) as $o ) {
			$out .= '<p class="notice notice-warning inline" style="padding:6px 10px">' . esc_html( sprintf( 'אותו קובץ בדיוק כבר במאגר: "%1$s" (%2$s, %3$s). כנראה כפילות — אפשר להסיר את זה.', (string) ( $o['title'] ?? '' ), (string) ( $o['source_type'] ?? '' ), 'published' === ( $o['publication_state'] ?? '' ) ? 'מפורסם' : 'לא מפורסם' ) ) . '</p>';
		}
		$out .= '<details><summary>' . esc_html__( 'תחילת המסמך', 'trial-knowledge' ) . '</summary>';
		foreach ( (array) ( $it['units'] ?? array() ) as $u ) {
			$out .= '<p><span class="description">' . esc_html( 'עמ׳ ' . (string) ( $u['page'] ?? '' ) . ( ! empty( $u['speaker'] ) ? ' · ' . (string) $u['speaker'] : '' ) ) . '</span><br>' . esc_html( (string) ( $u['text'] ?? '' ) ) . '</p>';
		}
		$out .= '</details><form method="post" action="' . esc_url( admin_url( 'admin-post.php' ) ) . '">' . wp_nonce_field( 'tk_source_' . $sv, '_wpnonce', true, false ) .
			'<input type="hidden" name="action" value="tk_source_action"><input type="hidden" name="sv" value="' . esc_attr( $sv ) . '">' .
			'<p><label>' . esc_html__( 'סוג', 'trial-knowledge' ) . ' <select name="kind">';
		$cur = (string) ( $it['source_type'] ?? '' );
		foreach ( array_merge( array( 'protocol' => 'פרוטוקול דיון' ), $kinds ) as $k => $label ) {
			$out .= '<option value="' . esc_attr( $k ) . '"' . ( $k === $cur ? ' selected' : '' ) . '>' . esc_html( $label ) . '</option>';
		}
		$out .= '</select></label> <label>' . esc_html__( 'כותרת', 'trial-knowledge' ) . ' <input type="text" name="title" size="40" value="' . esc_attr( (string) ( $it['title'] ?? '' ) ) . '"></label> ' .
			'<label>' . esc_html__( 'מי הגיש', 'trial-knowledge' ) . ' <select name="owner"><option value="">' . esc_html__( '(ללא שינוי)', 'trial-knowledge' ) . '</option>';
		foreach ( self::OWNERS as $o ) {
			$out .= '<option value="' . esc_attr( $o ) . '"' . ( $o === ( $it['source_owner'] ?? '' ) ? ' selected' : '' ) . '>' . esc_html( $o ) . '</option>';
		}
		$out .= '</select></label></p><p>';
		if ( $pending ) {
			$out .= '<button class="button button-primary" name="do" value="publish">' . esc_html__( 'שמירה ופרסום', 'trial-knowledge' ) . '</button> ' .
				'<button class="button" name="do" value="save">' . esc_html__( 'שמירה בלי לפרסם', 'trial-knowledge' ) . '</button> ' .
				'<button class="button" name="do" value="withdraw">' . esc_html__( 'הסרה (כפילות / לא שייך)', 'trial-knowledge' ) . '</button>';
		} else {
			$out .= '<button class="button button-primary" name="do" value="save">' . esc_html__( 'שמירת הסוג', 'trial-knowledge' ) . '</button>';
		}
		return $out . '</p></form></div>';
	}

	/** What a form press asks the API for: [method path, body]. Pure, for tests. */
	public static function action_calls( $do, $sv, $kind, $title, $owner, $current_kind, $has_hearing ) {
		$path  = '/v2/admin/sources/' . $sv;
		$calls = array();
		if ( 'withdraw' === $do ) {
			return array( array( $path . '/withdraw', array( 'reason' => 'הוסר במסך מקורות וקליטה (כפילות או לא שייך)' ) ) );
		}
		$retype = 'protocol' !== $kind && ( $kind !== $current_kind || $has_hearing || '' !== $title || '' !== $owner );
		if ( $retype ) {
			$body = array( 'kind' => $kind, 'publish' => 'publish' === $do );
			if ( '' !== $title ) {
				$body['title'] = $title;
			}
			if ( '' !== $owner ) {
				$body['source_owner'] = $owner;
			}
			$calls[] = array( $path . '/classify', $body );
		} elseif ( 'publish' === $do ) {
			$calls[] = array( $path . '/publish', new stdClass() );
		}
		return $calls;
	}

	public static function source_action() {
		if ( ! current_user_can( TK_Permissions::CAP_SOURCES ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ), 403 );
		}
		$sv = isset( $_POST['sv'] ) ? sanitize_text_field( wp_unslash( $_POST['sv'] ) ) : '';
		check_admin_referer( 'tk_source_' . $sv );
		$do    = isset( $_POST['do'] ) ? sanitize_key( wp_unslash( $_POST['do'] ) ) : '';
		$kind  = isset( $_POST['kind'] ) ? sanitize_key( wp_unslash( $_POST['kind'] ) ) : '';
		$title = isset( $_POST['title'] ) ? sanitize_text_field( wp_unslash( $_POST['title'] ) ) : '';
		$owner = isset( $_POST['owner'] ) ? sanitize_text_field( wp_unslash( $_POST['owner'] ) ) : '';
		$back  = admin_url( 'admin.php?page=trial-knowledge-sources' );
		if ( ! preg_match( '/^sv_[0-9a-f]{26}$/', $sv ) || ! in_array( $do, array( 'publish', 'save', 'withdraw' ), true ) || ( 'protocol' !== $kind && ! isset( self::KINDS[ $kind ] ) ) ) {
			wp_safe_redirect( add_query_arg( 'tk_msg', rawurlencode( __( 'בקשה לא תקינה.', 'trial-knowledge' ) ), $back ) );
			exit;
		}
		try {
			$pv    = (array) tk_api()->get( '/v2/admin/sources/' . $sv . '/preview?n=1', true );
			$title = $title === (string) ( $pv['title'] ?? '' ) ? '' : $title;
			$owner = $owner === (string) ( $pv['source_owner'] ?? '' ) ? '' : $owner;
			foreach ( self::action_calls( $do, $sv, $kind, $title, $owner, (string) ( $pv['source_type'] ?? '' ), ! empty( $pv['hearing_id'] ) ) as $c ) {
				tk_api()->post( $c[0], $c[1], true );
			}
			$msg = 'withdraw' === $do ? __( 'המסמך הוסר.', 'trial-knowledge' ) : ( 'publish' === $do ? __( 'המסמך פורסם. הוא יופיע באתר ובתשובות.', 'trial-knowledge' ) : __( 'נשמר.', 'trial-knowledge' ) );
		} catch ( TK_Api_Error $e ) {
			$msg = $e->getMessage();
		}
		wp_safe_redirect( add_query_arg( 'tk_msg', rawurlencode( $msg ), $back ) );
		exit;
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
				<h2><?php esc_html_e( 'העלאת מסמכים (PDF)', 'trial-knowledge' ); ?></h2>
				<p><label for="tk-files"><?php esc_html_e( 'קבצים', 'trial-knowledge' ); ?></label>
					<input type="file" id="tk-files" accept="application/pdf" multiple required></p>
				<p><label for="tk-kind"><?php esc_html_e( 'סוג המסמך', 'trial-knowledge' ); ?></label>
					<select id="tk-kind">
						<?php foreach ( self::KINDS as $tk_k => $tk_label ) : ?>
							<option value="<?php echo esc_attr( $tk_k ); ?>"><?php echo esc_html( $tk_label ); ?></option>
						<?php endforeach; ?>
					</select>
					<span class="description"><?php esc_html_e( 'בזיהוי אוטומטי: מסמך בלי רשימת נוכחים ובלי דוברים לא ייחשב לפרוטוקול דיון.', 'trial-knowledge' ); ?></span></p>
				<p><label for="tk-date"><?php esc_html_e( 'תאריך הדיון (אם ידוע; אחרת יזוהה מהפרוטוקול)', 'trial-knowledge' ); ?></label>
					<input type="date" id="tk-date"></p>
				<p><label for="tk-crs"><?php esc_html_e( 'מעמד בתיק', 'trial-knowledge' ); ?></label>
					<select id="tk-crs">
						<option value="filed"><?php esc_html_e( 'מסמך רשמי מתיק בית המשפט', 'trial-knowledge' ); ?></option>
						<option value="unknown"><?php esc_html_e( 'לא ידוע', 'trial-knowledge' ); ?></option>
						<option value="external"><?php esc_html_e( 'מקור חיצוני', 'trial-knowledge' ); ?></option>
					</select></p>
				<p><button type="submit" class="button button-primary"><?php esc_html_e( 'העלאה ויצירת משימות קליטה', 'trial-knowledge' ); ?></button></p>
				<ol id="tk-upload-log" class="tk-log" aria-live="polite"></ol>
			</form>
			<?php
			if ( isset( $_GET['tk_msg'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification.Recommended
				echo '<div class="notice notice-info is-dismissible"><p>' . esc_html( sanitize_text_field( wp_unslash( $_GET['tk_msg'] ) ) ) . '</p></div>'; // phpcs:ignore WordPress.Security.NonceVerification.Recommended
			}
			if ( tk_api()->admin_configured() ) {
				$tk_fix = null;
				$tk_sv  = isset( $_GET['tk_sv'] ) ? sanitize_text_field( wp_unslash( $_GET['tk_sv'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Recommended
				try {
					if ( preg_match( '/^sv_[0-9a-f]{26}$/', $tk_sv ) ) {
						$tk_fix = (array) tk_api()->get( '/v2/admin/sources/' . $tk_sv . '/preview?n=4', true );
					}
					echo self::render_pending( self::pending_sources(), $tk_fix ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render_pending()
					echo self::render_digests( self::hearings_without_digest( (array) ( tk_api()->get( '/v2/hearings' )['items'] ?? array() ) ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in render_digests()
				} catch ( TK_Api_Error $e ) {
					echo '<div class="notice notice-error"><p>' . esc_html( $e->getMessage() ) . '</p></div>';
				}
			}
			?>
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
		$kind = isset( $_POST['kind'] ) ? sanitize_key( wp_unslash( $_POST['kind'] ) ) : 'auto';
		$doc  = array_merge(
			array( 'title' => $title ? $title : __( 'מסמך', 'trial-knowledge' ), 'court_record_status' => in_array( $crs, array( 'filed', 'unknown', 'external' ), true ) ? $crs : 'unknown' ),
			self::kind_fields( $kind )
		);
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
