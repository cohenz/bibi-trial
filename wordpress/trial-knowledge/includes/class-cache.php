<?php
/**
 * Read-through access to PUBLISHED public API responses (spec §31.4), backed by the
 * local copy in the WordPress database (TK_Store, 2.5). No TTL:
 *
 *   row present → returned immediately, even when stale (a background refresh is scheduled,
 *                 never run inline on a page view);
 *   row missing → fetched live, stored, returned; on API errors the exception propagates
 *                 (the callers' existing "unavailable" behaviour).
 *
 * Webhooks and the sync mark rows stale by object tag (purge()); TK_Sync refreshes them.
 * Signed admin calls and POSTs never come here.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Cache {

	/**
	 * Store key of a request (sha256 of its canonical path; query order does not matter).
	 *
	 * @param string $endpoint Path.
	 * @param array  $params   Extra query parameters.
	 */
	public static function key( $endpoint, array $params = array(), $locale = 'he' ) {
		return TK_Store::hash( TK_Paths::canonical( $endpoint, $params ) );
	}

	/**
	 * Fetch through the local copy.
	 *
	 * @param string   $endpoint Public API path.
	 * @param callable $fetch    Returns array; throws on error. Called only when the path is not stored.
	 * @param array    $tags     Extra object tags (the path's own tags are added by TK_Paths::tags()).
	 * @param int      $ttl      Ignored since 2.5 (rows are kept until refreshed); kept for compatibility.
	 * @param array    $params   Extra query parameters (part of the key).
	 * @return array
	 */
	public static function remember( $endpoint, callable $fetch, array $tags = array(), $ttl = 0, array $params = array() ) {
		$path = TK_Paths::canonical( $endpoint, $params );
		if ( ! TK_Store::storable( $path ) ) {
			return $fetch();
		}
		TK_Store::$trace[] = $path;
		$row               = TK_Store::read( $path );
		if ( null !== $row ) {
			if ( $row['stale'] ) {
				TK_Sync::schedule_refresh();
			}
			return $row['data'];
		}
		$data = $fetch();
		if ( is_array( $data ) && self::worth_storing( $data ) ) {
			TK_Store::put( $path, $data, $tags );
		}
		return $data;
	}

	/**
	 * A page window past the end of a text (?tk_p= far beyond page_count) is answered but not
	 * stored, so arbitrary query values cannot grow the local copy.
	 *
	 * @param array $data Response.
	 */
	public static function worth_storing( array $data ) {
		return ! ( isset( $data['page_from'], $data['page_count'] ) && (int) $data['page_count'] > 0 && (int) $data['page_from'] > (int) $data['page_count'] );
	}

	/**
	 * Mark stored responses with the given tags (and the lists that may include them) stale and
	 * schedule their background refresh. Readers keep getting the stored copy meanwhile.
	 *
	 * @param array $tags Tags.
	 * @return int Rows marked.
	 */
	public static function purge( array $tags ) {
		$n = TK_Store::mark_stale( array_unique( array_merge( $tags, array( 'lists' ) ) ) );
		if ( $n > 0 ) {
			TK_Sync::schedule_refresh( TK_Sync::REFRESH_DEBOUNCE );
		}
		return $n;
	}

	/** Mark everything stale (refreshed in the background). */
	public static function purge_all() {
		$n = TK_Store::mark_all_stale();
		TK_Sync::schedule_refresh( TK_Sync::REFRESH_DEBOUNCE );
		return $n;
	}
}
