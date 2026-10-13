<?php
/**
 * 2.5 local copy: TK_Paths (canonical keys, shared builders), TK_Store (read-through, no TTL),
 * TK_Sync (webhook/changes stale marking, refresh batches, full sync plan and queue), uninstall.
 */

$hr1 = 'hr_' . str_repeat( 'a', 26 );
$hr2 = 'hr_' . str_repeat( 'b', 26 );
$sv1 = 'sv_' . str_repeat( 'c', 26 );
$sv2 = 'sv_' . str_repeat( 'd', 26 );
$svp = 'sv_' . str_repeat( 'e', 26 ); // protocol of hr1
$su1 = 'su_' . str_repeat( 'f', 26 );
$wa  = 'w_0123456789';
$wb  = 'w_abcdef0123';
$cl1 = '11111111-2222-3333-4444-555555555555';
$cl2 = 'AAAAAAAA-2222-3333-4444-555555555555';

/** Minimal published payloads for every reader path, enough for the loaders and a few renderers. */
$tk_fixture = function ( $path ) use ( $svp, $sv1, $hr1, $wa ) {
	$id = TK_Paths::object_id( $path );
	switch ( TK_Paths::kind( $path ) ) {
		case 'guide':
			return array( 'cases' => array(), 'indictment' => null, 'witnesses' => array( array( 'slug' => $wa, 'name' => 'עד א', 'side' => 'prosecution' ) ), 'latest_hearing' => null, 'counts' => array( 'hearings' => 1, 'documents' => array() ) );
		case 'glossary':
			return array( 'terms' => array() );
		case 'guide_timeline':
			return array( 'events' => array() );
		case 'timeline':
			return array( 'events' => array(), 'documents' => array(), 'hearings' => array() );
		case 'list':
			return array( 'items' => array() );
		case 'case':
			if ( '1000' === $id ) {
				throw new TK_Api_Error( 'not published', 'unpublished_object', 404 );
			}
			return array( 'title' => 'תיק ' . $id, 'blocks' => array() );
		case 'witness':
			return array( 'name' => 'עד', 'slug' => $id, 'hearings' => array(), 'appearances' => array() );
		case 'hearing':
			return array( 'hearing' => array( 'id' => $id, 'hearing_date' => '2024-01-01', 'source_version_id' => $svp, 'witnesses' => array() ), 'digest' => null );
		case 'transcript':
			return array( 'hearing' => array( 'id' => $id, 'source_version_id' => $svp ), 'page_from' => 1, 'units' => array() );
		case 'document':
			return array( 'document' => array( 'title' => 'החלטה', 'source_type' => 'decision', 'source_version_id' => $id ), 'units' => array() );
		case 'claim':
			return array( 'bundle' => array( 'question' => 'שאלה ' . $id ) );
		case 'citation':
			return array( 'citation' => array( 'source_version_id' => $sv1, 'page' => 3 ), 'document' => array( 'title' => 'מסמך' ), 'hearing_id' => $hr1, 'text' => 'טקסט' );
	}
	throw new TK_Api_Error( 'no fixture for ' . $path, 'not_found', 404 );
};

// ------------------------------------------------------------------ path normalisation
TK_T::eq( '/v2/documents?limit=50&significance=substantive&type=decision', TK_Paths::canonical( '/v2/documents?type=decision&significance=substantive&limit=50' ), 'canonical: query params sorted' );
TK_T::eq( TK_Paths::canonical( '/v2/documents?limit=50&type=decision' ), TK_Paths::canonical( '/v2/documents?type=decision&limit=50' ), 'canonical: order does not matter' );
TK_T::eq( TK_Cache::key( '/v2/documents?type=decision&limit=50' ), TK_Cache::key( '/v2/documents', array( 'limit' => 50, 'type' => 'decision' ) ), 'key: params merged into the canonical path' );
TK_T::eq( '/v2/guide', TK_Paths::canonical( '/v2/guide?' ), 'canonical: empty query dropped' );
TK_T::eq( '/v2/timeline?as_of=2021-01-01T23%3A59%3A59Z', TK_Paths::canonical( '/v2/timeline?as_of=2021-01-01T23:59:59Z' ), 'canonical: values encoded uniformly' );
TK_T::eq( TK_Paths::canonical( '/v2/timeline?as_of=2021-01-01T23%3A59%3A59Z' ), TK_Paths::timeline( '2021-01-01' ), 'canonical: encoded and plain values give one key' );
TK_T::eq( '/v2/sync/changes?since=2026-10-11T08%3A00%3A00%2B00%3A00', TK_Paths::canonical( '/v2/sync/changes', array( 'since' => '2026-10-11T08:00:00+00:00' ) ), 'canonical: + in an ISO time is encoded' );
TK_T::eq( 26, TK_Paths::window_start( 27 ), 'window: page 27 is in the window starting at 26' );
TK_T::eq( 1, TK_Paths::window_start( 0 ), 'window: page < 1 → 1' );
TK_T::eq( array( 1, 26, 51 ), TK_Paths::windows( 51 ), 'windows of 51 pages' );
TK_T::eq( array( 1 ), TK_Paths::windows( null ), 'windows of unknown page count' );
TK_T::eq( TK_Paths::transcript( $hr1, 26 ), TK_Paths::transcript( $hr1, 50 ), 'transcript: pages of one window share one key' );
TK_T::eq( '/v2/claims/' . strtolower( $cl2 ), TK_Paths::claim( $cl2 ), 'claim ids lowercased' );
TK_T::ok( ! TK_Store::storable( '/v2/admin/review-tasks' ) && ! TK_Store::storable( '/v2/ask' ) && ! TK_Store::storable( '/v2/sync/objects' ) && TK_Store::storable( '/v2/guide' ), 'storable: admin, ask and sync are never stored' );
TK_T::eq( array( 'hearing:' . $hr1 ), TK_Paths::tags( TK_Paths::transcript( $hr1, 3 ) ), 'tags: transcript window' );
TK_T::eq( array( 'document:' . $sv1 ), TK_Paths::tags( TK_Paths::document( $sv1 ) ), 'tags: document window (no list tags)' );
TK_T::eq( array( 'document:' . $sv1, 'hearing:' . $hr1 ), TK_Paths::body_tags( $tk_fixture( TK_Paths::citation( $su1 ) ) ), 'tags: citation carries its source version and hearing' );

