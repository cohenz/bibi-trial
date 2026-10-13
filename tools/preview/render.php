<?php
require '/home/claude/bibi-trial/wordpress/trial-knowledge/tests/bootstrap.php';
$P = __DIR__;
$css = file_get_contents( '/home/claude/bibi-trial/wordpress/trial-knowledge/assets/trial-knowledge.css' );
$A = '/home/claude/bibi-trial/wordpress/trial-knowledge/assets/';
$js  = '';
foreach ( array( 'reading.js', 'ask.js', 'timeline.js', 'glossary.js' ) as $f ) { if ( file_exists( $A . $f ) ) { $js .= file_get_contents( $A . $f ) . ";\n"; } }
// the live theme (Astra) styles buttons and links globally; the plugin must hold its own against them
$theme = 'a{color:#737880}a:hover,a:focus{color:#65696F}button,.button,input[type=submit]{border-style:solid;border-width:0;color:#fff;border-color:#737880;background-color:#737880;padding:15px 30px;font-weight:500;line-height:1em}button:focus,button:hover,.button:hover,.button:focus{color:#fff;background-color:#65696F;border-color:#65696F}';
// on the live site the theme's stylesheets load AFTER the plugin's, so equal-specificity theme rules win
$css = $css . $theme;
function page( $name, $body, $css, $js ) {
	file_put_contents( __DIR__ . "/$name.html", '<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial,sans-serif;margin:0;padding:16px;max-width:1100px;margin-inline:auto;color:#1d2731} ' . $css . '</style></head><body class="tk-page">' . $body . '<script>' . $js . '</script></body></html>' );
}
$g  = json_decode( file_get_contents( "$P/guide.json" ), true );
$ws = $g['witnesses'];
page( 'start', TK_Render_Guides::start( $g, array( 'ask_html' => TK_Render::ask_form() ) ), $css, $js );
page( 'witnesses', TK_Render_Nav::bar( 'witnesses', array( array( 'עדים', '' ) ) ) . '<h1>העדים במשפט</h1>' . TK_Render_Guides::witnesses_grouped( $ws ), $css, $js );
TK_Guides::slug_map( $ws );
page( 'witness', TK_Render_Guides::witness_page( json_decode( file_get_contents( "$P/w_yeshua.json" ), true ), $ws ), $css, $js );
page( 'documents', TK_Render_Nav::bar( 'documents', array( array( 'מסמכים', '' ) ) ) . '<h1>מסמכים בתיק</h1>' . TK_Render_Guides::documents_page( ( function ( $d ) { return $d["items"] ?? $d; } )( json_decode( file_get_contents( "$P/docs.json" ), true ) ), array(), 'https://site.test/trial/documents/' ), $css, $js );
$t  = json_decode( file_get_contents( "$P/timeline.json" ), true );
$h  = json_decode( file_get_contents( "$P/hearing.json" ), true );
page( 'hearing', TK_Render_Guides::hearing_page( $h, array( 'slugs' => TK_Guides::slug_map( $ws ), 'neighbors' => TK_Guides::neighbors_in( $t['events'], $h['hearing']['id'] ) ) ), $css, $js );
page( 'glossary', TK_Render_Guides::glossary( json_decode( file_get_contents( "$P/glossary.json" ), true ) ), $css, $js );
page( 'timeline', TK_Render_Guides::timeline( $t ), $css, $js );
if ( file_exists( "$P/ask_after.json" ) ) {
$ans = json_decode( file_get_contents( "$P/ask_after.json" ), true );
page( 'ask', TK_Render::ask_form() . '<div>' . TK_Render::answer( $ans[1] ) . TK_Render::answer( $ans[0] ) . '</div>', $css, $js );
}
echo "rendered\n";
