<?php
/**
 * Keeps the local copy (TK_Store) in sync with the Knowledge API (2.5). Everything here runs
 * in WP-Cron (or from the admin screen), never on a reader's page view.
 *
 *   tk_store_refresh    single event: refetch stale rows, ~40 per run, reschedules itself while
 *                       stale rows remain (webhooks and the changes sync mark rows stale)
 *   tk_store_changes    every 15 min: GET /v2/sync/changes?since=… → object tags → stale
 *   tk_store_full       daily: GET /v2/sync/objects → queue of every reader path (missing ones
 *                       fetched, index pages refreshed, unpublished objects pruned)
 *   tk_store_full_step  single event: works through that queue, ~30 requests per run
 *
 * One lock serialises the jobs so the site stays well under the API's per-client rate limit.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Sync {

	const HOOK_REFRESH   = 'tk_store_refresh';
	const HOOK_CHANGES   = 'tk_store_changes';
	const HOOK_FULL      = 'tk_store_full';
	const HOOK_FULL_STEP = 'tk_store_full_step';
	const SCHEDULE       = 'tk_every_15_minutes';

	const OPT_SINCE   = 'tk_store_since';
	const OPT_CHANGES = 'tk_store_changes_last';
	const OPT_REFRESH = 'tk_store_refresh_last';
	const OPT_FULL    = 'tk_store_full';
	const OPT_QUEUE   = 'tk_store_full_queue';
	const OPT_LOCK    = 'tk_store_lock';

	const REFRESH_BATCH    = 40;
	const FULL_BATCH       = 30;
	const REFRESH_DEBOUNCE = 60;  // seconds between a webhook and the refresh (bursts of webhooks coalesce)
	const STEP_GAP         = 30;  // seconds between batches (≤ ~80 API requests per minute)
	const BACKOFF          = 600; // API unreachable: retry in 10 minutes
	const BUDGET           = 20;  // seconds of work per run (cron requests must not time out)
	const LOCK_TTL         = 120;

	public static function init() {
		add_filter( 'cron_schedules', array( __CLASS__, 'schedules' ) ); // phpcs:ignore WordPress.WP.CronInterval.CronSchedulesInterval -- 15 minutes by design
		add_action( self::HOOK_REFRESH, array( __CLASS__, 'cron_refresh' ) );
		add_action( self::HOOK_CHANGES, array( __CLASS__, 'run_changes' ) );
		add_action( self::HOOK_FULL, array( __CLASS__, 'cron_full' ) );
		add_action( self::HOOK_FULL_STEP, array( __CLASS__, 'cron_full_step' ) );
		add_action( 'init', array( __CLASS__, 'maybe_ensure_schedules' ), 20 );
	}

	public static function schedules( $s ) {
		$s[ self::SCHEDULE ] = array(
			'interval' => 15 * MINUTE_IN_SECONDS,
			'display'  => __( 'כל 15 דקות', 'trial-knowledge' ),
		);
		return $s;
	}

	/** Activation and version upgrade: tables and recurring events. */
	public static function activate() {
		TK_Store::install();
		self::ensure_schedules();
	}

	public static function upgrade() {
		TK_Store::maybe_upgrade();
		self::ensure_schedules();
	}

	public static function deactivate() {
		foreach ( array( self::HOOK_REFRESH, self::HOOK_CHANGES, self::HOOK_FULL, self::HOOK_FULL_STEP ) as $h ) {
			wp_clear_scheduled_hook( $h );
		}
	}

	public static function maybe_ensure_schedules() {
		if ( is_admin() || ( function_exists( 'wp_doing_cron' ) && wp_doing_cron() ) ) {
			self::ensure_schedules();
		}
	}

	public static function ensure_schedules() {
		if ( ! wp_next_scheduled( self::HOOK_CHANGES ) ) {
			wp_schedule_event( time() + 5 * MINUTE_IN_SECONDS, self::SCHEDULE, self::HOOK_CHANGES );
		}
		if ( ! wp_next_scheduled( self::HOOK_FULL ) ) {
			wp_schedule_event( time() + 10 * MINUTE_IN_SECONDS, 'daily', self::HOOK_FULL );
		}
	}

	/** Schedule the stale-row refresh unless it is already scheduled. */
	public static function schedule_refresh( $delay = self::STEP_GAP ) {
		if ( ! wp_next_scheduled( self::HOOK_REFRESH ) ) {
			wp_schedule_single_event( time() + max( 1, (int) $delay ), self::HOOK_REFRESH );
		}
	}

	private static function schedule_full_step( $delay = self::STEP_GAP ) {
		if ( ! wp_next_scheduled( self::HOOK_FULL_STEP ) ) {
			wp_schedule_single_event( time() + max( 1, (int) $delay ), self::HOOK_FULL_STEP );
		}
	}

	// ----------------------------------------------------------------------------- lock

	private static function lock() {
		$until = (int) get_option( self::OPT_LOCK, 0 );
		if ( $until && $until < time() ) {
			delete_option( self::OPT_LOCK ); // a crashed run
		}
		return (bool) add_option( self::OPT_LOCK, time() + self::LOCK_TTL, '', 'no' );
	}

	private static function unlock() {
		delete_option( self::OPT_LOCK );
	}

	private static function long_run() {
		if ( function_exists( 'set_time_limit' ) && ! ( defined( 'TK_TESTING' ) && TK_TESTING ) ) {
			@set_time_limit( 120 ); // phpcs:ignore WordPress.PHP.NoSilencedErrors.Discouraged
		}
	}

	/** Transport error, rate limit or server error: the API is (temporarily) not answering. */
	private static function api_down( TK_Api_Error $e ) {
		return 0 === $e->status || 429 === $e->status || $e->status >= 500;
	}

	// ----------------------------------------------------------------------------- refresh

	public static function cron_refresh() {
		self::long_run();
		self::run_refresh();
	}

	/**
	 * Refetch up to $limit stale rows. A row whose object is gone (404) is removed; on other
	 * errors it stays (still served) and is retried later.
	 *
	 * @param int $limit  Rows per run.
	 * @param int $budget Seconds.
	 * @return array fetched, deleted, failed, remaining, down
	 */
	public static function run_refresh( $limit = self::REFRESH_BATCH, $budget = self::BUDGET ) {
		$res = array( 'time' => time(), 'fetched' => 0, 'deleted' => 0, 'failed' => 0, 'remaining' => 0, 'down' => false, 'error' => '' );
		if ( ! self::lock() ) {
			self::schedule_refresh( self::STEP_GAP );
			$res['locked'] = true;
			return $res;
		}
		try {
			$start = microtime( true );
			$five  = 0;
			foreach ( TK_Store::stale_batch( $limit ) as $r ) {
				if ( microtime( true ) - $start > $budget ) {
					break;
				}
				try {
					TK_Store::put( $r['path'], TK_Store::fetch_live( $r['path'] ), array(), (string) $r['tags'] );
					++$res['fetched'];
					$five = 0;
				} catch ( TK_Api_Error $e ) {
					$res['error'] = $e->getMessage();
					if ( 404 === $e->status || 410 === $e->status ) {
						TK_Store::delete_hash( $r['path_hash'] );
						++$res['deleted'];
					} elseif ( 0 === $e->status || 429 === $e->status ) {
						$res['down'] = true;
						break;
					} else {
						TK_Store::failed_refresh( $r['path_hash'] );
						++$res['failed'];
						if ( $e->status >= 500 && ++$five >= 3 ) {
							$res['down'] = true;
							break;
						}
					}
				}
			}
			$res['remaining'] = TK_Store::pending();
			if ( $res['remaining'] > 0 ) {
				self::schedule_refresh( $res['down'] ? self::BACKOFF : self::STEP_GAP );
			}
			update_option( self::OPT_REFRESH, $res, false );
		} finally {
			self::unlock();
		}
		return $res;
	}

	// ----------------------------------------------------------------------------- changes sync

	/**
	 * Object tags for a /v2/sync/changes response (the same tags the renderers' paths carry).
	 *
	 * @param array $r Response.
	 * @return string[]
	 */
	public static function changes_tags( array $r ) {
		$clean = static function ( $v ) {
			return preg_replace( '/[^A-Za-z0-9_\-]/', '', (string) $v );
		};
		$tags  = array();
		foreach ( (array) ( $r['hearings'] ?? array() ) as $id ) {
			$tags[] = 'hearing:' . $clean( $id );
		}
		foreach ( (array) ( $r['documents'] ?? array() ) as $id ) {
			$tags[] = 'document:' . $clean( $id );
		}
		foreach ( (array) ( $r['claims'] ?? array() ) as $id ) {
			$tags[] = 'claim:' . strtolower( $clean( $id ) );
		}
		$guides = (array) ( $r['guides'] ?? array() );
		foreach ( $guides as $g ) {
			$parts = explode( ':', (string) $g, 2 );
			$type  = $parts[0];
			$id    = $parts[1] ?? '';
			if ( 'case' === $type ) {
				$key    = preg_replace( '/[^0-9]/', '', $id );
				$tags[] = 'guide:case:' . $key;
				$tags[] = 'case:' . $key;
			} elseif ( 'witness' === $type ) {
				$tags[] = 'witness:' . $clean( $id );
			}
		}
		if ( $guides ) {
			// as for guide webhooks: the start page, the guide pages and the story track change too
			$tags = array_merge( $tags, array( 'guide', 'guide:home', 'timeline' ) );
		}
		if ( ! empty( $r['lists_changed'] ) ) {
			$tags = array_merge( $tags, array( 'lists', 'guide', 'timeline', 'documents' ) );
		}
		return array_values( array_unique( array_filter( $tags, static function ( $t ) {
			return ! preg_match( '/:$/', $t );
		} ) ) );
	}

	/** Cron/admin: ask the API what changed since the last successful sync and mark it stale. */
	public static function run_changes() {
		$since = (string) get_option( self::OPT_SINCE, '' );
		if ( '' === $since ) {
			$since = gmdate( 'Y-m-d\TH:i:s\Z', time() - DAY_IN_SECONDS );
		}
		$last = array( 'time' => time(), 'since' => $since, 'ok' => false );
		try {
			$r = tk_api()->get( TK_Paths::canonical( '/v2/sync/changes', array( 'since' => $since ) ) );
		} catch ( TK_Api_Error $e ) {
			$last['error'] = $e->getMessage();
			update_option( self::OPT_CHANGES, $last, false );
			return $last;
		}
		$tags   = self::changes_tags( $r );
		$marked = $tags ? TK_Store::mark_stale( $tags ) : 0;
		if ( $marked > 0 ) {
			self::schedule_refresh( 5 );
		}
		if ( ! empty( $r['now'] ) && is_string( $r['now'] ) ) {
			update_option( self::OPT_SINCE, $r['now'], false );
		}
		$last = array_merge(
			$last,
			array(
				'ok'             => true,
				'marked'         => $marked,
				'lists_changed'  => ! empty( $r['lists_changed'] ),
				'corpus_version' => (string) ( $r['corpus_version'] ?? '' ),
				'counts'         => array(
					'hearings'  => count( (array) ( $r['hearings'] ?? array() ) ),
					'documents' => count( (array) ( $r['documents'] ?? array() ) ),
					'guides'    => count( (array) ( $r['guides'] ?? array() ) ),
					'claims'    => count( (array) ( $r['claims'] ?? array() ) ),
				),
			)
		);
		update_option( self::OPT_CHANGES, $last, false );
		return $last;
	}

	// ----------------------------------------------------------------------------- full sync

	/**
	 * Every reader path for the objects in a /v2/sync/objects response, built with the same
	 * functions the renderers use. Entries are "1|path" (index page: always refetched) or
	 * "0|path" (object page: fetched only when missing).
	 *
	 * @param array   $o        /v2/sync/objects.
	 * @param array[] $doc_atts [tk_documents] attribute sets found in published content.
	 * @return string[]
	 */
	public static function plan( array $o, array $doc_atts = array() ) {
		$index = array( TK_Paths::guide(), TK_Paths::guide_timeline(), TK_Paths::glossary(), TK_Paths::timeline(), TK_Paths::latest_documents() );
		foreach ( array_unique( array_merge( TK_Guides::CASE_KEYS, array_map( 'strval', (array) ( $o['cases'] ?? array() ) ) ) ) as $key ) {
			if ( TK_Guides::valid_case( $key ) ) {
				$index[] = TK_Paths::guide_case( $key );
			}
		}
		$sets = array( array() );
		foreach ( (array) ( $o['document_types'] ?? array() ) as $t ) {
			$sets[] = array( 'type' => (string) $t );
		}
		foreach ( array_merge( $sets, $doc_atts ) as $atts ) {
			foreach ( array( false, true ) as $all ) {
				$req     = TK_Blocks::documents_request( $atts, $all );
				$index[] = $req['path'];
				if ( $req['procedural_path'] ) {
					$index[] = $req['procedural_path'];
				}
			}
		}
		$objects = array();
		foreach ( (array) ( $o['witnesses'] ?? array() ) as $slug ) {
			if ( TK_Guides::valid_witness( $slug ) ) {
				$objects[] = TK_Paths::guide_witness( $slug );
			}
		}
		foreach ( (array) ( $o['hearings'] ?? array() ) as $h ) {
			if ( empty( $h['id'] ) ) {
				continue;
			}
			$objects[] = TK_Public_Pages::request_path( 'hearing', $h['id'] );
			foreach ( TK_Paths::windows( $h['page_count'] ?? 1 ) as $p ) {
				$objects[] = TK_Paths::transcript( $h['id'], $p );
			}
		}
		foreach ( (array) ( $o['documents'] ?? array() ) as $d ) {
			if ( empty( $d['id'] ) ) {
				continue;
			}
			foreach ( TK_Paths::windows( $d['page_count'] ?? 1 ) as $p ) {
				$objects[] = TK_Paths::document( $d['id'], $p );
			}
		}
		foreach ( (array) ( $o['claims'] ?? array() ) as $id ) {
			$objects[] = TK_Public_Pages::request_path( 'claim', $id );
		}
		$out = array();
		foreach ( $index as $p ) {
			$out[ $p ] = '1|' . $p;
		}
		foreach ( $objects as $p ) {
			if ( ! isset( $out[ $p ] ) ) {
				$out[ $p ] = '0|' . $p;
			}
		}
		return array_values( $out );
	}

	/**
	 * Remove stored pages of hearings, claims and witnesses that the API no longer lists
	 * (unpublished while a webhook was missed). Document pages are kept: protocol documents
	 * are not listed by /v2/sync/objects and unpublished documents are caught by webhooks,
	 * the changes sync and the refresh (404 → removed).
	 *
	 * @param array $o /v2/sync/objects.
	 * @return int Rows removed.
	 */
	public static function prune( array $o ) {
		$keep = array(
			'hearing' => array_column( (array) ( $o['hearings'] ?? array() ), 'id' ),
			'claim'   => array_map( 'strtolower', array_map( 'strval', (array) ( $o['claims'] ?? array() ) ) ),
			'witness' => array_map( 'strval', (array) ( $o['witnesses'] ?? array() ) ),
		);
		$kinds = array();
		foreach ( $keep as $k => $ids ) {
			if ( $ids ) { // an empty list is treated as "unknown", never as "delete everything"
				$kinds[] = $k;
				$keep[ $k ] = array_flip( $ids );
			}
		}
		if ( isset( $keep['hearing'] ) && is_array( $keep['hearing'] ) && in_array( 'hearing', $kinds, true ) ) {
			$kinds[]            = 'transcript';
			$keep['transcript'] = $keep['hearing'];
		}
		$n = 0;
		foreach ( TK_Store::paths_of_kinds( $kinds ) as $r ) {
			$id = TK_Paths::object_id( $r['path'] );
			if ( '' !== $id && ! isset( $keep[ $r['kind'] ][ $id ] ) ) {
				TK_Store::delete_hash( $r['path_hash'] );
				++$n;
			}
		}
		return $n;
	}

	/** Parse [tk_documents …] attribute sets from post content. */
	public static function document_shortcodes( $content ) {
		$out = array();
		if ( ! preg_match_all( '/\[tk_documents(\s[^\]]*)?\]/', (string) $content, $m ) ) {
			return $out;
		}
		foreach ( $m[1] as $raw ) {
			$atts = array();
			if ( preg_match_all( '/([A-Za-z_][\w-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'\]]+))/', (string) $raw, $am, PREG_SET_ORDER ) ) {
				foreach ( $am as $a ) {
					$atts[ strtolower( $a[1] ) ] = $a[2] . ( $a[3] ?? '' ) . ( $a[4] ?? '' );
				}
			}
			$out[] = $atts;
		}
		return $out;
	}

	/** [tk_documents] attribute sets used in published posts and pages. */
	public static function used_document_atts() {
		global $wpdb;
		if ( empty( $wpdb->posts ) ) {
			return array();
		}
		$rows = (array) $wpdb->get_col( "SELECT post_content FROM {$wpdb->posts} WHERE post_status = 'publish' AND post_content LIKE '%[tk\\_documents%' LIMIT 500" ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
		$out  = array();
		foreach ( $rows as $c ) {
			foreach ( self::document_shortcodes( $c ) as $a ) {
				$out[ wp_json_encode( $a ) ] = $a;
			}
		}
		return array_values( $out );
	}

	public static function full_status() {
		$st = get_option( self::OPT_FULL, array() );
		return array_merge(
			array( 'status' => 'idle', 'started' => 0, 'finished' => 0, 'total' => 0, 'position' => 0, 'fetched' => 0, 'skipped' => 0, 'missing' => 0, 'failed' => 0, 'pruned' => 0, 'error' => '', 'stuck' => 0, 'corpus_version' => '' ),
			is_array( $st ) ? $st : array()
		);
	}

	public static function cron_full() {
		$st = self::full_status();
		if ( 'running' === $st['status'] && $st['started'] > time() - 6 * HOUR_IN_SECONDS ) {
			return; // the previous run is still working through its queue
		}
		self::start_full();
	}

	/**
	 * Start a full sync: read /v2/sync/objects, prune, queue every path, schedule the steps.
	 *
	 * @param array|null $objects Response (tests); fetched when null.
	 * @return array Status.
	 */
	public static function start_full( $objects = null ) {
		if ( null === $objects ) {
			try {
				$objects = tk_api()->get( '/v2/sync/objects' );
			} catch ( TK_Api_Error $e ) {
				$st           = self::full_status();
				$st['status'] = 'running' === $st['status'] ? 'running' : 'failed';
				$st['error']  = $e->getMessage();
				update_option( self::OPT_FULL, $st, false );
				return $st;
			}
		}
		$queue = self::plan( $objects, self::used_document_atts() );
		$st    = array(
			'status'         => 'running',
			'started'        => time(),
			'finished'       => 0,
			'total'          => count( $queue ),
			'position'       => 0,
			'fetched'        => 0,
			'skipped'        => 0,
			'missing'        => 0,
			'failed'         => 0,
			'pruned'         => self::prune( $objects ),
			'error'          => '',
			'stuck'          => 0,
			'corpus_version' => (string) ( $objects['corpus_version'] ?? '' ),
		);
		TK_Store::reset_tries();
		update_option( self::OPT_QUEUE, $queue, false );
		update_option( self::OPT_FULL, $st, false );
		wp_clear_scheduled_hook( self::HOOK_FULL_STEP );
		self::schedule_full_step( 1 );
		return $st;
	}

	public static function cron_full_step() {
		self::long_run();
		self::run_full_step();
	}

	/**
	 * Work through the queue: up to $limit API requests (stored object pages are skipped
	 * without a request).
	 *
	 * @param int $limit  Requests.
	 * @param int $budget Seconds.
	 * @return array Status.
	 */
	public static function run_full_step( $limit = self::FULL_BATCH, $budget = self::BUDGET ) {
		$st = self::full_status();
		if ( 'running' !== $st['status'] ) {
			return $st;
		}
		if ( ! self::lock() ) {
			self::schedule_full_step( self::STEP_GAP );
			return $st;
		}
		try {
			$queue = (array) get_option( self::OPT_QUEUE, array() );
			$total = count( $queue );
			$pos   = (int) $st['position'];
			$n     = 0;
			$retry = self::STEP_GAP;
			$start = microtime( true );
			while ( $pos < $total && $n < $limit && microtime( true ) - $start <= $budget ) {
				$parts = explode( '|', (string) $queue[ $pos ], 2 );
				$force = '1' === $parts[0];
				$path  = $parts[1] ?? '';
				if ( '' === $path || ( ! $force && TK_Store::exists( $path ) ) ) {
					++$st['skipped'];
					++$pos;
					continue;
				}
				++$n;
				try {
					TK_Store::put( $path, TK_Store::fetch_live( $path ) );
					++$st['fetched'];
					++$pos;
					$st['stuck'] = 0;
				} catch ( TK_Api_Error $e ) {
					$st['error'] = $path . ': ' . $e->getMessage();
					if ( 404 === $e->status || 410 === $e->status ) {
						TK_Store::delete( $path );
						++$st['missing'];
						++$pos;
					} elseif ( self::api_down( $e ) && ++$st['stuck'] < 3 ) {
						$retry = 429 === $e->status ? 60 : self::BACKOFF; // retry the same path later
						break;
					} else {
						++$st['failed'];
						++$pos;
						$st['stuck'] = 0;
					}
				}
			}
			$st['position'] = $pos;
			if ( $pos >= $total ) {
				$st['status']   = 'done';
				$st['finished'] = time();
				delete_option( self::OPT_QUEUE );
			} else {
				self::schedule_full_step( $retry );
			}
			update_option( self::OPT_FULL, $st, false );
		} finally {
			self::unlock();
		}
		return $st;
	}

	/** Stop a running full sync (the local copy is emptied). */
	public static function cancel_full() {
		wp_clear_scheduled_hook( self::HOOK_FULL_STEP );
		delete_option( self::OPT_QUEUE );
		$st = self::full_status();
		if ( 'running' === $st['status'] ) {
			$st['status']   = 'cancelled';
			$st['finished'] = time();
			update_option( self::OPT_FULL, $st, false );
		}
	}
}