// ------------------------------------------------------------------ install
$GLOBALS['tk_dbdelta'] = array();
TK_Store::install();
TK_T::ok( 2 === count( $GLOBALS['tk_dbdelta'] ) && false !== strpos( $GLOBALS['tk_dbdelta'][0], 'CREATE TABLE wp_tk_store (' ) && false !== strpos( $GLOBALS['tk_dbdelta'][0], 'PRIMARY KEY  (path_hash)' ) && false !== strpos( $GLOBALS['tk_dbdelta'][1], 'CREATE TABLE wp_tk_store_tags (' ), 'install: dbDelta creates both tables' );
TK_T::eq( TK_Store::DB_VERSION, get_option( TK_Store::OPT_DB ), 'install: schema version recorded' );
$GLOBALS['tk_dbdelta'] = array();
TK_Store::maybe_upgrade();
TK_T::eq( array(), $GLOBALS['tk_dbdelta'], 'upgrade: no dbDelta when the schema is current' );
update_option( TK_Store::OPT_DB, '0' );
TK_Sync::upgrade();
TK_T::ok( 2 === count( $GLOBALS['tk_dbdelta'] ) && false !== wp_next_scheduled( TK_Sync::HOOK_CHANGES ) && false !== wp_next_scheduled( TK_Sync::HOOK_FULL ), 'upgrade: older schema → dbDelta and sync schedules' );

// ------------------------------------------------------------------ read-through
tk_test_reset_store();
tk_api()->handler = $tk_fixture;
$g = TK_Guides::home();
TK_T::eq( array( '/v2/guide' ), tk_api()->calls, 'miss: fetched live once' );
$row = $GLOBALS['wpdb']->tables['wp_tk_store'][ TK_Store::hash( '/v2/guide' ) ] ?? array();
TK_T::ok( '/v2/guide' === ( $row['path'] ?? '' ) && 'guide' === $row['kind'] && '0' === $row['stale'] && (int) $row['bytes'] === strlen( $row['body'] ) && 'guide guide:home lists' === $row['tags'], 'miss: row stored with path, kind, tags, bytes' );
TK_T::eq( 3, count( $GLOBALS['wpdb']->tables['wp_tk_store_tags'] ), 'miss: tag index rows' );
TK_Store::forget_memo();
TK_T::eq( $g, TK_Guides::home(), 'hit: same data from the database' );
TK_T::eq( 1, count( tk_api()->calls ), 'hit: no API call' );
TK_Rest_Proxy::cached_get( '/v2/documents?type=decision&limit=50' );
TK_Rest_Proxy::cached_get( '/v2/documents?limit=50&type=decision' );
TK_T::eq( 2, count( tk_api()->calls ), 'hit: reordered query is the same stored row' );
$adm = 0;
TK_Cache::remember( '/v2/admin/inbox', function () use ( &$adm ) { ++$adm; return array( 'x' => 1 ); } );
TK_Cache::remember( '/v2/admin/inbox', function () use ( &$adm ) { ++$adm; return array( 'x' => 1 ); } );
TK_T::eq( 2, $adm, 'admin paths are never stored' );
tk_api()->handler = function ( $path ) use ( $tk_fixture ) {
	return false !== strpos( $path, 'page_from=4976' ) ? array( 'page_from' => 4976, 'page_to' => 4976, 'page_count' => 12, 'units' => array() ) : $tk_fixture( $path );
};
$_GET['tk_p'] = 4999;
TK_Rest_Proxy::cached_get( TK_Public_Pages::transcript_path( $hr1 ) );
unset( $_GET['tk_p'] );
TK_T::ok( ! TK_Store::exists( TK_Paths::transcript( $hr1, 4999 ) ), 'a window past the end of the text is not stored' );
tk_api()->handler = $tk_fixture;
$_GET['tk_as_of'] = '2999-01-01';
TK_Blocks::timeline( array() );
$_GET['tk_as_of'] = '1900-05-05';
TK_Blocks::timeline( array() );
unset( $_GET['tk_as_of'] );
TK_T::ok( TK_Store::exists( TK_Paths::timeline() ) && TK_Store::exists( TK_Paths::timeline( '2016-01-01' ) ) && ! TK_Store::exists( TK_Paths::timeline( '2999-01-01' ) ), 'timeline block: as_of days are bounded' );
TK_T::eq( null, TK_Guides::case_guide( '1000' ), 'unpublished case guide → null' );
TK_Store::forget_memo();
$n = count( tk_api()->calls );
TK_Guides::case_guide( '1000' );
TK_T::eq( $n, count( tk_api()->calls ), 'unpublished case guide marker is stored too' );
tk_api()->down = true;
$err = null;
try {
	TK_Guides::witness( $wb );
} catch ( TK_Api_Error $e ) {
	$err = $e;
}
TK_T::ok( $err instanceof TK_Api_Error && 0 === $err->status, 'missing row + API down → existing error behaviour' );
TK_T::ok( false !== strpos( TK_Blocks::documents( array( 'type' => 'motion' ) ), 'המידע אינו זמין' ), 'missing list + API down → "unavailable" box' );

