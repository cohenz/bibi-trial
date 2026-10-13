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
	/** A new answer (writer + verifier) takes about a minute with the defense lens (2.7.8); other API calls keep the
	 * short timeout. Under Cloudflare's 100-second limit for a request. */
	const ASK_TIMEOUT = 85;

	public static function ask( $req ) {
		if ( function_exists( 'set_time_limit' ) && ! ( defined( 'TK_TESTING' ) && TK_TESTING ) ) {
			@set_time_limit( self::ASK_TIMEOUT + 15 ); // phpcs:ignore WordPress.PHP.NoSilencedErrors.Discouraged
		}
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
				self::client_headers( $ip, $session ),
				self::ASK_TIMEOUT
			);
		} catch ( TK_Api_Error $e ) {
			$status = 429 === $e->status ? 429 : ( $e->status >= 400 && $e->status < 500 ? 400 : 503 );
			if ( 429 === $status && in_array( $e->api_code, array( 'daily_limit', 'visitor_daily_limit' ), true ) ) {
				$msg = 'daily_limit' === $e->api_code
					? __( 'הגענו למכסת השאלות החדשות להיום. שאלות שכבר נשאלו עדיין נענות, ואפשר לחפש בעמודי העדים, הדיונים והמסמכים. נסו שוב מחר.', 'trial-knowledge' )
					: __( 'שאלתם היום הרבה שאלות חדשות. שאלות שכבר נשאלו עדיין נענות; לשאלות חדשות נסו שוב מחר.', 'trial-knowledge' );
				return new WP_REST_Response( array( 'error' => $msg ), 429 );
			}
			if ( in_array( $e->api_code, array( 'timeout', 'answer_in_progress' ), true ) ) {
				// the answer keeps being prepared and is stored; asking again waits for it (the API never writes it
				// twice), so the page asks once more by itself (retry) before showing this
				return new WP_REST_Response( array( 'error' => __( 'התשובה עדיין בהכנה. נסו לשאול שוב בעוד דקה — היא תופיע מיד.', 'trial-knowledge' ), 'retry' => true ), 503 );
			}
			return new WP_REST_Response( array( 'error' => 429 === $status ? __( 'נשאלו יותר מדי שאלות. נסו שוב בעוד דקה.', 'trial-knowledge' ) : __( 'לא ניתן לענות כרגע.', 'trial-knowledge' ) ), $status );
		}
		return new WP_REST_Response( array( 'html' => TK_Render::answer( $env ), 'envelope' => $env ), 200 );
	}

	/** Cloudflare's published edge ranges (https://www.cloudflare.com/ips/). */
	const CLOUDFLARE = array(
		'173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22', '141.101.64.0/18', '108.162.192.0/18',
		'190.93.240.0/20', '188.114.96.0/20', '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
		'104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
		'2400:cb00::/32', '2606:4700::/32', '2803:f800::/32', '2405:b500::/32', '2405:8100::/32', '2a06:98c0::/29', '2c0f:f248::/32',
	);

	/**
	 * The visitor's address. Behind Cloudflare REMOTE_ADDR is a Cloudflare edge, and the visitor is in
	 * CF-Connecting-IP — trusted only when the request really came from a Cloudflare edge (anyone can send the header).
	 *
	 * @param array|null $server $_SERVER (tests pass their own).
	 */
	public static function visitor_ip( $server = null ) {
		$server = null === $server ? $_SERVER : $server;
		$remote = isset( $server['REMOTE_ADDR'] ) && is_string( $server['REMOTE_ADDR'] ) ? trim( $server['REMOTE_ADDR'] ) : '';
		$remote = filter_var( $remote, FILTER_VALIDATE_IP ) ? $remote : '';
		$cf     = isset( $server['HTTP_CF_CONNECTING_IP'] ) && is_string( $server['HTTP_CF_CONNECTING_IP'] ) ? trim( $server['HTTP_CF_CONNECTING_IP'] ) : '';
		if ( $remote && $cf && filter_var( $cf, FILTER_VALIDATE_IP ) && self::in_ranges( $remote, self::CLOUDFLARE ) ) {
			return $cf;
		}
		return $remote;
	}

	/** Is $ip inside one of the CIDR ranges (IPv4 or IPv6)? */
	public static function in_ranges( $ip, array $ranges ) {
		$bin = @inet_pton( $ip ); // phpcs:ignore WordPress.PHP.NoSilencedErrors.Discouraged -- invalid input returns false
		if ( false === $bin ) {
			return false;
		}
		foreach ( $ranges as $r ) {
			list( $net, $bits ) = explode( '/', $r );
			$nb                 = @inet_pton( $net ); // phpcs:ignore WordPress.PHP.NoSilencedErrors.Discouraged
			if ( false === $nb || strlen( $nb ) !== strlen( $bin ) ) {
				continue;
			}
			$bits  = (int) $bits;
			$bytes = intdiv( $bits, 8 );
			if ( substr( $bin, 0, $bytes ) !== substr( $nb, 0, $bytes ) ) {
				continue;
			}
			$rest = $bits % 8;
			if ( 0 === $rest || ( ( ord( $bin[ $bytes ] ) ^ ord( $nb[ $bytes ] ) ) & ( 0xFF << ( 8 - $rest ) ) & 0xFF ) === 0 ) {
				return true;
			}
		}
		return false;
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
