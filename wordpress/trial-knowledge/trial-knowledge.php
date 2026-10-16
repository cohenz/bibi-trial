<?php
/**
 * Plugin Name:       Trial Knowledge
 * Plugin URI:        https://example.org/trial-knowledge
 * Description:       Displays the Netanyahu trial knowledge base (start page, case and witness guides, dual timeline, glossary, claim cards, citations, hearings, Ask the Trial) from the Knowledge API, and provides upload, ingestion and review screens. The Knowledge API (PostgreSQL) prepares and publishes the content; readers are served from a local copy in the WordPress database that is kept in sync by webhooks and scheduled sync.
 * Version:           2.7.13
 * Requires at least: 6.4
 * Requires PHP:      8.1
 * Author:            Trial Knowledge
 * License:           GPL-2.0-or-later
 * Text Domain:       trial-knowledge
 * Domain Path:       /languages
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'TK_VERSION', '2.7.13' );
define( 'TK_FILE', __FILE__ );
define( 'TK_DIR', plugin_dir_path( __FILE__ ) );
define( 'TK_URL', plugin_dir_url( __FILE__ ) );
define( 'TK_OPTION', 'trial_knowledge_settings' );

require_once TK_DIR . 'includes/class-settings-store.php';
require_once TK_DIR . 'includes/class-api-client.php';
require_once TK_DIR . 'includes/class-paths.php';
require_once TK_DIR . 'includes/class-store.php';
require_once TK_DIR . 'includes/class-sync.php';
require_once TK_DIR . 'includes/class-cache.php';
require_once TK_DIR . 'includes/class-permissions.php';
require_once TK_DIR . 'includes/class-webhooks.php';
require_once TK_DIR . 'includes/class-render.php';
require_once TK_DIR . 'includes/class-guides.php';
require_once TK_DIR . 'includes/class-render-guides.php';
require_once TK_DIR . 'includes/class-render-nav.php';
require_once TK_DIR . 'includes/class-p315.php';
require_once TK_DIR . 'includes/class-rest-proxy.php';
require_once TK_DIR . 'includes/class-blocks.php';
require_once TK_DIR . 'includes/class-public-pages.php';
require_once TK_DIR . 'includes/class-admin-settings.php';
require_once TK_DIR . 'includes/class-admin-sources.php';
require_once TK_DIR . 'includes/class-admin-review.php';
require_once TK_DIR . 'includes/class-admin-duplicates.php';
require_once TK_DIR . 'includes/class-admin-store.php';
require_once TK_DIR . 'includes/class-admin-costs.php';
require_once TK_DIR . 'includes/class-questions.php';
require_once TK_DIR . 'includes/class-admin-questions.php';

/**
 * Bootstrap.
 */
function tk_boot() {
	load_plugin_textdomain( 'trial-knowledge', false, dirname( plugin_basename( TK_FILE ) ) . '/languages' );
	TK_Store::maybe_upgrade();
	TK_Sync::init();
	TK_Webhooks::init();
	TK_Rest_Proxy::init();
	TK_Blocks::init();
	TK_Public_Pages::init();
	TK_Questions::init();
	if ( is_admin() ) {
		TK_Admin_Costs::init();
		TK_Admin_Questions::init();
		TK_Admin_Settings::init();
		TK_Admin_Sources::init();
		TK_Admin_Review::init();
		TK_Admin_Duplicates::init();
		TK_Admin_Store::init();
	}
}
add_action( 'plugins_loaded', 'tk_boot' );

register_activation_hook( TK_FILE, array( 'TK_Permissions', 'activate' ) );
register_activation_hook( TK_FILE, array( 'TK_Public_Pages', 'activate' ) );
register_activation_hook( TK_FILE, array( 'TK_Sync', 'activate' ) );
register_deactivation_hook( TK_FILE, array( 'TK_Public_Pages', 'deactivate' ) );
register_deactivation_hook( TK_FILE, array( 'TK_Sync', 'deactivate' ) );
register_deactivation_hook( TK_FILE, array( 'TK_Questions', 'deactivate' ) );

/**
 * Shared API client.
 *
 * @return TK_Api_Client
 */
function tk_api() {
	static $client = null;
	if ( null === $client ) {
		$client = new TK_Api_Client( TK_Settings_Store::get() );
	}
	return $client;
}