// ------------------------------------------------------------------ resilience: everything renders from the store with the API down
tk_test_reset_store();
tk_api()->handler = $tk_fixture;
$pages = array(
	array( 'hearing', $hr1, 'דיון 2024-01-01 | Site' ),
	array( 'document', $sv1, null ),
	array( 'claim', $cl1, 'שאלה ' . $cl1 . ' | Site' ),
	array( 'case', '4000', null ),
	array( 'witness', $wa, null ),
	array( 'timeline', 'all', 'ציר הזמן של המשפט | Site' ),
	array( 'witnesses', 'all', 'העדים במשפט | Site' ),
	array( 'glossary', 'all', 'מילון מונחים | Site' ),
);
$tk_view_all = function () use ( $pages, $hr1, $wa ) {
	$out = array();
	foreach ( $pages as $p ) {
		$GLOBALS['tk_query_vars'] = array( 'tk_type' => $p[0], 'tk_id' => $p[1] );
		TK_Public_Pages::$current = null;
		$out[]                    = TK_Public_Pages::title( 'fallback' );
	}
	$_GET['tk_p'] = 30;
	$out[]        = TK_Rest_Proxy::cached_get( TK_Public_Pages::transcript_path( $hr1 ) );
	unset( $_GET['tk_p'] );
	$out[] = TK_Blocks::start( array( 'ask' => '0' ) );
	$out[] = TK_Blocks::documents( array( 'type' => 'decision' ) );
	$out[] = TK_Blocks::witnesses( array() );
	$out[] = TK_Blocks::timeline( array() );
	$out[] = TK_Guides::hearing_exchanges( array( 'id' => $hr1, 'witnesses' => array( 'עד א' ) ), TK_Guides::slug_map( TK_Guides::witnesses() ) );
	return $out;
};
$online = $tk_view_all();
$calls  = count( tk_api()->calls );
TK_Store::forget_memo();
TK_Public_Pages::$current = null;
tk_api()->down            = true;
$offline                  = $tk_view_all();
TK_T::eq( $online, $offline, 'API down: every page renders the same from the store' );
TK_T::eq( $calls, count( tk_api()->calls ), 'API down: no API request from page views once the store is filled' );
TK_T::ok( false === strpos( implode( '', array_filter( $offline, 'is_string' ) ), 'המידע אינו זמין' ), 'API down: no "unavailable" box' );
TK_T::eq( 'דיון מיום 1.1.2024 | Site', $offline[0], 'API down: hearing page title from the store' );
TK_Cache::purge( array( 'hearing:' . $hr1 ) );
TK_Store::forget_memo();
TK_T::eq( $online, $tk_view_all(), 'API down: stale rows are still served' );

