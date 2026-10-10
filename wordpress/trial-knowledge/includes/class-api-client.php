<?php
/**
 * Knowledge API client with service-account request signing.
 *
 * canonical = METHOD \n PATH \n sorted-query \n timestamp \n nonce \n actor \n sha256(body)
 * signature = hex HMAC-SHA256(secret, canonical)
 * Must stay byte-identical to services/api/ntk_api/security.py (pinned by a
 * shared test vector in tests/test-signing.php and tests/unit/...).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Api_Error extends Exception {
	/** @var string */
	public $api_code;
	/** @var int */
	public $status;
	/** @var mixed */
	public $details;

	public function __construct( $message, $api_code = 'internal_error', $status = 0, $details = null ) {
		parent::__construct( $message );
		$this->api_code = $api_code;
		$this->status   = (int) $status;
		$this->details  = $details;
	}
}

class TK_Api_Client {

	/** @var array */
	private $cfg;

	public function __construct( array $cfg ) {
		$this->cfg = $cfg;
	}

	public function configured() {
		return ! empty( $this->cfg['api_base'] );
	}

	public function admin_configured() {
		return $this->configured() && ! empty( $this->cfg['key_id'] ) && ! empty( $this->cfg['secret'] );
	}

	public static function canonical( $method, $path, $query, $timestamp, $nonce, $actor, $body ) {
		$pairs = array();
		if ( '' !== (string) $query ) {
			foreach ( explode( '&', $query ) as $part ) {
				if ( '' === $part ) {
					continue;
				}
				$kv      = explode( '=', $part, 2 );
				$pairs[] = array( rawurldecode( str_replace( '+', ' ', $kv[0] ) ), isset( $kv[1] ) ? rawurldecode( str_replace( '+', ' ', $kv[1] ) ) : '' );
			}
			usort(
				$pairs,
				static function ( $a, $b ) {
					return strcmp( $a[0], $b[0] ) ?: strcmp( $a[1], $b[1] );
				}
			);
		}
		$q = array();
		foreach ( $pairs as $p ) {
			$q[] = self::py_quote_plus( $p[0] ) . '=' . self::py_quote_plus( $p[1] );
		}
		return implode(
			"\n",
			array( strtoupper( $method ), $path, implode( '&', $q ), (string) $timestamp, (string) $nonce, (string) $actor, hash( 'sha256', (string) $body ) )
		);
	}

	/** Python urllib.parse.urlencode uses quote_plus. */
	private static function py_quote_plus( $s ) {
		return str_replace( array( '%7E', '%20' ), array( '~', '+' ), rawurlencode( $s ) );
	}

	public static function sign( $secret, $method, $path, $query, $timestamp, $nonce, $actor, $body ) {
		return hash_hmac( 'sha256', self::canonical( $method, $path, $query, $timestamp, $nonce, $actor, $body ), $secret );
	}

	private function url( $path ) {
		return rtrim( (string) $this->cfg['api_base'], '/' ) . $path;
	}

	/**
	 * @param string     $method HTTP method.
	 * @param string     $path   API path starting with /v2.
	 * @param array|null $body   JSON body.
	 * @param bool       $admin  Sign as service account.
	 * @param array      $extra_headers Extra headers.
	 * @return array Decoded JSON.
	 * @throws TK_Api_Error On transport or API errors.
	 */
	public function request( $method, $path, $body = null, $admin = false, $extra_headers = array() ) {
		if ( ! $this->configured() ) {
			throw new TK_Api_Error( 'API base URL is not configured', 'not_configured' );
		}
		$raw     = null === $body ? '' : wp_json_encode( $body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES );
		$headers = array_merge( array( 'Accept' => 'application/json' ), $extra_headers );
		if ( null !== $body ) {
			$headers['Content-Type'] = 'application/json';
		}
		if ( $admin ) {
			if ( ! $this->admin_configured() ) {
				throw new TK_Api_Error( 'service credentials are not configured', 'not_configured' );
			}
			$parts                      = wp_parse_url( $this->url( $path ) );
			$ts                         = (string) time();
			$nonce                      = bin2hex( random_bytes( 12 ) );
			$actor                      = self::actor();
			$headers['X-NTK-Key-Id']    = $this->cfg['key_id'];
			$headers['X-NTK-Timestamp'] = $ts;
			$headers['X-NTK-Nonce']     = $nonce;
			$headers['X-NTK-Actor']     = $actor;
			$headers['X-NTK-Signature'] = self::sign( $this->cfg['secret'], $method, $parts['path'], $parts['query'] ?? '', $ts, $nonce, $actor, $raw );
		}
		$resp = wp_remote_request(
			$this->url( $path ),
			array(
				'method'      => $method,
				'headers'     => $headers,
				'body'        => null === $body ? null : $raw,
				'timeout'     => (int) ( $this->cfg['timeout'] ?? 15 ),
				'redirection' => 0,
			)
		);
		if ( is_wp_error( $resp ) ) {
			throw new TK_Api_Error( 'Knowledge API unreachable: ' . $resp->get_error_message(), 'unreachable' );
		}
		$status = (int) wp_remote_retrieve_response_code( $resp );
		$data   = json_decode( (string) wp_remote_retrieve_body( $resp ), true );
		if ( $status >= 400 ) {
			$code = is_array( $data ) && isset( $data['code'] ) ? $data['code'] : 'http_' . $status;
			$msg  = is_array( $data ) && isset( $data['message'] ) ? $data['message'] : 'HTTP ' . $status;
			throw new TK_Api_Error( $msg, $code, $status, is_array( $data ) ? ( $data['details'] ?? null ) : null );
		}
		return is_array( $data ) ? $data : array();
	}

	public function get( $path, $admin = false ) {
		return $this->request( 'GET', $path, null, $admin );
	}

	public function post( $path, $body, $admin = false ) {
		return $this->request( 'POST', $path, $body, $admin );
	}

	private static function actor() {
		if ( function_exists( 'wp_get_current_user' ) ) {
			$u = wp_get_current_user();
			if ( $u && $u->exists() ) {
				return 'wp:' . $u->user_login;
			}
		}
		return 'wp:system';
	}
}
