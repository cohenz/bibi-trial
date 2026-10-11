<?php
/**
 * Removes plugin options, the local copy of the published content (tables tk_store and
 * tk_store_tags) and its scheduled sync. Knowledge data lives in the Knowledge API
 * (PostgreSQL) and is not touched.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
	exit;
}
global $wpdb;
$wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}tk_store" ); // phpcs:ignore WordPress.DB.DirectDatabaseQuery,WordPress.DB.PreparedSQL.InterpolatedNotPrepared
$wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}tk_store_tags" ); // phpcs:ignore WordPress.DB.DirectDatabaseQuery,WordPress.DB.PreparedSQL.InterpolatedNotPrepared
foreach ( array( 'tk_store_refresh', 'tk_store_changes', 'tk_store_full', 'tk_store_full_step' ) as $tk_hook ) {
	wp_clear_scheduled_hook( $tk_hook );
}
foreach ( array( 'trial_knowledge_settings', 'tk_cache_index', 'tk_cache_generation', 'tk_rewrite_version', 'tk_store_db_version', 'tk_store_since', 'tk_store_changes_last', 'tk_store_refresh_last', 'tk_store_full', 'tk_store_full_queue', 'tk_store_lock' ) as $tk_option ) {
	delete_option( $tk_option );
}
foreach ( array( 'administrator', 'editor' ) as $tk_role_name ) {
	$tk_role = get_role( $tk_role_name );
	if ( $tk_role ) {
		foreach ( array( 'tk_manage_settings', 'tk_manage_sources', 'tk_review', 'tk_publish' ) as $tk_cap ) {
			$tk_role->remove_cap( $tk_cap );
		}
	}
}
