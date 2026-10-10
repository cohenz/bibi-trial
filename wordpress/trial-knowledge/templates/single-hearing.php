<?php
/**
 * Hearing page: published digest with citations.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--hearing" dir="rtl">
	<?php
	if ( $tk_cur && $tk_cur['data'] ) :
		$tk_h    = $tk_cur['data']['hearing'];
		$tk_d    = $tk_cur['data']['digest'];
		$tk_cits = array();
		if ( $tk_d ) {
			foreach ( $tk_d['citations'] as $tk_c ) {
				$tk_cits[ $tk_c['source_unit_id'] ] = $tk_c;
			}
		}
		?>
		<h1><?php echo esc_html( sprintf( __( 'דיון מיום %s', 'trial-knowledge' ), $tk_h['hearing_date'] ) ); ?></h1>
		<?php if ( ! empty( $tk_h['witnesses'] ) ) : ?>
			<p><?php echo esc_html( __( 'עדים:', 'trial-knowledge' ) . ' ' . implode( ', ', $tk_h['witnesses'] ) ); ?></p>
		<?php endif; ?>
		<?php if ( $tk_d ) : ?>
			<section class="tk-box"><h2><?php esc_html_e( 'סיכום הדיון', 'trial-knowledge' ); ?></h2><ul>
			<?php foreach ( $tk_d['summary_sentences'] as $tk_s ) : ?>
				<li><?php echo esc_html( $tk_s['text'] ); ?>
				<?php
				foreach ( $tk_s['citation_ids'] as $tk_id ) {
					if ( isset( $tk_cits[ $tk_id ] ) ) {
						echo ' ' . TK_Render::citation_link( $tk_cits[ $tk_id ] ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
					}
				}
				?>
				</li>
			<?php endforeach; ?>
			</ul></section>
		<?php else : ?>
			<p class="tk-muted"><?php esc_html_e( 'טרם פורסם סיכום לדיון זה.', 'trial-knowledge' ); ?></p>
		<?php endif; ?>
	<?php else : ?>
		<?php echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php endif; ?>
</main>
<?php
get_footer();
