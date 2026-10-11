<?php
// secret encryption round trip; ciphertext differs per call; tamper fails
$enc = TK_Settings_Store::encrypt( 's3cr3t-value' );
TK_T::ok( 0 === strpos( $enc, 'v1:' ) && false === strpos( $enc, 's3cr3t' ), 'secret stored encrypted' );
TK_T::eq( 's3cr3t-value', TK_Settings_Store::decrypt( $enc ), 'decrypt round trip' );
TK_T::ok( $enc !== TK_Settings_Store::encrypt( 's3cr3t-value' ), 'random IV' );
TK_T::eq( '', TK_Settings_Store::decrypt( substr( $enc, 0, -2 ) . 'AA' ), 'tampered ciphertext rejected' );
TK_Settings_Store::save( array( 'api_base' => 'https://api.test', 'key_id' => 'wp', 'secret' => 'abc' ) );
$cfg = TK_Settings_Store::get();
TK_T::eq( 'abc', $cfg['secret'], 'secret available server-side' );
TK_T::ok( ! isset( get_option( TK_OPTION )['secret'] ), 'plain secret never stored' );

// local copy (2.5): remember, tag purge marks stale (still served), background refresh, purge_all
tk_test_reset_store();
$calls = 0;
$f     = function () use ( &$calls ) { ++$calls; return array( 'v' => $calls ); };
TK_Cache::remember( '/v2/claims/x', $f, array( 'claim:x' ) );
TK_Cache::remember( '/v2/claims/x', $f, array( 'claim:x' ) );
TK_T::eq( 1, $calls, 'stored: second call served locally' );
TK_T::ok( TK_Cache::purge( array( 'claim:x' ) ) >= 1, 'purge by tag marks the row stale' );
TK_T::eq( array( 'v' => 1 ), TK_Cache::remember( '/v2/claims/x', $f, array( 'claim:x' ) ), 'stale row still served (no inline refetch)' );
TK_T::eq( 1, $calls, 'no API call on a page view after purge' );
TK_T::ok( false !== wp_next_scheduled( TK_Sync::HOOK_REFRESH ), 'purge schedules the background refresh' );
tk_test_run_cron( TK_Sync::HOOK_REFRESH, array( 'TK_Sync', 'run_refresh' ) );
TK_T::eq( array( '/v2/claims/x' ), tk_api()->calls, 'refresh refetched the stale row' );
TK_T::eq( '/v2/claims/x', TK_Cache::remember( '/v2/claims/x', $f )['path'] ?? '', 'refreshed copy served' );
TK_Cache::purge_all();
TK_T::eq( 1, TK_Store::stats()['stale'], 'purge_all marks everything stale' );

// webhook signature
$body = '{"event":"artifact.published","payload":{"object_type":"claim","object_id":"abc"}}';
$ts   = (string) time();
$sig  = hash_hmac( 'sha256', $ts . '.' . $body, 'whsec' );
TK_T::ok( TK_Webhooks::verify( 'whsec', $ts, $sig, $body ), 'valid webhook accepted' );
TK_T::ok( ! TK_Webhooks::verify( 'whsec', $ts, $sig, $body . ' ' ), 'modified body rejected' );
TK_T::ok( ! TK_Webhooks::verify( 'whsec', (string) ( time() - 3600 ), hash_hmac( 'sha256', ( time() - 3600 ) . '.' . $body, 'whsec' ), $body ), 'stale timestamp rejected' );
TK_T::ok( ! TK_Webhooks::verify( '', $ts, $sig, $body ), 'no secret → reject' );
TK_T::ok( in_array( 'claim:abc', TK_Webhooks::tags_for( json_decode( $body, true ) ), true ), 'purge tags include object' );
