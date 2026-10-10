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

// cache: remember, tag purge, generation purge
$calls = 0;
$f     = function () use ( &$calls ) { ++$calls; return array( 'v' => $calls ); };
TK_Cache::remember( '/v2/claims/x', $f, array( 'claim:x' ) );
TK_Cache::remember( '/v2/claims/x', $f, array( 'claim:x' ) );
TK_T::eq( 1, $calls, 'cached second call' );
TK_T::ok( TK_Cache::purge( array( 'claim:x' ) ) >= 1, 'purge by tag' );
TK_Cache::remember( '/v2/claims/x', $f, array( 'claim:x' ) );
TK_T::eq( 2, $calls, 'refetched after purge' );
TK_Cache::purge_all();
TK_Cache::remember( '/v2/claims/x', $f, array( 'claim:x' ) );
TK_T::eq( 3, $calls, 'refetched after generation bump' );

// webhook signature
$body = '{"event":"artifact.published","payload":{"object_type":"claim","object_id":"abc"}}';
$ts   = (string) time();
$sig  = hash_hmac( 'sha256', $ts . '.' . $body, 'whsec' );
TK_T::ok( TK_Webhooks::verify( 'whsec', $ts, $sig, $body ), 'valid webhook accepted' );
TK_T::ok( ! TK_Webhooks::verify( 'whsec', $ts, $sig, $body . ' ' ), 'modified body rejected' );
TK_T::ok( ! TK_Webhooks::verify( 'whsec', (string) ( time() - 3600 ), hash_hmac( 'sha256', ( time() - 3600 ) . '.' . $body, 'whsec' ), $body ), 'stale timestamp rejected' );
TK_T::ok( ! TK_Webhooks::verify( '', $ts, $sig, $body ), 'no secret → reject' );
TK_T::ok( in_array( 'claim:abc', TK_Webhooks::tags_for( json_decode( $body, true ) ), true ), 'purge tags include object' );
