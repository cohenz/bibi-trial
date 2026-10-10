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

require TK_DIR . 'includes/class-settings-store.php';
require TK_DIR . 'includes/class-api-client.php';
require TK_DIR . 'includes/class-cache.php';
require TK_DIR . 'includes/class-webhooks.php';
require TK_DIR . 'includes/class-public-pages.php';
require TK_DIR . 'includes/class-render.php';

/** Tiny assertion helpers (PHPUnit-like names). */
final class TK_T {
	public static $pass = 0;
	public static $fail = array();
	public static function eq( $exp, $act, $msg ) { if ( $exp === $act ) { ++self::$pass; } else { self::$fail[] = $msg . ' expected ' . var_export( $exp, true ) . ' got ' . var_export( $act, true ); } }
	public static function ok( $cond, $msg ) { if ( $cond ) { ++self::$pass; } else { self::$fail[] = $msg; } }
}
