<?php
/**
 * Permanent answer page (historical versions stay available).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--answer" dir="rtl">
	<?php if ( $tk_cur && $tk_cur['data'] ) : ?>
		<h1><?php echo esc_html( $tk_cur['data']['question'] ); ?></h1>
		<?php echo TK_Render::answer( $tk_cur['data'] ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php else : ?>
		<?php echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php endif; ?>
</main>
<?php
get_footer();
