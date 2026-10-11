<?php
/**
 * Change webhook from the Knowledge API: marks the stored copies of the changed objects stale
 * (TK_Store) and schedules their background refresh; readers keep the stored copy meanwhile.
 * POST /wp-json/trial-knowledge/v1/webhook
 * Headers: X-NTK-Timestamp, X-NTK-Webhook-Signature = hex HMAC-SHA256(secret, "{ts}.{body}")
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Webhooks {

	const MAX_SKEW = 300;

	public static function init() {
		add_action( 'rest_api_init', array( __CLASS__, 'routes' ) );
	}

	public static function routes() {
		register_rest_route(
			'trial-knowledge/v1',
			'/webhook',
			array(
				'methods'             => 'POST',
				'callback'            => array( __CLASS__, 'handle' ),
				'permission_callback' => '__return_true', // authenticated by HMAC below.
			)
		);
	}

	public static function verify( $secret, $timestamp, $signature, $body, $now = null ) {
		if ( '' === (string) $secret || '' === (string) $signature || ! ctype_digit( (string) $timestamp ) ) {
			return false;
		}
		$now = null === $now ? time() : $now;
		if ( abs( $now - (int) $timestamp ) > self::MAX_SKEW ) {
			return false;
		}
		$expected = hash_hmac( 'sha256', $timestamp . '.' . $body, $secret );
		return hash_equals( $expected, strtolower( (string) $signature ) );
	}

	/**
	 * @param WP_REST_Request $request Request.
	 * @return WP_REST_Response|WP_Error
	 */
	public static function handle( $request ) {
		$body = (string) $request->get_body();
		$ok   = self::verify(
			TK_Settings_Store::webhook_secret(),
			(string) $request->get_header( 'x-ntk-timestamp' ),
			(string) $request->get_header( 'x-ntk-webhook-signature' ),
			$body
		);
		if ( ! $ok ) {
			return new WP_Error( 'tk_forbidden', 'invalid signature', array( 'status' => 401 ) );
		}
		$evt = json_decode( $body, true );
		if ( ! is_array( $evt ) || empty( $evt['event'] ) ) {
			return new WP_Error( 'tk_bad_request', 'invalid payload', array( 'status' => 400 ) );
		}
		$n = TK_Cache::purge( self::tags_for( $evt ) );
		return new WP_REST_Response( array( 'purged' => $n, 'stale' => $n ), 200 );
	}

	public static function tags_for( array $evt ) {
		$p    = isset( $evt['payload'] ) && is_array( $evt['payload'] ) ? $evt['payload'] : array();
		$tags = array( 'lists', 'status' );
		if ( ! empty( $p['object_type'] ) && ! empty( $p['object_id'] ) ) {
			$tags[] = sanitize_key( $p['object_type'] ) . ':' . preg_replace( '/[^A-Za-z0-9_\-]/', '', (string) $p['object_id'] );
		}
		if ( ! empty( $p['source_version_id'] ) ) {
			$tags[] = 'citations';
		}
		if ( isset( $evt['event'] ) && 0 === strpos( (string) $evt['event'], 'case_event' ) ) {
			$tags[] = 'timeline';
		}
		// 2.3 reader guides: a published/unpublished guide changes the start page, the case or
		// witness page and the story track; any published summary or source changes witness
		// pages and the trial track (those are also tagged 'lists', which every purge clears).
		$ot    = isset( $p['object_type'] ) ? (string) $p['object_type'] : '';
		$guide = ( $p['artifact_type'] ?? '' ) === 'guide' || in_array( $ot, array( 'case', 'witness', 'indictment' ), true );
		if ( $guide ) {
			$tags = array_merge( $tags, array( 'guide', 'guide:home', 'timeline' ) );
			if ( 'case' === $ot && ! empty( $p['object_id'] ) ) {
				$tags[] = 'guide:case:' . preg_replace( '/[^0-9]/', '', (string) $p['object_id'] );
			}
		}
		$event = (string) ( $evt['event'] ?? '' );
		if ( 0 === strpos( $event, 'source_version.' ) || ( 0 === strpos( $event, 'artifact.' ) && 'hearing' === $ot ) ) {
			$tags = array_merge( $tags, array( 'guide', 'timeline' ) );
		}
		// 2.4 document briefs (artifact_type summary, object_type document, object_id = sv_…): the brief changes
		// the document page ('document:<sv>' above), the document lists, the timeline (title, text, hearing days)
		// and, through hearing days, the start page and witness pages ('guide').
		if ( 0 === strpos( $event, 'artifact.' ) && 'document' === $ot ) {
			$tags = array_merge( $tags, array( 'documents', 'timeline', 'guide', 'guide:home' ) );
		}
		if ( 0 === strpos( $event, 'source_version.' ) ) {
			$tags[] = 'documents';
			if ( ! empty( $p['source_version_id'] ) ) {
				$tags[] = 'document:' . preg_replace( '/[^A-Za-z0-9_\-]/', '', (string) $p['source_version_id'] );
			}
		}
		return array_values( array_unique( $tags ) );
	}
}
