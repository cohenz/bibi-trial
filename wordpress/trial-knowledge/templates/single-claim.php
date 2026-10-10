<?php
/**
 * Claim card page. Override in theme: trial-knowledge/single-claim.php
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--claim" dir="rtl">
	<?php
	if ( $tk_cur && $tk_cur['data'] ) {
		echo TK_Render::claim_card( $tk_cur['data'], array( 'heading_level' => 1 ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
		echo '<p class="tk-muted">' . esc_html( sprintf( __( 'פורסם: %s', 'trial-knowledge' ), substr( (string) $tk_cur['data']['published_at'], 0, 10 ) ) ) . '</p>';
	} else {
		echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	}
	?>
</main>
<?php
get_footer();
