<?php
/**
 * Removes plugin options and caches. Knowledge data lives in the Knowledge
 * API (PostgreSQL) and is not touched.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
	exit;
}
delete_option( 'trial_knowledge_settings' );
delete_option( 'tk_cache_index' );
delete_option( 'tk_cache_generation' );
foreach ( array( 'administrator', 'editor' ) as $tk_role_name ) {
	$tk_role = get_role( $tk_role_name );
	if ( $tk_role ) {
		foreach ( array( 'tk_manage_settings', 'tk_manage_sources', 'tk_review', 'tk_publish' ) as $tk_cap ) {
			$tk_role->remove_cap( $tk_cap );
		}
	}
}
