<?php
/**
 * Visitors' questions (/{slug}/questions/): the questions the admin approved, collapsed, most opened first (2.7.8).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
get_header();
wp_enqueue_script( 'trial-knowledge-questions' );
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--questions" dir="rtl">
	<?php echo TK_Render_Nav::bar( 'questions', array( array( __( 'שאלות ותשובות', 'trial-knowledge' ), '' ) ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer ?>
	<header class="tk-head tk-guide"><p class="tk-kicker"><?php esc_html_e( 'המשפט של בנימין נתניהו', 'trial-knowledge' ); ?></p>
		<h1 class="tk-head__title"><?php esc_html_e( 'שאלות ותשובות', 'trial-knowledge' ); ?></h1>
		<p class="tk-lead"><?php esc_html_e( 'שאלות שמבקרים שאלו את המאגר, והתשובות שקיבלו — כל קביעה עם ציטוט מהפרוטוקול. השאלות שהכי מעניינות את הקוראים מופיעות למעלה.', 'trial-knowledge' ); ?></p>
		<p><a class="tk-more" href="<?php echo esc_url( home_url( '/' ) . '#tk-ask' ); ?>"><?php esc_html_e( 'יש לכם שאלה אחרת? שאלו את המאגר ←', 'trial-knowledge' ); ?></a></p></header>
	<?php
	if ( $tk_cur && is_array( $tk_cur['data'] ) ) {
		echo TK_Questions::render_public( (array) ( $tk_cur['data']['rows'] ?? array() ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
	} else {
		echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	}
	?>
</main>
<?php
get_footer();
