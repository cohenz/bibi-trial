<?php
/**
 * All witnesses (/{slug}/witnesses/).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
TK_Render::enqueue_reading();
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--witnesses" dir="rtl">
	<?php echo TK_Render_Nav::bar( 'witnesses', array( array( __( 'עדים', 'trial-knowledge' ), '' ) ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer ?>
	<header class="tk-head tk-guide"><p class="tk-kicker"><?php esc_html_e( 'המשפט של בנימין נתניהו', 'trial-knowledge' ); ?></p>
		<h1 class="tk-head__title"><?php esc_html_e( 'העדים במשפט', 'trial-knowledge' ); ?></h1>
		<p class="tk-muted"><?php esc_html_e( 'העדים שעדותם מופיעה בפרוטוקולים שפורסמו או בהודעות בית המשפט, לפי שלבי המשפט: קודם עדי התביעה, אחר כך הנאשם ועדי ההגנה. בכל קבוצה — מי שהעיד ימים רבים יותר קודם.', 'trial-knowledge' ); ?></p></header>
	<?php
	if ( $tk_cur && $tk_cur['data'] ) {
		echo TK_Render_Guides::witnesses_grouped( (array) ( $tk_cur['data']['witnesses'] ?? array() ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
	} else {
		echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	}
	?>
</main>
<?php
get_footer();
