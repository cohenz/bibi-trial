<?php
/**
 * All documents (/{slug}/documents/): decisions, motions, responses, notices … in one list with filters
 * (type, year, words, procedural too) that work as a plain GET form (2.7).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
get_header();
$tk_cur = TK_Public_Pages::$current;
// phpcs:disable WordPress.Security.NonceVerification.Recommended -- read-only filters
$tk_q = array(
	'type' => isset( $_GET['tk_type_f'] ) ? sanitize_key( wp_unslash( $_GET['tk_type_f'] ) ) : '',
	'year' => isset( $_GET['tk_year'] ) ? preg_replace( '/[^0-9]/', '', (string) wp_unslash( $_GET['tk_year'] ) ) : '',
	'q'    => isset( $_GET['tk_q'] ) ? mb_substr( sanitize_text_field( wp_unslash( $_GET['tk_q'] ) ), 0, 80 ) : '',
	'all'  => isset( $_GET['tk_all'] ) && '1' === (string) wp_unslash( $_GET['tk_all'] ), // phpcs:ignore WordPress.Security.ValidatedSanitizedInput -- compared to a literal
	'p'    => isset( $_GET['tk_p'] ) ? absint( wp_unslash( $_GET['tk_p'] ) ) : 1,
);
// phpcs:enable
?>
<main id="primary" class="site-main tk-page tk-page--documents" dir="rtl">
	<?php echo TK_Render_Nav::bar( 'documents', array( array( __( 'מסמכים', 'trial-knowledge' ), '' ) ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer ?>
	<header class="tk-head tk-guide"><p class="tk-kicker"><?php esc_html_e( 'המשפט של בנימין נתניהו', 'trial-knowledge' ); ?></p>
		<h1 class="tk-head__title"><?php esc_html_e( 'מסמכים בתיק', 'trial-knowledge' ); ?></h1>
		<p class="tk-muted"><?php esc_html_e( 'החלטות בית המשפט ובקשות, תגובות והודעות של הצדדים. לכל מסמך תקציר קצר, והמסמך המלא בעמוד שלו.', 'trial-knowledge' ); ?></p></header>
	<?php
	if ( $tk_cur && $tk_cur['data'] ) {
		echo TK_Render_Guides::documents_page( (array) ( $tk_cur['data']['items'] ?? array() ), $tk_q, TK_Public_Pages::section_url( 'documents' ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
	} else {
		echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	}
	?>
</main>
<?php
get_footer();
