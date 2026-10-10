<?php
/**
 * Capabilities and nonce helpers.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Permissions {

	const CAP_SETTINGS = 'tk_manage_settings';
	const CAP_SOURCES  = 'tk_manage_sources';
	const CAP_REVIEW   = 'tk_review';
	const CAP_PUBLISH  = 'tk_publish';

	public static function activate() {
		$admin = get_role( 'administrator' );
		if ( $admin ) {
			foreach ( array( self::CAP_SETTINGS, self::CAP_SOURCES, self::CAP_REVIEW, self::CAP_PUBLISH ) as $cap ) {
				$admin->add_cap( $cap );
			}
		}
		$editor = get_role( 'editor' );
		if ( $editor ) {
			$editor->add_cap( self::CAP_REVIEW );
		}
	}

	/**
	 * Verify capability and nonce for an admin AJAX/POST action; dies with a JSON error otherwise.
	 *
	 * @param string $cap    Capability.
	 * @param string $action Nonce action.
	 */
	public static function require_ajax( $cap, $action ) {
		if ( ! current_user_can( $cap ) ) {
			wp_send_json_error( array( 'message' => __( 'אין הרשאה לפעולה זו.', 'trial-knowledge' ) ), 403 );
		}
		if ( ! check_ajax_referer( $action, '_ajax_nonce', false ) ) {
			wp_send_json_error( array( 'message' => __( 'פג תוקף האבטחה של הדף. רעננו ונסו שוב.', 'trial-knowledge' ) ), 403 );
		}
	}
}
