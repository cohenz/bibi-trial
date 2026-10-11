<?php
/**
 * Duplicates in the intake: files uploaded more than once to inbox/.
 *
 * Exact copies (same bytes) are removed by the system when NTK_INBOX_DELETE_DUPLICATES is on. Near-identical copies
 * (same text, different file) are held before any processing; here the operator deletes the extra copy or marks it as
 * a different document. Works without JavaScript: each decision is a small form posted to admin-post.php.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Admin_Duplicates {

	const ACTION = 'tk_duplicate_decision';

	public static function init() {
		add_action( 'admin_post_' . self::ACTION, array( __CLASS__, 'decide' ) );
	}

	/** Public page for a kept source, when it is published. */
	public static function kept_link( array $kept ) {
		if ( empty( $kept['kind'] ) || 'source' !== $kept['kind'] || empty( $kept['publication_state'] ) || 'published' !== $kept['publication_state'] ) {
			return '';
		}
		if ( ! empty( $kept['hearing_id'] ) ) {
			return TK_Public_Pages::url( 'hearing', $kept['hearing_id'] );
		}
		return ! empty( $kept['source_version_id'] ) ? TK_Public_Pages::url( 'document', $kept['source_version_id'] ) : '';
	}

	public static function kept_html( $kept ) {
		if ( empty( $kept ) || ! is_array( $kept ) ) {
			return '<em>' . esc_html__( 'לא ידוע', 'trial-knowledge' ) . '</em>';
		}
		$bits = array();
		if ( 'source' === ( $kept['kind'] ?? '' ) ) {
			$title = $kept['title'] ?? ( $kept['source_version_id'] ?? '' );
			$link  = self::kept_link( $kept );
			$bits[] = $link ? '<a href="' . esc_url( $link ) . '" target="_blank" rel="noopener">' . esc_html( $title ) . '</a>' : '<strong>' . esc_html( $title ) . '</strong>';
			$meta = array_filter(
				array(
					! empty( $kept['source_type'] ) ? TK_Render::type_label( $kept['source_type'] ) : '',
					! empty( $kept['document_date'] ) ? $kept['document_date'] : '',
					! empty( $kept['page_count'] ) ? sprintf( /* translators: %d pages */ __( '%d עמ׳', 'trial-knowledge' ), (int) $kept['page_count'] ) : '',
					'published' === ( $kept['publication_state'] ?? '' ) ? __( 'מפורסם', 'trial-knowledge' ) : __( 'במערכת, לא מפורסם', 'trial-knowledge' ),
				)
			);
			$bits[] = '<span class="description">' . esc_html( implode( ' · ', $meta ) ) . '</span>';
			if ( ! empty( $kept['original_filename'] ) ) {
				$bits[] = '<code dir="ltr">' . esc_html( $kept['original_filename'] ) . '</code>';
			}
		} elseif ( 'inbox' === ( $kept['kind'] ?? '' ) ) {
			$bits[] = '<strong>' . esc_html( $kept['title'] ?? __( 'קובץ קודם בתיבת הקליטה', 'trial-knowledge' ) ) . '</strong>';
			$bits[] = '<code dir="ltr">' . esc_html( $kept['object_key'] ?? '' ) . '</code>';
			$bits[] = '<span class="description">' . esc_html( sprintf( /* translators: %s status */ __( 'סטטוס: %s', 'trial-knowledge' ), $kept['status'] ?? '' ) ) . '</span>';
		} else {
			$bits[] = esc_html( $kept['ref'] ?? '' );
		}
		return implode( '<br>', $bits );
	}

	private static function button( $item_id, $action, $label, $primary, $confirm ) {
		$out  = '<form method="post" action="' . esc_url( admin_url( 'admin-post.php' ) ) . '" style="display:inline-block;margin:2px">';
		$out .= '<input type="hidden" name="action" value="' . esc_attr( self::ACTION ) . '">';
		$out .= '<input type="hidden" name="item_id" value="' . esc_attr( $item_id ) . '">';
		$out .= '<input type="hidden" name="decision" value="' . esc_attr( $action ) . '">';
		$out .= wp_nonce_field( self::ACTION . '_' . $item_id, '_wpnonce', true, false );
		$out .= '<button type="submit" class="button' . ( $primary ? ' button-primary' : '' ) . '" onclick="return confirm(' . esc_attr( wp_json_encode( $confirm ) ) . ')">' . esc_html( $label ) . '</button>';
		return $out . '</form>';
	}

	public static function page() {
		if ( ! current_user_can( TK_Permissions::CAP_SOURCES ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ) );
		}
		$data  = null;
		$error = '';
		try {
			$data = tk_api()->get( '/v2/admin/inbox/duplicates?limit=300', true );
		} catch ( TK_Api_Error $e ) {
			$error = $e->getMessage();
		}
		// phpcs:disable WordPress.Security.NonceVerification.Recommended -- display-only notices after a redirect
		$notice = isset( $_GET['tk_msg'] ) ? sanitize_text_field( wp_unslash( $_GET['tk_msg'] ) ) : '';
		$ok     = isset( $_GET['tk_ok'] ) && '1' === $_GET['tk_ok'];
		// phpcs:enable
		?>
		<div class="wrap tk-admin" dir="rtl">
			<h1><?php esc_html_e( 'כפילויות בתיבת הקליטה', 'trial-knowledge' ); ?></h1>
			<?php if ( $notice ) : ?>
				<div class="notice <?php echo $ok ? 'notice-success' : 'notice-error'; ?>"><p><?php echo esc_html( $notice ); ?></p></div>
			<?php endif; ?>
			<?php if ( $error ) : ?>
				<div class="notice notice-error"><p><?php echo esc_html( $error ); ?></p></div>
			<?php endif; ?>
			<div class="tk-card">
				<p><?php esc_html_e( 'כל מסמך נשמר באחסון פעם אחת בלבד, לפי טביעת האצבע של התוכן (SHA-256). קובץ שהועלה שוב לתיבת הקליטה מזוהה לפני כל עיבוד:', 'trial-knowledge' ); ?></p>
				<ul style="list-style:disc;padding-right:1.5em">
					<li><?php esc_html_e( 'עותק זהה (אותו קובץ בדיוק): לא מעובד שוב. כשהמחיקה האוטומטית פעילה, העותק הנוסף נמחק מתיבת הקליטה, אחרי בדיקה שהעותק השמור קיים.', 'trial-knowledge' ); ?></li>
					<li><?php esc_html_e( 'כמעט זהה (אותו טקסט בקובץ אחר, למשל סריקה חוזרת או עותק עם חותמת): מוחזק בצד, לא נשמר ולא מעובד, עד שתחליטו כאן.', 'trial-knowledge' ); ?></li>
				</ul>
				<?php if ( is_array( $data ) ) : ?>
					<p><strong><?php esc_html_e( 'מחיקה אוטומטית של עותקים זהים:', 'trial-knowledge' ); ?></strong>
						<?php echo ! empty( $data['auto_delete'] ) ? esc_html__( 'פעילה', 'trial-knowledge' ) : esc_html__( 'כבויה (העותקים מסומנים ונשארים)', 'trial-knowledge' ); ?>
						· <?php echo esc_html( sprintf( /* translators: %d percent */ __( 'סף דמיון לכמעט־זהים: %d%%', 'trial-knowledge' ), (int) round( 100 * (float) ( $data['threshold'] ?? 0.9 ) ) ) ); ?>
					</p>
				<?php endif; ?>
			</div>
			<?php
			if ( is_array( $data ) ) {
				self::section(
					__( 'ממתינים להחלטה: כמעט זהים', 'trial-knowledge' ),
					$data['possible'] ?? array(),
					true,
					__( 'אין קבצים שממתינים להחלטה.', 'trial-knowledge' )
				);
				self::section(
					__( 'עותקים זהים שעדיין בתיבת הקליטה', 'trial-knowledge' ),
					$data['exact_not_removed'] ?? array(),
					false,
					__( 'אין.', 'trial-knowledge' )
				);
				self::removed( $data['removed'] ?? array() );
			}
			?>
		</div>
		<?php
	}

	private static function section( $title, array $items, $possible, $empty ) {
		echo '<div class="tk-card"><h2>' . esc_html( $title ) . ' <span class="count">(' . count( $items ) . ')</span></h2>';
		if ( ! $items ) {
			echo '<p>' . esc_html( $empty ) . '</p></div>';
			return;
		}
		echo '<table class="widefat striped"><thead><tr><th>' . esc_html__( 'הקובץ שהועלה שוב', 'trial-knowledge' ) . '</th><th>'
			. esc_html__( 'המסמך שכבר במערכת (יישאר)', 'trial-knowledge' ) . '</th><th>' . esc_html__( 'פעולה', 'trial-knowledge' ) . '</th></tr></thead><tbody>';
		foreach ( $items as $it ) {
			$id   = (string) ( $it['id'] ?? '' );
			$left = '<code dir="ltr">' . esc_html( $it['object_key'] ?? '' ) . '</code><br><span class="description">'
				. esc_html(
					implode(
						' · ',
						array_filter(
							array(
								$it['title'] ?? '',
								! empty( $it['page_count'] ) ? sprintf( /* translators: %d pages */ __( '%d עמ׳', 'trial-knowledge' ), (int) $it['page_count'] ) : '',
								isset( $it['similarity'] ) && null !== $it['similarity'] ? sprintf( /* translators: %d percent */ __( 'דמיון %d%%', 'trial-knowledge' ), (int) round( 100 * (float) $it['similarity'] ) ) : __( 'זהה', 'trial-knowledge' ),
							)
						)
					)
				) . '</span>';
			$actions = self::button( $id, 'remove_copy', __( 'מחיקת העותק הכפול', 'trial-knowledge' ), true, __( 'למחוק את העותק הזה מתיבת הקליטה? המסמך שכבר במערכת יישאר.', 'trial-knowledge' ) );
			if ( $possible ) {
				$actions .= self::button( $id, 'keep_and_process', __( 'זה מסמך אחר — לעבד', 'trial-knowledge' ), false, __( 'לשמור ולעבד את הקובץ כמסמך נפרד?', 'trial-knowledge' ) );
			}
			echo '<tr><td>' . wp_kses_post( $left ) . '</td><td>' . wp_kses_post( self::kept_html( $it['kept'] ?? null ) ) . '</td><td>'
				. $actions . '</td></tr>'; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- built from escaped parts above
		}
		echo '</tbody></table></div>';
	}

	private static function removed( array $items ) {
		echo '<div class="tk-card"><h2>' . esc_html__( 'עותקים שנמחקו', 'trial-knowledge' ) . ' <span class="count">(' . count( $items ) . ')</span></h2>';
		if ( ! $items ) {
			echo '<p>' . esc_html__( 'עוד לא נמחקו עותקים.', 'trial-knowledge' ) . '</p></div>';
			return;
		}
		echo '<table class="widefat striped"><thead><tr><th>' . esc_html__( 'הקובץ שנמחק', 'trial-knowledge' ) . '</th><th>' . esc_html__( 'מתי ומי', 'trial-knowledge' )
			. '</th><th>' . esc_html__( 'המסמך שנשאר', 'trial-knowledge' ) . '</th></tr></thead><tbody>';
		foreach ( $items as $it ) {
			$who = ( 'inbox:auto' === ( $it['removed_by'] ?? '' ) ) ? __( 'אוטומטית', 'trial-knowledge' ) : ( $it['removed_by'] ?? '' );
			echo '<tr><td><code dir="ltr">' . esc_html( $it['object_key'] ?? '' ) . '</code></td><td>' . esc_html( substr( (string) ( $it['removed_at'] ?? '' ), 0, 16 ) . ' · ' . $who )
				. '</td><td>' . wp_kses_post( self::kept_html( $it['kept'] ?? null ) ) . '</td></tr>';
		}
		echo '</tbody></table></div>';
	}

	public static function decide() {
		$item_id  = isset( $_POST['item_id'] ) ? sanitize_text_field( wp_unslash( $_POST['item_id'] ) ) : '';
		$decision = isset( $_POST['decision'] ) ? sanitize_key( wp_unslash( $_POST['decision'] ) ) : '';
		if ( ! current_user_can( TK_Permissions::CAP_SOURCES ) ) {
			wp_die( esc_html__( 'אין הרשאה.', 'trial-knowledge' ), 403 );
		}
		check_admin_referer( self::ACTION . '_' . $item_id );
		$back = admin_url( 'admin.php?page=trial-knowledge-duplicates' );
		if ( ! preg_match( '/^[0-9a-f-]{36}$/', $item_id ) || ! in_array( $decision, array( 'remove_copy', 'keep_and_process' ), true ) ) {
			wp_safe_redirect( add_query_arg( array( 'tk_msg' => rawurlencode( __( 'בקשה לא תקינה.', 'trial-knowledge' ) ) ), $back ) );
			exit;
		}
		try {
			tk_api()->post( '/v2/admin/inbox/items/' . $item_id . '/duplicate', array( 'action' => $decision ), true );
			$msg = 'remove_copy' === $decision ? __( 'העותק הכפול נמחק. המסמך שבמערכת נשאר.', 'trial-knowledge' ) : __( 'הקובץ נשמר ויעובד כמסמך נפרד.', 'trial-knowledge' );
			$ok  = '1';
		} catch ( TK_Api_Error $e ) {
			$msg = $e->getMessage();
			$ok  = '0';
		}
		wp_safe_redirect( add_query_arg( array( 'tk_msg' => rawurlencode( $msg ), 'tk_ok' => $ok ), $back ) );
		exit;
	}
}
