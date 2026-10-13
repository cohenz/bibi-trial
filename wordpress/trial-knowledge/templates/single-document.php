<?php
/**
 * Document page (decision, motion, response, notice, affidavit …): the brief when published (2.4: title,
 * summary with citations, procedural note, hearing-day box), metadata and the full text page by page.
 * Without a brief the page shows the archive title, as before.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
$tk_cur        = TK_Public_Pages::$current;
$tk_brief_html = '';
if ( $tk_cur && $tk_cur['data'] && ! empty( $tk_cur['data']['document']['brief'] ) && is_array( $tk_cur['data']['document']['brief'] ) ) {
	$tk_b          = $tk_cur['data']['document']['brief'];
	$tk_slugs      = ! empty( $tk_b['hearing_days'] ) ? TK_Guides::slug_map( TK_Guides::witnesses() ) : array();
	$tk_brief_html = TK_Render_Guides::document_brief( $tk_cur['data']['document'], $tk_slugs );
	if ( $tk_brief_html ) {
		TK_Guides::enqueue_glossary();
	}
}
get_header();
?>
<main id="primary" class="site-main tk-page tk-page--document" dir="rtl">
	<?php
	if ( $tk_cur && $tk_cur['data'] ) :
		$tk_d   = $tk_cur['data'];
		$tk_doc = $tk_d['document'];
		echo TK_Render_Nav::bar( 'documents', array( array( __( 'מסמכים', 'trial-knowledge' ), TK_Public_Pages::section_url( 'documents' ) ), array( TK_Render::display_title( $tk_doc ), '' ) ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
		?>
		<p class="tk-kicker"><span class="tk-badge"><?php echo esc_html( TK_Render::type_label( $tk_doc['source_type'] ) ); ?></span>
			<?php if ( ! empty( $tk_doc['document_date'] ) ) : ?>
				<time datetime="<?php echo esc_attr( substr( $tk_doc['document_date'], 0, 10 ) ); ?>"><?php echo esc_html( TK_Render_Guides::fmt_date( $tk_doc['document_date'] ) ); ?></time>
			<?php endif; ?>
		</p>
		<?php
		if ( $tk_brief_html ) {
			echo $tk_brief_html; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
		} else {
			echo '<h1>' . esc_html( $tk_doc['title'] ) . '</h1>';
		}
		?>
		<p class="tk-muted tk-doc-meta"><?php echo esc_html( $tk_doc['source_owner'] ); ?>
			· <?php echo esc_html( TK_Render::RECORD[ $tk_doc['court_record_status'] ] ?? '' ); ?>
			· SHA-256 <code><?php echo esc_html( substr( $tk_doc['content_sha256'], 0, 16 ) ); ?>…</code></p>
		<?php if ( ! empty( $tk_doc['synthetic_lines'] ) ) : ?>
			<p class="tk-muted"><?php esc_html_e( 'במסמך זה אין מספור שורות מודפס; מספרי השורות חושבו בקליטה.', 'trial-knowledge' ); ?></p>
		<?php endif; ?>
		<?php if ( ! empty( $tk_doc['hearing_id'] ) ) : ?>
			<p><a class="tk-button" href="<?php echo esc_url( TK_Public_Pages::url( 'hearing', $tk_doc['hearing_id'] ) ); ?>"><?php esc_html_e( 'לדף הדיון', 'trial-knowledge' ); ?></a></p>
		<?php endif; ?>
		<?php if ( $tk_brief_html ) : ?>
			<h2 class="tk-sub tk-doc-full"><?php esc_html_e( 'המסמך המלא', 'trial-knowledge' ); ?></h2>
		<?php endif; ?>
		<?php echo TK_Render::transcript( $tk_d, TK_Public_Pages::url( 'document', $tk_doc['source_version_id'] ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php else : ?>
		<?php echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
	<?php endif; ?>
</main>
<?php
get_footer();
