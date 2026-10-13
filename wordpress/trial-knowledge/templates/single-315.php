<?php
/**
 * "315 האירועים" (/{slug}/315/): Project 315's check of the coverage events in the Case 4000
 * indictment appendix, summarized, with links to the project's site (2.6).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
TK_Guides::enqueue_glossary();
get_header();
?>
<main id="primary" class="site-main tk-page tk-page--p315" dir="rtl">
	<?php echo TK_Render_Nav::bar( 'cases', array( array( __( 'תיק 4000', 'trial-knowledge' ), TK_Public_Pages::url( 'case', '4000' ) ), array( __( '315 האירועים', 'trial-knowledge' ), '' ) ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer ?>
	<?php echo TK_P315::page(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer ?>
</main>
<?php
get_footer();
