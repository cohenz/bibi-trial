<?php
/**
 * Settings storage. The service secret is preferably defined in wp-config.php
 * (TK_API_SECRET, TK_WEBHOOK_SECRET). If stored in the database it is
 * encrypted with AES-256-GCM using a key derived from the site's AUTH salt,
 * and it is never sent to the browser.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Settings_Store {

	const DEFAULTS = array(
		'api_base'        => '',
		'key_id'          => '',
		'secret_enc'      => '',
		'webhook_enc'     => '',
		'cache_ttl'       => 300,
		'timeout'         => 15,
		'public_slug'     => 'trial',
		'disclosure'      => 'האתר בוחן טענות מקו ההגנה; חומר סותר מהותי מוצג בגוף העמוד. כל קביעה מלווה בציטוט למקור.',
	);

	/**
	 * @return array
	 */
	public static function get() {
		$opt = get_option( TK_OPTION, array() );
		$opt = is_array( $opt ) ? array_merge( self::DEFAULTS, $opt ) : self::DEFAULTS;
		$opt['secret']         = self::secret();
		$opt['webhook_secret'] = self::webhook_secret();
		return $opt;
	}

	public static function secret() {
		if ( defined( 'TK_API_SECRET' ) && TK_API_SECRET ) {
			return (string) TK_API_SECRET;
		}
		$opt = get_option( TK_OPTION, array() );
		return isset( $opt['secret_enc'] ) ? self::decrypt( $opt['secret_enc'] ) : '';
	}

	public static function webhook_secret() {
		if ( defined( 'TK_WEBHOOK_SECRET' ) && TK_WEBHOOK_SECRET ) {
			return (string) TK_WEBHOOK_SECRET;
		}
		$opt = get_option( TK_OPTION, array() );
		return isset( $opt['webhook_enc'] ) ? self::decrypt( $opt['webhook_enc'] ) : '';
	}

	public static function secret_from_constant() {
		return defined( 'TK_API_SECRET' ) && TK_API_SECRET;
	}

	/**
	 * @param array $values Sanitised values; secrets are given in plain text and encrypted here.
	 */
	public static function save( array $values ) {
		$opt = get_option( TK_OPTION, array() );
		$opt = is_array( $opt ) ? $opt : array();
		foreach ( array( 'api_base', 'key_id', 'cache_ttl', 'timeout', 'public_slug', 'disclosure' ) as $k ) {
			if ( array_key_exists( $k, $values ) ) {
				$opt[ $k ] = $values[ $k ];
			}
		}
		if ( ! empty( $values['secret'] ) ) {
			$opt['secret_enc'] = self::encrypt( $values['secret'] );
		}
		if ( ! empty( $values['webhook_secret'] ) ) {
			$opt['webhook_enc'] = self::encrypt( $values['webhook_secret'] );
		}
		update_option( TK_OPTION, $opt, false );
	}

	private static function key() {
		$salt = function_exists( 'wp_salt' ) ? wp_salt( 'auth' ) : ( defined( 'AUTH_KEY' ) ? AUTH_KEY : 'tk-insecure-default' );
		return hash( 'sha256', 'trial-knowledge|' . $salt, true );
	}

	public static function encrypt( $plain ) {
		if ( '' === (string) $plain ) {
			return '';
		}
		$iv  = random_bytes( 12 );
		$tag = '';
		$ct  = openssl_encrypt( (string) $plain, 'aes-256-gcm', self::key(), OPENSSL_RAW_DATA, $iv, $tag );
		if ( false === $ct ) {
			return '';
		}
		return 'v1:' . base64_encode( $iv . $tag . $ct ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_encode
	}

	public static function decrypt( $blob ) {
		if ( ! is_string( $blob ) || 0 !== strpos( $blob, 'v1:' ) ) {
			return '';
		}
		$raw = base64_decode( substr( $blob, 3 ), true ); // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions.obfuscation_base64_decode
		if ( false === $raw || strlen( $raw ) < 29 ) {
			return '';
		}
		$iv    = substr( $raw, 0, 12 );
		$tag   = substr( $raw, 12, 16 );
		$ct    = substr( $raw, 28 );
		$plain = openssl_decrypt( $ct, 'aes-256-gcm', self::key(), OPENSSL_RAW_DATA, $iv, $tag );
		return false === $plain ? '' : $plain;
	}
}