// ------------------------------------------------------------------ stale marking from webhook tags
tk_test_reset_store();
tk_api()->handler = $tk_fixture;
foreach ( array( TK_Paths::hearing( $hr1 ), TK_Paths::transcript( $hr1, 1 ), TK_Paths::transcript( $hr1, 26 ), TK_Paths::hearing( $hr2 ), TK_Paths::document( $sv1 ), TK_Paths::document( $sv2 ), TK_Paths::citation( $su1 ), TK_Paths::guide_witness( $wa ), TK_Paths::glossary(), TK_Paths::claim( $cl1 ) ) as $p ) {
	TK_Rest_Proxy::cached_get( $p );
}
$tk_stale = function () {
	$out = array();
	foreach ( $GLOBALS['wpdb']->tables['wp_tk_store'] as $r ) {
		if ( '1' === $r['stale'] ) {
			$out[] = $r['path'];
		}
	}
	sort( $out );
	return $out;
};
$tk_sorted = function ( array $a ) {
	sort( $a );
	return $a;
};
TK_Cache::purge( TK_Webhooks::tags_for( array( 'event' => 'source_version.published', 'payload' => array( 'source_version_id' => $sv1 ) ) ) );
TK_T::eq( $tk_sorted( array( TK_Paths::document( $sv1 ), TK_Paths::citation( $su1 ), TK_Paths::guide_witness( $wa ) ) ), $tk_stale(), 'webhook source_version: its document, its citations and list pages (witness) are stale; glossary, other objects not' );
TK_T::ok( false !== wp_next_scheduled( TK_Sync::HOOK_REFRESH ) && wp_next_scheduled( TK_Sync::HOOK_REFRESH ) >= time() + TK_Sync::REFRESH_DEBOUNCE - 1, 'webhook: one debounced refresh scheduled' );
$first = wp_next_scheduled( TK_Sync::HOOK_REFRESH );
TK_Cache::purge( array( 'claim:' . $cl1 ) );
TK_T::eq( $first, wp_next_scheduled( TK_Sync::HOOK_REFRESH ), 'webhook: a scheduled refresh is not scheduled twice' );
TK_Store::mark_stale( array( 'nothing' ) );
TK_Sync::run_refresh();
TK_T::eq( array(), $tk_stale(), 'refresh: all stale rows refreshed' );
TK_Cache::purge( TK_Webhooks::tags_for( array( 'event' => 'artifact.published', 'payload' => array( 'artifact_type' => 'digest', 'object_type' => 'hearing', 'object_id' => $hr1 ) ) ) );
$st = $tk_stale();
TK_T::ok( in_array( TK_Paths::hearing( $hr1 ), $st, true ) && in_array( TK_Paths::transcript( $hr1, 1 ), $st, true ) && in_array( TK_Paths::transcript( $hr1, 26 ), $st, true ) && ! in_array( TK_Paths::hearing( $hr2 ), $st, true ), 'webhook hearing artifact: the hearing page and all its transcript windows are stale, other hearings not' );
TK_Sync::run_refresh();
TK_Cache::purge( TK_Webhooks::tags_for( array( 'event' => 'source_version.unpublished', 'payload' => array( 'source_version_id' => $svp ) ) ) );
TK_T::ok( in_array( TK_Paths::transcript( $hr1, 1 ), $tk_stale(), true ), 'webhook on a protocol source version reaches its hearing pages (tag from the body)' );

