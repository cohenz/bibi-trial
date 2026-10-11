<?php
/**
 * Witness page (/{slug}/witness/{w_slug}/): who the witness is, the hearings, notable Q/A, all witnesses.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
TK_Guides::enqueue_glossary();
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--witness" dir="rtl">
	<?php
	if ( $tk_cur && $tk_cur['data'] ) {
		echo TK_Render_Guides::witness_page( $tk_cur['data'], TK_Guides::witnesses() ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
	} else {
		echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	}
	?>
</main>
<?php
get_footer();
