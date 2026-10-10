<?php
/**
 * Public REST proxy used by front-end blocks. It forwards only to PUBLIC API
 * endpoints, caches only published responses, and never exposes credentials.
 * Ask the Trial is forwarded without caching (the API caches by corpus version).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Rest_Proxy {

	public static function init() {
		add_action( 'rest_api_init', array( __CLASS__, 'routes' ) );
	}

	public static function routes() {
		register_rest_route(
			'trial-knowledge/v1',
			'/ask',
			array(
				'methods'             => 'POST',
				'callback'            => array( __CLASS__, 'ask' ),
				'permission_callback' => '__return_true',
				'args'                => array(
					'question' => array(
						'type'              => 'string',
						'required'          => true,
						'sanitize_callback' => 'sanitize_textarea_field',
						'validate_callback' => static function ( $v ) {
							return is_string( $v ) && mb_strlen( trim( $v ) ) >= 2 && mb_strlen( $v ) <= 500;
						},
					),
				),
			)
		);
		register_rest_route(
			'trial-knowledge/v1',
			'/citations/(?P<id>su_[0-9a-f]{26})',
			array(
				'methods'             => 'GET',
				'callback'            => array( __CLASS__, 'citation' ),
				'permission_callback' => '__return_true',
			)
		);
	}

	/**
	 * @param WP_REST_Request $req Request.
	 */
	public static function ask( $req ) {
		$ip      = isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '';
		$session = substr( hash( 'sha256', $ip . '|' . ( isset( $_SERVER['HTTP_USER_AGENT'] ) ? sanitize_text_field( wp_unslash( $_SERVER['HTTP_USER_AGENT'] ) ) : '' ) ), 0, 32 );
		try {
			$env = tk_api()->request(
				'POST',
				'/v2/ask',
				array(
					'question'          => (string) $req->get_param( 'question' ),
					'locale'            => 'he',
					'client_request_id' => 'wp-' . wp_generate_password( 12, false, false ),
				),
				false,
				self::client_headers( $ip, $session )
			);
		} catch ( TK_Api_Error $e ) {
			$status = 429 === $e->status ? 429 : ( $e->status >= 400 && $e->status < 500 ? 400 : 503 );
			return new WP_REST_Response( array( 'error' => 429 === $status ? __( 'נשאלו יותר מדי שאלות. נסו שוב בעוד דקה.', 'trial-knowledge' ) : __( 'לא ניתן לענות כרגע.', 'trial-knowledge' ) ), $status );
		}
		return new WP_REST_Response( array( 'html' => TK_Render::answer( $env ), 'envelope' => $env ), 200 );
	}

	/**
	 * Vouch for the end user so the API can rate-limit per visitor rather than
	 * per WordPress server: HMAC(secret, ts + "\n" + client_hash).
	 */
	public static function client_headers( $ip, $session ) {
		$cfg = TK_Settings_Store::get();
		$h   = array( 'X-NTK-Session' => $session );
		if ( ! empty( $cfg['key_id'] ) && ! empty( $cfg['secret'] ) ) {
			$ts                       = (string) time();
			$hash                     = substr( hash( 'sha256', wp_salt( 'nonce' ) . '|' . $ip ), 0, 32 );
			$h['X-NTK-Key-Id']        = $cfg['key_id'];
			$h['X-NTK-Client-Hash']   = $hash;
			$h['X-NTK-Client-Ts']     = $ts;
			$h['X-NTK-Client-Sig']    = hash_hmac( 'sha256', $ts . "\n" . $hash, $cfg['secret'] );
		}
		return $h;
	}

	/**
	 * @param WP_REST_Request $req Request.
	 */
	public static function citation( $req ) {
		$id = (string) $req['id'];
		try {
			$data = self::cached_get( '/v2/citations/' . $id, array( 'citations', 'citation:' . $id ) );
		} catch ( TK_Api_Error $e ) {
			return new WP_REST_Response( array( 'error' => 'not_found' ), 404 === $e->status ? 404 : 503 );
		}
		return new WP_REST_Response( $data, 200 );
	}

	/**
	 * Cached GET of a PUBLIC endpoint (published objects only).
	 *
	 * @param string $path Path.
	 * @param array  $tags Purge tags.
	 * @return array
	 */
	public static function cached_get( $path, array $tags = array() ) {
		$cfg = TK_Settings_Store::get();
		return TK_Cache::remember(
			$path,
			static function () use ( $path ) {
				return tk_api()->get( $path );
			},
			$tags,
			(int) $cfg['cache_ttl']
		);
	}
}