// ------------------------------------------------------------------ changes sync
$changes = array(
	'since'          => '2026-10-10T08:00:00+00:00',
	'now'            => '2026-10-11T08:00:00.123456+00:00',
	'corpus_version' => 'cv_9',
	'lists_changed'  => true,
	'hearings'       => array( $hr1 ),
	'documents'      => array( $sv2 ),
	'guides'         => array( 'case:4000', 'witness:' . $wa, 'indictment:main' ),
	'claims'         => array( $cl2 ),
);
$tags = TK_Sync::changes_tags( $changes );
$exp  = array( 'hearing:' . $hr1, 'document:' . $sv2, 'claim:' . strtolower( $cl2 ), 'guide:case:4000', 'case:4000', 'witness:' . $wa, 'guide', 'guide:home', 'timeline', 'lists', 'documents' );
TK_T::eq( $tk_sorted( $exp ), $tk_sorted( $tags ), 'changes: ids mapped to the renderers\' tags' );
TK_T::eq( array( 'hearing:' . $hr2 ), TK_Sync::changes_tags( array( 'lists_changed' => false, 'hearings' => array( $hr2 ), 'documents' => array(), 'guides' => array(), 'claims' => array() ) ), 'changes: no list tags when lists did not change' );
foreach ( array( TK_Paths::guide_case( '4000' ), TK_Paths::guide(), TK_Paths::documents_list( '', 50, 'substantive' ) ) as $p ) {
	TK_Rest_Proxy::cached_get( $p );
}
TK_Sync::run_refresh();
TK_Store::truncate();
tk_test_reset_store();
tk_api()->handler = $tk_fixture;
foreach ( array( TK_Paths::hearing( $hr1 ), TK_Paths::hearing( $hr2 ), TK_Paths::document( $sv2 ), TK_Paths::guide_case( '4000' ), TK_Paths::guide_case( '2000' ), TK_Paths::guide(), TK_Paths::glossary(), TK_Paths::claim( $cl2 ), TK_Paths::claim( $cl1 ), TK_Paths::documents_list( '', 50, 'substantive' ) ) as $p ) {
	TK_Rest_Proxy::cached_get( $p );
}
$sync_calls       = array();
tk_api()->handler = function ( $path ) use ( $changes, &$sync_calls, $tk_fixture ) {
	if ( 0 === strpos( $path, '/v2/sync/changes' ) ) {
		$sync_calls[] = $path;
		return $changes;
	}
	return $tk_fixture( $path );
};
$res = TK_Sync::run_changes();
parse_str( (string) parse_url( $sync_calls[0], PHP_URL_QUERY ), $q );
TK_T::ok( abs( strtotime( $q['since'] ) - ( time() - DAY_IN_SECONDS ) ) < 5, 'changes: first run asks for the last day' );
TK_T::ok( $res['ok'] && 'cv_9' === $res['corpus_version'] && 1 === $res['counts']['hearings'], 'changes: result recorded' );
TK_T::eq( $tk_sorted( array( TK_Paths::hearing( $hr1 ), TK_Paths::document( $sv2 ), TK_Paths::guide_case( '4000' ), TK_Paths::guide_case( '2000' ), TK_Paths::guide(), TK_Paths::claim( $cl2 ), TK_Paths::documents_list( '', 50, 'substantive' ) ) ), $tk_stale(), 'changes: changed objects and lists stale; other hearings, claims and the glossary not' );
TK_T::eq( $changes['now'], get_option( TK_Sync::OPT_SINCE ), 'changes: "now" stored as the next since' );
TK_T::ok( false !== wp_next_scheduled( TK_Sync::HOOK_REFRESH ), 'changes: refresh scheduled' );
TK_Sync::run_changes();
TK_T::eq( TK_Paths::canonical( '/v2/sync/changes', array( 'since' => $changes['now'] ) ), $sync_calls[1], 'changes: second run continues from the stored time' );
tk_api()->down = true;
$res           = TK_Sync::run_changes();
TK_T::ok( ! $res['ok'] && '' !== $res['error'] && $changes['now'] === get_option( TK_Sync::OPT_SINCE ), 'changes: failure recorded, since kept' );

// ------------------------------------------------------------------ batch refresh limits
tk_test_reset_store();
for ( $i = 0; $i < 100; $i++ ) {
	TK_Store::put( TK_Paths::citation( 'su_' . str_pad( (string) $i, 26, '0', STR_PAD_LEFT ) ), array( 'i' => $i ) );
}
TK_Store::mark_all_stale();
$r = tk_test_run_cron( TK_Sync::HOOK_REFRESH, array( 'TK_Sync', 'run_refresh' ) );
TK_T::ok( 40 === $r['fetched'] && 40 === count( tk_api()->calls ) && 60 === $r['remaining'], 'refresh: 40 rows per run' );
TK_T::ok( wp_next_scheduled( TK_Sync::HOOK_REFRESH ) <= time() + TK_Sync::STEP_GAP, 'refresh: reschedules itself while stale rows remain' );
tk_test_run_cron( TK_Sync::HOOK_REFRESH, array( 'TK_Sync', 'run_refresh' ) );
$r = tk_test_run_cron( TK_Sync::HOOK_REFRESH, array( 'TK_Sync', 'run_refresh' ) );
TK_T::ok( 20 === $r['fetched'] && 0 === $r['remaining'] && 100 === count( tk_api()->calls ), 'refresh: last batch' );
TK_T::eq( false, wp_next_scheduled( TK_Sync::HOOK_REFRESH ), 'refresh: not rescheduled when nothing is stale' );
TK_Store::mark_all_stale();
tk_api()->handler = function ( $path ) {
	if ( false !== strpos( $path, 'su_00000000000000000000000001' ) ) {
		throw new TK_Api_Error( 'gone', 'unpublished_object', 404 );
	}
	if ( false !== strpos( $path, 'su_00000000000000000000000002' ) ) {
		throw new TK_Api_Error( 'bad', 'invalid_request', 400 );
	}
	return array( 'ok' => 1 );
};
TK_Sync::run_refresh( 5 );
TK_T::ok( ! TK_Store::exists( TK_Paths::citation( 'su_00000000000000000000000001' ) ), 'refresh: unpublished object (404) removed from the store' );
TK_T::eq( '1', $GLOBALS['wpdb']->tables['wp_tk_store'][ TK_Store::hash( TK_Paths::citation( 'su_00000000000000000000000002' ) ) ]['tries'], 'refresh: other error → kept (still served), tries counted' );
$n             = count( tk_api()->calls );
tk_api()->down = true;
$GLOBALS['tk_cron'] = array();
$r                  = TK_Sync::run_refresh();
TK_T::ok( $r['down'] && 1 === count( tk_api()->calls ) - $n && 0 === $r['fetched'], 'refresh: API down → stops after the first failure' );
TK_T::ok( wp_next_scheduled( TK_Sync::HOOK_REFRESH ) >= time() + TK_Sync::BACKOFF - 1, 'refresh: API down → retried after the back-off' );
TK_T::eq( 96, TK_Store::pending(), 'refresh: API down → nothing removed or given up' );
add_option( TK_Sync::OPT_LOCK, time() + 60 );
$r = TK_Sync::run_refresh();
TK_T::ok( ! empty( $r['locked'] ), 'refresh: one job at a time (lock)' );
delete_option( TK_Sync::OPT_LOCK );
add_option( TK_Sync::OPT_LOCK, time() - 1 );
tk_api()->down = false;
$r             = TK_Sync::run_refresh();
TK_T::ok( empty( $r['locked'] ) && $r['fetched'] > 0, 'refresh: an expired lock (crashed run) is taken over' );

