<?php
/**
 * Case guide page (/{slug}/case/{key}/): what the indictment alleges, charges, people,
 * the case timeline and related hearings. Friendly "in preparation" page until published.
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
<main id="primary" class="site-main tk-page tk-page--case" dir="rtl">
	<?php
	if ( $tk_cur && $tk_cur['data'] ) {
		echo TK_Render_Guides::case_page( $tk_cur['data'], array( 'slugs' => TK_Guides::slug_map( TK_Guides::witnesses() ) ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
	} elseif ( $tk_cur && 404 === $tk_cur['error'] ) {
		echo TK_Render_Guides::case_pending( $tk_cur['id'] ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	} else {
		echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	}
	?>
</main>
<?php
get_footer();
