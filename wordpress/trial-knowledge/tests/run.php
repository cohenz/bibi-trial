<?php
/**
 * php tests/run.php — runs all tests/test-*.php files.
 */
require __DIR__ . '/bootstrap.php';
foreach ( glob( __DIR__ . '/test-*.php' ) as $f ) {
	require $f;
}
echo 'passed: ' . TK_T::$pass . ', failed: ' . count( TK_T::$fail ) . "\n";
foreach ( TK_T::$fail as $m ) {
	echo "FAIL: $m\n";
}
exit( TK_T::$fail ? 1 : 0 );