// ------------------------------------------------------------------ full sync: plan = what the renderers request
tk_test_reset_store();
tk_api()->handler = $tk_fixture;
$objects          = array(
	'corpus_version' => 'cv_9',
	'hearings'       => array( array( 'id' => $hr1, 'page_count' => 60 ), array( 'id' => $hr2, 'page_count' => 12 ) ),
	'documents'      => array( array( 'id' => $sv1, 'page_count' => 30, 'source_type' => 'decision' ), array( 'id' => $sv2, 'page_count' => null, 'source_type' => 'motion' ) ),
	'cases'          => array( '4000', '2000' ),
	'witnesses'      => array( $wa, $wb ),
	'claims'         => array( $cl1, $cl2 ),
	'document_types' => array( 'decision', 'motion' ),
);
$used = TK_Sync::document_shortcodes( '<p>x</p>[tk_documents type="notice" limit="20"] and [tk_documents type=\'decision\' procedural="show"] [tk_documents]' );
TK_T::eq( array( array( 'type' => 'notice', 'limit' => '20' ), array( 'type' => 'decision', 'procedural' => 'show' ), array() ), $used, 'shortcodes: [tk_documents] attributes parsed' );
$plan  = TK_Sync::plan( $objects, $used );
$paths = array_map( static function ( $e ) { return substr( $e, 2 ); }, $plan );
TK_T::eq( count( $paths ), count( array_unique( $paths ) ), 'plan: no duplicates' );
TK_T::ok( in_array( '1|' . TK_Paths::guide(), $plan, true ) && in_array( '0|' . TK_Paths::hearing( $hr1 ), $plan, true ), 'plan: index pages forced, object pages only when missing' );

// what the renderers request for the same objects (every page of every view, both document-list modes)
TK_Store::$trace = array();
foreach ( TK_Guides::CASE_KEYS as $k ) {
	$GLOBALS['tk_query_vars'] = array( 'tk_type' => 'case', 'tk_id' => (string) $k );
	TK_Public_Pages::$current = null;
	TK_Public_Pages::title( '' );
}
foreach ( array( $wa, $wb ) as $w ) {
	$GLOBALS['tk_query_vars'] = array( 'tk_type' => 'witness', 'tk_id' => $w );
	TK_Public_Pages::$current = null;
	TK_Public_Pages::title( '' );
}
foreach ( array( 'timeline', 'witnesses', 'glossary' ) as $s ) {
	$GLOBALS['tk_query_vars'] = array( 'tk_type' => $s, 'tk_id' => 'all' );
	TK_Public_Pages::$current = null;
	TK_Public_Pages::title( '' );
}
foreach ( $objects['hearings'] as $h ) {
	for ( $p = 1; $p <= $h['page_count']; $p++ ) { // every ?tk_p= a reader can open
		$_GET['tk_p']             = $p;
		$GLOBALS['tk_query_vars'] = array( 'tk_type' => 'hearing', 'tk_id' => $h['id'] );
		TK_Public_Pages::$current = null;
		TK_Public_Pages::title( '' );
		TK_Rest_Proxy::cached_get( TK_Public_Pages::transcript_path( $h['id'] ) ); // templates/single-hearing.php
	}
}
foreach ( $objects['documents'] as $d ) {
	for ( $p = 1; $p <= max( 1, (int) $d['page_count'] ); $p++ ) {
		$_GET['tk_p']             = $p;
		$GLOBALS['tk_query_vars'] = array( 'tk_type' => 'document', 'tk_id' => $d['id'] );
		TK_Public_Pages::$current = null;
		TK_Public_Pages::title( '' );
	}
}
unset( $_GET['tk_p'] );
foreach ( $objects['claims'] as $c ) {
	$GLOBALS['tk_query_vars'] = array( 'tk_type' => 'claim', 'tk_id' => $c );
	TK_Public_Pages::$current = null;
	TK_Public_Pages::title( '' );
}
TK_Blocks::start( array( 'ask' => '0' ) );
TK_Blocks::timeline( array() );
foreach ( array_merge( array( array() ), array( array( 'type' => 'decision' ), array( 'type' => 'motion' ) ), $used ) as $atts ) {
	foreach ( array( null, '1' ) as $all ) {
		if ( $all ) {
			$_GET['tk_all'] = $all;
		} else {
			unset( $_GET['tk_all'] );
		}
		TK_Blocks::documents( $atts );
	}
}
unset( $_GET['tk_all'] );
$requested = array_values( array_unique( TK_Store::$trace ) );
TK_T::eq( $tk_sorted( $paths ), $tk_sorted( $requested ), 'plan: generated paths == paths the renderers request for the same objects' );
TK_T::ok( in_array( TK_Paths::transcript( $hr1, 51 ), $paths, true ) && ! in_array( TK_Paths::transcript( $hr1, 76 ), $paths, true ), 'plan: transcript windows follow page_count' );
TK_T::ok( in_array( TK_Paths::documents_list( 'notice', 20, 'substantive' ), $paths, true ) && in_array( TK_Paths::documents_list( 'notice', 200, 'procedural' ), $paths, true ) && in_array( TK_Paths::documents_list( 'decision', 50, '' ), $paths, true ), 'plan: documents list variants (type × substantive/all, procedural count)' );

