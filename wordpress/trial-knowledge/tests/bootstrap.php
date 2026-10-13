<?php
/**
 * Minimal WordPress stubs so the plugin's logic can be tested without a WP
 * install. When the official WP test suite is available, run PHPUnit with
 * it instead (see tests/README.md).
 */
define( 'ABSPATH', __DIR__ . '/' );
define( 'TK_OPTION', 'trial_knowledge_settings' );
define( 'TK_DIR', dirname( __DIR__ ) . '/' );
define( 'TK_URL', 'https://site.test/wp-content/plugins/trial-knowledge/' );
define( 'TK_VERSION', 'test' );
define( 'AUTH_KEY', 'test-auth-key' );

$GLOBALS['tk_options']    = array();
$GLOBALS['tk_transients'] = array();

function get_option( $k, $d = false ) { return array_key_exists( $k, $GLOBALS['tk_options'] ) ? $GLOBALS['tk_options'][ $k ] : $d; }
function update_option( $k, $v, $a = null ) { $GLOBALS['tk_options'][ $k ] = $v; return true; }
function delete_option( $k ) { unset( $GLOBALS['tk_options'][ $k ] ); return true; }
function get_transient( $k ) { return $GLOBALS['tk_transients'][ $k ] ?? false; }
function set_transient( $k, $v, $t = 0 ) { $GLOBALS['tk_transients'][ $k ] = $v; return true; }
function delete_transient( $k ) { unset( $GLOBALS['tk_transients'][ $k ] ); return true; }
function wp_salt( $s = 'auth' ) { return 'salt-' . $s; }
function wp_json_encode( $d, $o = 0 ) { return json_encode( $d, $o ); }
function __( $t, $d = null ) { return $t; }
function esc_html__( $t, $d = null ) { return esc_html( $t ); }
function esc_attr__( $t, $d = null ) { return esc_attr( $t ); }
function esc_html_e( $t, $d = null ) { echo esc_html( $t ); }
function esc_html( $t ) { return htmlspecialchars( (string) $t, ENT_QUOTES, 'UTF-8' ); }
function esc_attr( $t ) { return htmlspecialchars( (string) $t, ENT_QUOTES, 'UTF-8' ); }
function esc_url( $u ) { $u = (string) $u; return preg_match( '#^(https?:)?//#', $u ) || '' === $u || '/' === $u[0] ? htmlspecialchars( $u, ENT_QUOTES, 'UTF-8' ) : ''; }
function esc_textarea( $t ) { return esc_html( $t ); }
function home_url( $p = '' ) { return 'https://site.test' . $p; }
function rest_url( $p = '' ) { return 'https://site.test/wp-json/' . $p; }
function sanitize_title( $t ) { return strtolower( preg_replace( '/[^A-Za-z0-9-]+/', '-', (string) $t ) ); }
function sanitize_key( $k ) { return strtolower( preg_replace( '/[^a-z0-9_\-]/i', '', (string) $k ) ); }
function wp_trim_words( $t, $n = 55 ) { $w = preg_split( '/\s+/u', trim( (string) $t ) ); return implode( ' ', array_slice( $w, 0, $n ) ) . ( count( $w ) > $n ? '…' : '' ); }
function wp_rand( $a = 0, $b = 0 ) { return 4242; }
function wp_parse_url( $u, $c = -1 ) { return parse_url( $u, $c ); }
function nl2br_safe( $t ) { return nl2br( $t ); }
function current_user_can( $c ) { return false; }
function is_wp_error( $x ) { return false; }
function get_bloginfo( $s ) { return 'Site'; }
function add_action() {}
function add_filter() {}
function add_shortcode() {}
function add_query_arg( $k, $v = null, $u = "https://site.test/page/" ) {
	if ( is_array( $k ) ) { // add_query_arg( array $args, string $url )
		$u = null === $v ? "https://site.test/page/" : $v;
		foreach ( $k as $kk => $vv ) { $u = add_query_arg( $kk, $vv, $u ); }
		return $u;
	}
	return $u . ( false === strpos( $u, '?' ) ? '?' : '&' ) . rawurlencode( $k ) . '=' . rawurlencode( (string) $v );
}
function _n( $s, $p, $n, $d = null ) { return 1 === (int) $n ? $s : $p; }
function absint( $v ) { return abs( (int) $v ); }
function wp_unslash( $v ) { return $v; }
function admin_url( $p = '' ) { return 'https://site.test/wp-admin/' . $p; }
function sanitize_text_field( $v ) { return trim( strip_tags( (string) $v ) ); }
function add_option( $k, $v = '', $d = '', $a = 'yes' ) { if ( array_key_exists( $k, $GLOBALS['tk_options'] ) ) { return false; } $GLOBALS['tk_options'][ $k ] = $v; return true; }
function shortcode_atts( $pairs, $atts, $sc = '' ) { $out = array(); foreach ( $pairs as $k => $d ) { $out[ $k ] = array_key_exists( $k, (array) $atts ) ? $atts[ $k ] : $d; } return $out; }
function wp_enqueue_style() {}
function wp_enqueue_script() {}
function wp_add_inline_script() {}
function esc_url_raw( $u ) { return (string) $u; }
function remove_query_arg( $k, $u = '' ) { return (string) $u; }
function get_query_var( $k ) { return $GLOBALS['tk_query_vars'][ $k ] ?? ''; }
function is_admin() { return false; }
function wp_nonce_field( $a = -1, $n = '_wpnonce', $r = true, $e = true ) { return '<input type="hidden" name="' . $n . '" value="nonce">'; }
function dbDelta( $sql ) { $GLOBALS['tk_dbdelta'][] = $sql; return array(); }

