<?php
/**
 * Citation page: the exact source unit with page and lines.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--source" dir="rtl">
	<?php if ( $tk_cur && $tk_cur['data'] ) : ?>
		<h1><?php echo esc_html( $tk_cur['data']['document']['title'] ); ?></h1>
		<?php echo TK_Render::citation( $tk_cur['data'] ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php else : ?>
		<?php echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php endif; ?>
</main>
<?php
get_footer();
