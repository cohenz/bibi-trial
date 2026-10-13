<?php
/**
 * Glossary (/{slug}/glossary/), one anchor per term: #term-{id}.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--glossary" dir="rtl">
	<?php echo TK_Render_Nav::bar( 'glossary', array( array( __( 'מילון', 'trial-knowledge' ), '' ) ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer ?>
	<header class="tk-head tk-guide"><p class="tk-kicker"><?php esc_html_e( 'המשפט של בנימין נתניהו', 'trial-knowledge' ); ?></p>
		<h1 class="tk-head__title"><?php esc_html_e( 'מילון מונחים', 'trial-knowledge' ); ?></h1></header>
	<?php
	if ( $tk_cur && $tk_cur['data'] ) {
		echo TK_Render_Guides::glossary( $tk_cur['data'] ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
	} else {
		echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	}
	?>
</main>
<?php
get_footer();
