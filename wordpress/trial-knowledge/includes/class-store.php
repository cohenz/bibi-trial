<?php
/**
 * Local copy of the published public API responses (2.5). Readers are served from these
 * tables; the Knowledge API is called only to fill a missing row, and by the background
 * sync (TK_Sync) that keeps rows fresh. There is no TTL: a row is kept until it is
 * refreshed, or removed because its object is no longer published.
 *
 *   {prefix}tk_store       path_hash (sha256 of the canonical path), path, kind, body (JSON), tags,
 *                          fetched_at (UTC), stale, tries (failed refreshes), bytes
 *   {prefix}tk_store_tags  (tag, path_hash) — index for marking rows stale by object tag
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Store {

	const DB_VERSION = '1';
	const OPT_DB     = 'tk_store_db_version';

	/** A row whose refresh failed this many times waits for the next full sync. */
	const MAX_TRIES = 5;

	/** @var array in-request memo: path_hash → decoded body */
	private static $memo = array();

	/** @var string[] canonical paths requested in this process (tests, diagnostics) */
	public static $trace = array();

	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'tk_store';
	}

	public static function tags_table() {
		global $wpdb;
		return $wpdb->prefix . 'tk_store_tags';
	}

	public static function hash( $canonical ) {
		return hash( 'sha256', (string) $canonical );
	}

	/** Create or upgrade the tables (activation and version change). */
	public static function install() {
		global $wpdb;
		if ( ! function_exists( 'dbDelta' ) ) {
			require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		}
		$c = $wpdb->get_charset_collate();
		$t = self::table();
		$g = self::tags_table();
		dbDelta(
			"CREATE TABLE {$t} (
  path_hash char(64) NOT NULL,
  path text NOT NULL,
  kind varchar(20) NOT NULL DEFAULT '',
  body longtext NOT NULL,
  tags text NOT NULL,
  fetched_at datetime NOT NULL,
  stale tinyint(1) NOT NULL DEFAULT 0,
  tries smallint(5) unsigned NOT NULL DEFAULT 0,
  bytes int(10) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY  (path_hash),
  KEY stale (stale,tries,fetched_at),
  KEY kind (kind)
) {$c};"
		);
		dbDelta(
			"CREATE TABLE {$g} (
  path_hash char(64) NOT NULL,
  tag varchar(191) NOT NULL,
  PRIMARY KEY  (tag,path_hash),
  KEY path_hash (path_hash)
) {$c};"
		);
		update_option( self::OPT_DB, self::DB_VERSION, true );
		// 2.4 transient cache bookkeeping is no longer used (transients expire on their own).
		delete_option( 'tk_cache_index' );
		delete_option( 'tk_cache_generation' );
	}

	/** Run install() once after an update that changed the schema (or when the tables are missing). */
	public static function maybe_upgrade() {
		if ( get_option( self::OPT_DB ) !== self::DB_VERSION ) {
			self::install();
		}
	}

	/** Drop the tables (uninstall). */
	public static function drop() {
		global $wpdb;
		$wpdb->query( 'DROP TABLE IF EXISTS ' . self::table() ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared,WordPress.DB.DirectDatabaseQuery
		$wpdb->query( 'DROP TABLE IF EXISTS ' . self::tags_table() ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared,WordPress.DB.DirectDatabaseQuery
		delete_option( self::OPT_DB );
	}

	/** Paths that are never stored: signed admin calls, Ask, sync control calls. */
	public static function storable( $path ) {
		$p = (string) $path;
		return 0 === strpos( $p, '/v2/' ) && ! preg_match( '#^/v2/(admin|ask|sync|search|ready|health)(/|\?|$)#', $p );
	}

	/**
	 * Stored row for a canonical path.
	 *
	 * @param string $canonical Canonical path.
	 * @return array|null array( 'data' => array, 'stale' => bool )
	 */
	public static function read( $canonical ) {
		$h = self::hash( $canonical );
		if ( array_key_exists( $h, self::$memo ) ) {
			return self::$memo[ $h ];
		}
		global $wpdb;
		$row = $wpdb->get_row( $wpdb->prepare( 'SELECT body, stale FROM ' . self::table() . ' WHERE path_hash = %s', $h ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
		if ( ! is_array( $row ) ) {
			return null;
		}
		$data = json_decode( (string) $row['body'], true );
		if ( ! is_array( $data ) ) {
			return null;
		}
		$out              = array( 'data' => $data, 'stale' => (bool) (int) $row['stale'] );
		self::$memo[ $h ] = $out;
		return $out;
	}

	public static function exists( $canonical ) {
		global $wpdb;
		return null !== $wpdb->get_var( $wpdb->prepare( 'SELECT stale FROM ' . self::table() . ' WHERE path_hash = %s', self::hash( $canonical ) ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
	}

	/**
	 * Store (insert or replace) a fresh response.
	 *
	 * @param string      $canonical Canonical path.
	 * @param array       $data      Response.
	 * @param array       $tags      Caller tags (merged with the path's and the body's tags).
	 * @param string|null $prev_tags Tags string of the row being refreshed (skips rewriting an unchanged tag index).
	 * @return bool
	 */
	public static function put( $canonical, array $data, array $tags = array(), $prev_tags = null ) {
		global $wpdb;
		$body = wp_json_encode( $data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES );
		if ( ! is_string( $body ) ) {
			return false;
		}
		$h    = self::hash( $canonical );
		$all  = array_values( array_unique( array_filter( array_merge( TK_Paths::tags( $canonical ), $tags, TK_Paths::body_tags( $data ) ), 'strlen' ) ) );
		sort( $all );
		$tstr = implode( ' ', $all );
		$ok   = $wpdb->replace(
			self::table(),
			array(
				'path_hash'  => $h,
				'path'       => $canonical,
				'kind'       => TK_Paths::kind( $canonical ),
				'body'       => $body,
				'tags'       => $tstr,
				'fetched_at' => gmdate( 'Y-m-d H:i:s' ),
				'stale'      => 0,
				'tries'      => 0,
				'bytes'      => strlen( $body ),
			),
			array( '%s', '%s', '%s', '%s', '%s', '%s', '%d', '%d', '%d' )
		);
		if ( false === $ok ) {
			return false;
		}
		if ( $prev_tags !== $tstr ) {
			$wpdb->delete( self::tags_table(), array( 'path_hash' => $h ), array( '%s' ) );
			foreach ( $all as $tag ) {
				$wpdb->replace( self::tags_table(), array( 'path_hash' => $h, 'tag' => substr( $tag, 0, 191 ) ), array( '%s', '%s' ) );
			}
		}
		self::$memo[ $h ] = array( 'data' => $data, 'stale' => false );
		return true;
	}

	/** Remove one stored path (its object is no longer published). */
	public static function delete( $canonical ) {
		self::delete_hash( self::hash( $canonical ) );
	}

	public static function delete_hash( $h ) {
		global $wpdb;
		$wpdb->delete( self::table(), array( 'path_hash' => $h ), array( '%s' ) );
		$wpdb->delete( self::tags_table(), array( 'path_hash' => $h ), array( '%s' ) );
		unset( self::$memo[ $h ] );
	}

	/**
	 * Mark every row carrying one of $tags stale (it keeps being served until refreshed).
	 *
	 * @param string[] $tags Tags.
	 * @return int Rows marked.
	 */
	public static function mark_stale( array $tags ) {
		global $wpdb;
		$tags = array_values( array_unique( array_filter( array_map( 'strval', $tags ), 'strlen' ) ) );
		if ( ! $tags ) {
			return 0;
		}
		$hashes = array();
		foreach ( array_chunk( $tags, 100 ) as $chunk ) {
			$in     = implode( ', ', array_fill( 0, count( $chunk ), '%s' ) );
			$hashes = array_merge( $hashes, (array) $wpdb->get_col( $wpdb->prepare( 'SELECT path_hash FROM ' . self::tags_table() . " WHERE tag IN ($in)", $chunk ) ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.PreparedSQLPlaceholders.UnfinishedPrepare,WordPress.DB.DirectDatabaseQuery
		}
		$hashes = array_values( array_unique( $hashes ) );
		foreach ( array_chunk( $hashes, 500 ) as $chunk ) {
			$in = implode( ', ', array_fill( 0, count( $chunk ), '%s' ) );
			$wpdb->query( $wpdb->prepare( 'UPDATE ' . self::table() . " SET stale = 1 WHERE path_hash IN ($in)", $chunk ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.PreparedSQLPlaceholders.UnfinishedPrepare,WordPress.DB.DirectDatabaseQuery
		}
		self::$memo = array();
		return count( $hashes );
	}

	/** Mark every row stale (e.g. the API base URL changed). */
	public static function mark_all_stale() {
		global $wpdb;
		$n          = $wpdb->query( 'UPDATE ' . self::table() . ' SET stale = 1, tries = 0' ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared,WordPress.DB.DirectDatabaseQuery
		self::$memo = array();
		return (int) $n;
	}

	/** Give rows that failed too often another chance (daily full sync). */
	public static function reset_tries() {
		global $wpdb;
		$wpdb->query( 'UPDATE ' . self::table() . ' SET tries = 0 WHERE tries > 0' ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared,WordPress.DB.DirectDatabaseQuery
	}

	/**
	 * Oldest stale rows to refresh.
	 *
	 * @param int $limit Rows.
	 * @return array[] path_hash, path, tags
	 */
	public static function stale_batch( $limit ) {
		global $wpdb;
		return (array) $wpdb->get_results( $wpdb->prepare( 'SELECT path_hash, path, tags FROM ' . self::table() . ' WHERE stale = 1 AND tries < %d ORDER BY tries ASC, fetched_at ASC LIMIT %d', self::MAX_TRIES, (int) $limit ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
	}

	/** Stale rows still waiting for a refresh. */
	public static function pending() {
		global $wpdb;
		return (int) $wpdb->get_var( $wpdb->prepare( 'SELECT COUNT(*) FROM ' . self::table() . ' WHERE stale = 1 AND tries < %d', self::MAX_TRIES ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
	}

	public static function failed_refresh( $h ) {
		global $wpdb;
		$wpdb->query( $wpdb->prepare( 'UPDATE ' . self::table() . ' SET tries = tries + 1 WHERE path_hash = %s', $h ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
	}

	/**
	 * Stored paths of some kinds (pruning objects that are no longer published).
	 *
	 * @param string[] $kinds Kinds (TK_Paths::kind()).
	 * @return array[] path_hash, path, kind
	 */
	public static function paths_of_kinds( array $kinds ) {
		global $wpdb;
		if ( ! $kinds ) {
			return array();
		}
		$in = implode( ', ', array_fill( 0, count( $kinds ), '%s' ) );
		return (array) $wpdb->get_results( $wpdb->prepare( 'SELECT path_hash, path, kind FROM ' . self::table() . " WHERE kind IN ($in)", $kinds ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.PreparedSQLPlaceholders.UnfinishedPrepare,WordPress.DB.DirectDatabaseQuery
	}

	/** @return array count, bytes, stale, failed, kinds (kind → count, bytes) */
	public static function stats() {
		global $wpdb;
		$t   = self::table();
		$row = $wpdb->get_row( $wpdb->prepare( "SELECT COUNT(*) AS n, SUM(bytes) AS bytes, SUM(stale) AS stale FROM {$t} WHERE tries < %d", self::MAX_TRIES ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
		$bad = $wpdb->get_row( $wpdb->prepare( "SELECT COUNT(*) AS n, SUM(bytes) AS bytes, SUM(stale) AS stale FROM {$t} WHERE tries >= %d", self::MAX_TRIES ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
		$by  = (array) $wpdb->get_results( "SELECT kind, COUNT(*) AS n, SUM(bytes) AS bytes FROM {$t} GROUP BY kind", ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
		$kinds = array();
		foreach ( $by as $r ) {
			$kinds[ (string) $r['kind'] ] = array( 'count' => (int) $r['n'], 'bytes' => (int) $r['bytes'] );
		}
		ksort( $kinds );
		return array(
			'count'  => (int) ( $row['n'] ?? 0 ) + (int) ( $bad['n'] ?? 0 ),
			'bytes'  => (int) ( $row['bytes'] ?? 0 ) + (int) ( $bad['bytes'] ?? 0 ),
			'stale'  => (int) ( $row['stale'] ?? 0 ) + (int) ( $bad['stale'] ?? 0 ),
			'failed' => (int) ( $bad['stale'] ?? 0 ),
			'kinds'  => $kinds,
		);
	}

	/** Empty the local copy (admin "ניקוי העותק"). */
	public static function truncate() {
		global $wpdb;
		$wpdb->query( 'TRUNCATE TABLE ' . self::table() ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared,WordPress.DB.DirectDatabaseQuery
		$wpdb->query( 'TRUNCATE TABLE ' . self::tags_table() ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared,WordPress.DB.DirectDatabaseQuery
		self::$memo = array();
	}

	public static function forget_memo() {
		self::$memo = array();
	}

	/**
	 * Live GET of a public path for the sync (refresh, prefetch). An unpublished case guide is
	 * stored as a marker, exactly as TK_Guides::case_guide() stores it on a page view.
	 *
	 * @param string $canonical Canonical path.
	 * @return array
	 * @throws TK_Api_Error On errors (404 = no longer published).
	 */
	public static function fetch_live( $canonical ) {
		try {
			return tk_api()->get( $canonical );
		} catch ( TK_Api_Error $e ) {
			if ( 404 === $e->status && 'case' === TK_Paths::kind( $canonical ) ) {
				return array( '__missing' => true );
			}
			throw $e;
		}
	}
}
