<?php
/**
 * Document page (decision, motion, response, notice, affidavit …): metadata and the full text page by page.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--document" dir="rtl">
	<?php
	if ( $tk_cur && $tk_cur['data'] ) :
		$tk_d   = $tk_cur['data'];
		$tk_doc = $tk_d['document'];
		?>
		<p class="tk-kicker"><span class="tk-badge"><?php echo esc_html( TK_Render::type_label( $tk_doc['source_type'] ) ); ?></span>
			<?php if ( ! empty( $tk_doc['document_date'] ) ) : ?>
				<time datetime="<?php echo esc_attr( $tk_doc['document_date'] ); ?>"><?php echo esc_html( $tk_doc['document_date'] ); ?></time>
			<?php endif; ?>
		</p>
		<h1><?php echo esc_html( $tk_doc['title'] ); ?></h1>
		<p class="tk-muted"><?php echo esc_html( $tk_doc['source_owner'] ); ?>
			· <?php echo esc_html( TK_Render::RECORD[ $tk_doc['court_record_status'] ] ?? '' ); ?>
			· SHA-256 <code><?php echo esc_html( substr( $tk_doc['content_sha256'], 0, 16 ) ); ?>…</code></p>
		<?php if ( ! empty( $tk_doc['synthetic_lines'] ) ) : ?>
			<p class="tk-muted"><?php esc_html_e( 'במסמך זה אין מספור שורות מודפס; מספרי השורות חושבו בקליטה.', 'trial-knowledge' ); ?></p>
		<?php endif; ?>
		<?php if ( ! empty( $tk_doc['hearing_id'] ) ) : ?>
			<p><a class="tk-button" href="<?php echo esc_url( TK_Public_Pages::url( 'hearing', $tk_doc['hearing_id'] ) ); ?>"><?php esc_html_e( 'לדף הדיון', 'trial-knowledge' ); ?></a></p>
		<?php endif; ?>
		<?php echo TK_Render::transcript( $tk_d, TK_Public_Pages::url( 'document', $tk_doc['source_version_id'] ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php else : ?>
		<?php echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php endif; ?>
</main>
<?php
get_footer();
