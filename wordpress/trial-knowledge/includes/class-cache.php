<?php
/**
 * Cache for PUBLISHED public API responses only (spec §31.4).
 * Key = endpoint + params + corpus_version + artifact_version + locale.
 * Webhooks purge by object tag; drafts and admin views are never cached.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Cache {

	const INDEX = 'tk_cache_index';
	const GEN   = 'tk_cache_generation';

	public static function key( $endpoint, array $params = array(), $locale = 'he' ) {
		ksort( $params );
		$gen = (int) get_option( self::GEN, 1 );
		return 'tk_' . substr( hash( 'sha256', wp_json_encode( array( $endpoint, $params, $locale, $gen ) ) ), 0, 40 );
	}

	/**
	 * Fetch through cache.
	 *
	 * @param string   $endpoint Public API path.
	 * @param callable $fetch    Returns array; throws on error.
	 * @param array    $tags     Object tags for purge (e.g. claim:<id>).
	 * @param int      $ttl      Seconds.
	 * @return array
	 */
	public static function remember( $endpoint, callable $fetch, array $tags = array(), $ttl = 300, array $params = array() ) {
		$k   = self::key( $endpoint, $params );
		$hit = get_transient( $k );
		if ( false !== $hit && is_array( $hit ) ) {
			return $hit;
		}
		$data = $fetch();
		set_transient( $k, $data, max( 30, (int) $ttl ) );
		self::index( $k, $tags );
		return $data;
	}

	private static function index( $k, array $tags ) {
		$idx = get_option( self::INDEX, array() );
		$idx = is_array( $idx ) ? $idx : array();
		foreach ( array_merge( array( 'all' ), $tags ) as $t ) {
			$idx[ $t ]       = isset( $idx[ $t ] ) ? $idx[ $t ] : array();
			$idx[ $t ][ $k ] = 1;
			if ( count( $idx[ $t ] ) > 2000 ) {
				$idx[ $t ] = array_slice( $idx[ $t ], -1000, null, true );
			}
		}
		update_option( self::INDEX, $idx, false );
	}

	/**
	 * Purge keys for the given tags (and lists that may include them).
	 *
	 * @param array $tags Tags.
	 * @return int Number of keys removed.
	 */
	public static function purge( array $tags ) {
		$idx = get_option( self::INDEX, array() );
		$idx = is_array( $idx ) ? $idx : array();
		$n   = 0;
		foreach ( array_unique( array_merge( $tags, array( 'lists' ) ) ) as $t ) {
			if ( empty( $idx[ $t ] ) ) {
				continue;
			}
			foreach ( array_keys( $idx[ $t ] ) as $k ) {
				delete_transient( $k );
				++$n;
			}
			unset( $idx[ $t ] );
		}
		update_option( self::INDEX, $idx, false );
		return $n;
	}

	/** Invalidate everything by bumping the generation (O(1)). */
	public static function purge_all() {
		update_option( self::GEN, (int) get_option( self::GEN, 1 ) + 1, false );
		delete_option( self::INDEX );
	}
}
