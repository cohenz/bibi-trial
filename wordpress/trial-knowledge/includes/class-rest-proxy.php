<?php
/**
 * Public REST proxy used by front-end blocks. It forwards only to PUBLIC API
 * endpoints, stores only published responses (local copy, TK_Store), and never exposes
 * credentials. Ask the Trial is always forwarded live (the API caches by corpus version).
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
		$ip      = self::visitor_ip();
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
			if ( 429 === $status && in_array( $e->api_code, array( 'daily_limit', 'visitor_daily_limit' ), true ) ) {
				$msg = 'daily_limit' === $e->api_code
					? __( 'הגענו למכסת השאלות החדשות להיום. שאלות שכבר נשאלו עדיין נענות, ואפשר לחפש בעמודי העדים, הדיונים והמסמכים. נסו שוב מחר.', 'trial-knowledge' )
					: __( 'שאלתם היום הרבה שאלות חדשות. שאלות שכבר נשאלו עדיין נענות; לשאלות חדשות נסו שוב מחר.', 'trial-knowledge' );
				return new WP_REST_Response( array( 'error' => $msg ), 429 );
			}
			return new WP_REST_Response( array( 'error' => 429 === $status ? __( 'נשאלו יותר מדי שאלות. נסו שוב בעוד דקה.', 'trial-knowledge' ) : __( 'לא ניתן לענות כרגע.', 'trial-knowledge' ) ), $status );
		}
		return new WP_REST_Response( array( 'html' => TK_Render::answer( $env ), 'envelope' => $env ), 200 );
	}

	/** The visitor's address: behind Cloudflare REMOTE_ADDR is a Cloudflare edge, so its header comes first. */
	public static function visitor_ip() {
		foreach ( array( 'HTTP_CF_CONNECTING_IP', 'REMOTE_ADDR' ) as $k ) {
			if ( ! empty( $_SERVER[ $k ] ) && is_string( $_SERVER[ $k ] ) ) {
				$ip = trim( sanitize_text_field( wp_unslash( $_SERVER[ $k ] ) ) );
				if ( filter_var( $ip, FILTER_VALIDATE_IP ) ) {
					return $ip;
				}
			}
		}
		return '';
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
			$data = self::cached_get( TK_Paths::citation( $id ) );
		} catch ( TK_Api_Error $e ) {
			return new WP_REST_Response( array( 'error' => 'not_found' ), 404 === $e->status ? 404 : 503 );
		}
		return new WP_REST_Response( $data, 200 );
	}

	/**
	 * GET of a PUBLIC endpoint (published objects only) through the local copy (TK_Store):
	 * served from the WordPress database; the API is called only when the path is not stored yet.
	 *
	 * @param string $path Path (built with TK_Paths).
	 * @param array  $tags Extra object tags (the path's own tags are added automatically).
	 * @return array
	 * @throws TK_Api_Error When the path is not stored and the API fails.
	 */
	public static function cached_get( $path, array $tags = array() ) {
		$canonical = TK_Paths::canonical( $path );
		return TK_Cache::remember(
			$canonical,
			static function () use ( $canonical ) {
				return tk_api()->get( $canonical );
			},
			$tags
		);
	}
}
