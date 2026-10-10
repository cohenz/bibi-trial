<?php
// Shared vector with tests/unit/test_gates_models_security.py::test_signature_vector_shared_with_wordpress
TK_T::eq(
	"POST\n/v2/admin/ingestion-jobs\na=1&b=2\n1760000000\nnonce-12345678\neditor\n5041bf1f713df204784353e82f6a4a535931cb64f1f4b4a5aeaffcb720918b22",
	TK_Api_Client::canonical( 'POST', '/v2/admin/ingestion-jobs', 'b=2&a=1', '1760000000', 'nonce-12345678', 'editor', '{"x":1}' ),
	'canonical string matches Python'
);
TK_T::eq(
	'15b573dc9927a7fbc96c8ddd66580402d1227f3a6f834203b627f30b01d32ddd',
	TK_Api_Client::sign( 'test-secret', 'POST', '/v2/admin/ingestion-jobs', 'b=2&a=1', '1760000000', 'nonce-12345678', 'editor', '{"x":1}' ),
	'signature matches Python'
);
TK_T::eq( "GET\n/v2/x\nlimit=50&q=a+b\n1\nn\na\n" . hash( 'sha256', '' ), TK_Api_Client::canonical( 'GET', '/v2/x', 'q=a%20b&limit=50', '1', 'n', 'a', '' ), 'query encoding like urlencode(quote_plus)' );