// ------------------------------------------------------------------ full sync queue
tk_test_reset_store();
tk_api()->handler = $tk_fixture;
TK_Rest_Proxy::cached_get( TK_Paths::hearing( $hr1 ) );        // present object page: skipped
TK_Rest_Proxy::cached_get( TK_Paths::glossary() );              // present index page: refreshed
TK_Rest_Proxy::cached_get( TK_Paths::hearing( 'hr_' . str_repeat( '9', 26 ) ) ); // no longer published: pruned
TK_Rest_Proxy::cached_get( TK_Paths::transcript( 'hr_' . str_repeat( '9', 26 ), 1 ) );
TK_Rest_Proxy::cached_get( TK_Paths::citation( $su1 ) );        // citations are never pruned
$before                           = count( tk_api()->calls );
$GLOBALS['wpdb']->posts            = 'wp_posts';
$GLOBALS['wpdb']->tables['wp_posts'] = array(
	1 => array( 'ID' => '1', 'post_status' => 'publish', 'post_content' => '<!-- wp:shortcode -->[tk_documents type="notice" limit="20"]<!-- /wp:shortcode -->' ),
	2 => array( 'ID' => '2', 'post_status' => 'draft', 'post_content' => '[tk_documents type="affidavit"]' ),
	3 => array( 'ID' => '3', 'post_status' => 'publish', 'post_content' => 'no shortcode' ),
);
TK_T::eq( array( array( 'type' => 'notice', 'limit' => '20' ) ), TK_Sync::used_document_atts(), 'full: [tk_documents] attributes read from published content' );
$fplan = TK_Sync::plan( $objects, TK_Sync::used_document_atts() );
$st    = TK_Sync::start_full( $objects );
TK_T::ok( 'running' === $st['status'] && count( $fplan ) === $st['total'] && 2 === $st['pruned'], 'full: queued every path, pruned the unpublished hearing' );
TK_T::ok( ! TK_Store::exists( TK_Paths::hearing( 'hr_' . str_repeat( '9', 26 ) ) ) && TK_Store::exists( TK_Paths::citation( $su1 ) ), 'full: prune keeps citations' );
TK_T::ok( false !== wp_next_scheduled( TK_Sync::HOOK_FULL_STEP ), 'full: first step scheduled' );
$st = tk_test_run_cron( TK_Sync::HOOK_FULL_STEP, function () { return TK_Sync::run_full_step( 10 ); } );
TK_T::eq( 10, count( tk_api()->calls ) - $before, 'full: request limit per run' );
TK_T::ok( 'running' === $st['status'] && 10 === $st['position'] && false !== wp_next_scheduled( TK_Sync::HOOK_FULL_STEP ), 'full: progress kept, next step scheduled' );
TK_T::eq( TK_Sync::FULL_BATCH, 30, 'full: default batch is 30 requests' );
TK_T::ok( in_array( TK_Paths::glossary(), array_slice( tk_api()->calls, $before ), true ), 'full: index pages refreshed' );
$guard = 0;
while ( 'running' === TK_Sync::full_status()['status'] && $guard++ < 20 ) {
	tk_test_run_cron( TK_Sync::HOOK_FULL_STEP, array( 'TK_Sync', 'run_full_step' ) );
}
$st = TK_Sync::full_status();
TK_T::ok( 'done' === $st['status'] && $st['position'] === $st['total'] && false === get_option( TK_Sync::OPT_QUEUE ), 'full: finished, queue removed' );
TK_T::eq( 1, $st['skipped'], 'full: stored object page skipped without a request' );
TK_T::ok( 0 === $st['missing'] && 0 === $st['failed'] && TK_Store::exists( TK_Paths::guide_case( '1000' ) ), 'full: unpublished case guide stored as a marker, not an error' );
TK_T::eq( array(), array_values( array_diff( array_map( static function ( $e ) { return substr( $e, 2 ); }, $fplan ), array_map( static function ( $r ) { return $r['path']; }, $GLOBALS['wpdb']->tables['wp_tk_store'] ) ) ), 'full: every planned path is stored' );
TK_T::ok( ! in_array( TK_Paths::hearing( $hr1 ), array_slice( tk_api()->calls, $before ), true ), 'full: present hearing not refetched' );
$GLOBALS['wpdb']->tables['wp_tk_store'] = array();
$GLOBALS['wpdb']->posts                 = '';
TK_Sync::start_full( $objects );
$n             = count( tk_api()->calls );
tk_api()->down = true;
$st            = tk_test_run_cron( TK_Sync::HOOK_FULL_STEP, array( 'TK_Sync', 'run_full_step' ) );
TK_T::ok( 0 === $st['position'] && 1 === count( tk_api()->calls ) - $n && wp_next_scheduled( TK_Sync::HOOK_FULL_STEP ) >= time() + TK_Sync::BACKOFF - 1, 'full: API down → position kept, retried after the back-off' );
TK_Sync::cancel_full();
TK_T::eq( 'cancelled', TK_Sync::full_status()['status'], 'full: cancel' );
$GLOBALS['tk_options'][ TK_Sync::OPT_FULL ] = array( 'status' => 'running', 'started' => time() );
$n = count( tk_api()->calls );
TK_Sync::cron_full();
TK_T::eq( $n, count( tk_api()->calls ), 'full: the daily event does not restart a running sync' );

