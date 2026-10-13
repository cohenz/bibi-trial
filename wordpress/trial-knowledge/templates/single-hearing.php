<?php
/**
 * Hearing page: date, witnesses (linked), judges; tabs "בקצרה" (digest),
 * "שאלות ותשובות מרכזיות", "הפרוטוקול המלא" (paged; pager links keep the tab)
 * and "מסמך המקור". Without JS the tabs are anchors and all sections are shown.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
TK_Guides::enqueue_glossary();
TK_Guides::enqueue_tabs();
get_header();
$tk_cur = TK_Public_Pages::$current;
?>
<main id="primary" class="site-main tk-page tk-page--hearing" dir="rtl">
	<?php
	if ( $tk_cur && $tk_cur['data'] ) {
		$tk_h     = $tk_cur['data']['hearing'];
		$tk_slugs = TK_Guides::slug_map( TK_Guides::witnesses() );
		$tk_t     = null;
		try {
			$tk_t = TK_Rest_Proxy::cached_get( TK_Public_Pages::transcript_path( $tk_h['id'] ) );
		} catch ( TK_Api_Error $e ) {
			$tk_t = null;
		}
		echo TK_Render_Guides::hearing_page( // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped in renderer
			$tk_cur['data'],
			array(
				'transcript' => $tk_t,
				'slugs'      => $tk_slugs,
				'exchanges'  => TK_Guides::hearing_exchanges( $tk_h, $tk_slugs ),
				'tab'        => TK_Public_Pages::tab_param(),
				'base_url'   => TK_Public_Pages::url( 'hearing', $tk_h['id'] ),
				'neighbors'  => TK_Guides::hearing_neighbors( $tk_h['id'] ),
			)
		);
	} else {
		echo TK_Render::unavailable(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
	}
	?>
</main>
<?php
get_footer();