// --- WP-Cron stubs (events kept in $GLOBALS['tk_cron'] as hook → timestamp)
$GLOBALS['tk_cron'] = array();
function wp_next_scheduled( $hook ) { return $GLOBALS['tk_cron'][ $hook ] ?? false; }
function wp_schedule_single_event( $ts, $hook ) { $GLOBALS['tk_cron'][ $hook ] = $ts; return true; }
function wp_schedule_event( $ts, $rec, $hook ) { $GLOBALS['tk_cron'][ $hook ] = $ts; return true; }
function wp_clear_scheduled_hook( $hook ) { unset( $GLOBALS['tk_cron'][ $hook ] ); return 1; }
/** Run a scheduled single event the way WP-Cron does (unscheduled first, then the callback). */
function tk_test_run_cron( $hook, callable $cb ) { unset( $GLOBALS['tk_cron'][ $hook ] ); return $cb(); }

define( 'MINUTE_IN_SECONDS', 60 );
define( 'HOUR_IN_SECONDS', 3600 );
define( 'DAY_IN_SECONDS', 86400 );
define( 'TK_TESTING', true );

require __DIR__ . '/fake-wpdb.php';
$GLOBALS['wpdb'] = new TK_Fake_WPDB();

require TK_DIR . 'includes/class-settings-store.php';
require TK_DIR . 'includes/class-api-client.php';
require TK_DIR . 'includes/class-paths.php';
require TK_DIR . 'includes/class-store.php';
require TK_DIR . 'includes/class-sync.php';
require TK_DIR . 'includes/class-cache.php';
require TK_DIR . 'includes/class-webhooks.php';
require TK_DIR . 'includes/class-public-pages.php';
require TK_DIR . 'includes/class-render.php';
require TK_DIR . 'includes/class-guides.php';
require TK_DIR . 'includes/class-render-guides.php';
require TK_DIR . 'includes/class-render-nav.php';
require TK_DIR . 'includes/class-p315.php';
require TK_DIR . 'includes/class-rest-proxy.php';
require TK_DIR . 'includes/class-blocks.php';
require TK_DIR . 'includes/class-admin-costs.php';
require TK_DIR . 'includes/class-questions.php';
require TK_DIR . 'includes/class-admin-questions.php';

/**
 * Fake Knowledge API client: records every GET; $handler( $path ) returns the body or throws;
 * $down = true simulates an unreachable API.
 */
final class TK_Fake_Api {
	public $calls   = array();
	public $down    = false;
	public $handler = null;
	public function get( $path, $admin = false ) {
		$this->calls[] = $path;
		if ( $this->down ) {
			throw new TK_Api_Error( 'Knowledge API unreachable: timeout', 'unreachable', 0 );
		}
		if ( $this->handler ) {
			return call_user_func( $this->handler, $path );
		}
		return array( 'path' => $path, 'n' => count( $this->calls ) );
	}
	public $post_error = null;
	public $last_timeout = null;
	public function request( $method, $path, $body = null, $admin = false, $h = array(), $timeout = null ) {
		$this->last_timeout = $timeout;
		if ( 'POST' === $method && $this->post_error ) {
			throw $this->post_error;
		}
		if ( 'GET' !== $method ) {
			throw new TK_Api_Error( 'not in tests', 'internal_error', 500 );
		}
		return $this->get( $path, $admin );
	}
}
$GLOBALS['tk_fake_api'] = new TK_Fake_Api();
function tk_api() { return $GLOBALS['tk_fake_api']; }
/** Fresh store, cron and fake API between test sections. */
function tk_test_reset_store() {
	$GLOBALS['wpdb']->reset();
	$GLOBALS['tk_cron']     = array();
	$GLOBALS['tk_fake_api'] = new TK_Fake_Api();
	TK_Store::forget_memo();
	TK_Store::$trace = array();
	foreach ( array_keys( $GLOBALS['tk_options'] ) as $k ) {
		if ( 0 === strpos( $k, 'tk_store' ) ) {
			unset( $GLOBALS['tk_options'][ $k ] );
		}
	}
}

/** Tiny assertion helpers (PHPUnit-like names). */
final class TK_T {
	public static $pass = 0;
	public static $fail = array();
	public static function eq( $exp, $act, $msg ) { if ( $exp === $act ) { ++self::$pass; } else { self::$fail[] = $msg . ' expected ' . var_export( $exp, true ) . ' got ' . var_export( $act, true ); } }
	public static function ok( $cond, $msg ) { if ( $cond ) { ++self::$pass; } else { self::$fail[] = $msg; } }
}