// ------------------------------------------------------------------ stats, truncate
tk_test_reset_store();
TK_Store::put( TK_Paths::guide(), array( 'a' => 'א' ) );
TK_Store::put( TK_Paths::hearing( $hr1 ), array( 'b' => 1 ) );
TK_Store::mark_stale( array( 'hearing:' . $hr1 ) );
$s = TK_Store::stats();
TK_T::ok( 2 === $s['count'] && 1 === $s['stale'] && $s['bytes'] > 10 && 1 === $s['kinds']['hearing']['count'], 'stats: count, size, stale, by kind' );
TK_Store::truncate();
TK_T::eq( 0, TK_Store::stats()['count'], 'truncate empties the store' );

// ------------------------------------------------------------------ admin status (display strings)
require_once TK_DIR . 'includes/class-permissions.php';
require_once TK_DIR . 'includes/class-admin-store.php';
tk_test_reset_store();
TK_Store::put( TK_Paths::hearing( $hr1 ), array( 'b' => 1 ) );
TK_Store::mark_stale( array( 'hearing:' . $hr1 ) );
update_option( TK_Sync::OPT_CHANGES, array( 'time' => time(), 'ok' => true, 'marked' => 3, 'lists_changed' => true, 'counts' => array( 'hearings' => 2, 'documents' => 1, 'guides' => 0, 'claims' => 0 ) ) );
$as = TK_Admin_Store::status();
TK_T::ok( '1' === $as['count'] && '1' === $as['stale'] && $as['busy'] && false !== strpos( $as['changes'], '2 דיונים' ) && 'דיונים' === $as['kinds'][0]['label'] && false !== strpos( $as['full'], 'טרם רץ' ), 'admin: status strings' );

// ------------------------------------------------------------------ uninstall drops the tables
if ( ! function_exists( 'get_role' ) ) {
	function get_role( $r ) { return null; }
}
define( 'WP_UNINSTALL_PLUGIN', 'trial-knowledge/trial-knowledge.php' );
$GLOBALS['tk_cron'][ TK_Sync::HOOK_CHANGES ] = time();
update_option( TK_Sync::OPT_SINCE, 'x' );
require TK_DIR . 'uninstall.php';
TK_T::ok( ! isset( $GLOBALS['wpdb']->tables['wp_tk_store'] ) && ! isset( $GLOBALS['wpdb']->tables['wp_tk_store_tags'] ), 'uninstall: both tables dropped' );
TK_T::ok( false === wp_next_scheduled( TK_Sync::HOOK_CHANGES ) && false === get_option( TK_Sync::OPT_SINCE ), 'uninstall: schedules and sync options removed' );
$GLOBALS['wpdb']->reset();
