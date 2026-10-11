<?php
/**
 * Gutenberg blocks (dynamic, server-rendered) and equivalent shortcodes.
 *
 * Blocks: trial-knowledge/claim-card, source-citation, hearing-timeline, ask-the-trial
 * Shortcodes: [tk_claim_card id=""], [tk_citation id=""], [tk_hearing_timeline], [tk_ask],
 *             [tk_documents type="decision" limit="50"],
 *             2.3 entry points: [tk_start], [tk_timeline case=""], [tk_witnesses], [tk_glossary]
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Blocks {

	public static function init() {
		add_action( 'init', array( __CLASS__, 'register' ) );
		add_action( 'init', array( __CLASS__, 'register_assets' ) );
		add_action( 'wp_enqueue_scripts', array( __CLASS__, 'assets' ) );
		add_shortcode( 'tk_claim_card', array( __CLASS__, 'claim_card' ) );
		add_shortcode( 'tk_citation', array( __CLASS__, 'citation' ) );
		add_shortcode( 'tk_hearing_timeline', array( __CLASS__, 'timeline' ) );
		add_shortcode( 'tk_ask', array( __CLASS__, 'ask' ) );
		add_shortcode( 'tk_documents', array( __CLASS__, 'documents' ) );
		add_shortcode( 'tk_start', array( __CLASS__, 'start' ) );
		add_shortcode( 'tk_timeline', array( __CLASS__, 'guide_timeline' ) );
		add_shortcode( 'tk_witnesses', array( __CLASS__, 'witnesses' ) );
		add_shortcode( 'tk_glossary', array( __CLASS__, 'glossary' ) );
	}

	/**
	 * [tk_start] — the "מתחילים כאן" home: cases, indictment, where the trial stands,
	 * witnesses, entry links and Ask. Optional URL overrides: glossary, timeline,
	 * witnesses, decisions, motions, responses, notices; ask="0" hides the Ask box.
	 */
	public static function start( $atts ) {
		$atts = shortcode_atts(
			array( 'glossary' => '', 'timeline' => '', 'witnesses' => '', 'decisions' => '', 'motions' => '', 'responses' => '', 'notices' => '', 'ask' => '1' ),
			(array) $atts
		);
		wp_enqueue_style( 'trial-knowledge' );
		try {
			$g = TK_Guides::home();
		} catch ( TK_Api_Error $e ) {
			return TK_Render::unavailable();
		}
		TK_Guides::enqueue_glossary();
		$opts = array( 'docs' => array() );
		foreach ( array( 'glossary', 'timeline', 'witnesses' ) as $k ) {
			if ( $atts[ $k ] ) {
				$opts[ $k ] = esc_url_raw( $atts[ $k ] );
			}
		}
		foreach ( array( 'decisions' => 'decision', 'motions' => 'motion', 'responses' => 'response', 'notices' => 'notice' ) as $k => $t ) {
			if ( $atts[ $k ] ) {
				$opts['docs'][ $t ] = esc_url_raw( $atts[ $k ] );
			}
		}
		if ( '0' !== (string) $atts['ask'] ) {
			wp_enqueue_script( 'trial-knowledge-ask' );
			$opts['ask_html'] = TK_Render::ask_form();
		}
		return TK_Render_Guides::start( $g, $opts );
	}

	/** [tk_timeline case="4000"] — dual-track zoomable timeline; ?tk_case= overrides the attribute. */
	public static function guide_timeline( $atts ) {
		$atts = shortcode_atts( array( 'case' => '' ), (array) $atts );
		wp_enqueue_style( 'trial-knowledge' );
		try {
			$t = TK_Guides::timeline();
		} catch ( TK_Api_Error $e ) {
			return TK_Render::unavailable();
		}
		TK_Guides::enqueue_timeline();
		$case = TK_Public_Pages::case_param();
		return TK_Render_Guides::timeline( $t, $case ? $case : (string) $atts['case'] );
	}

	public static function witnesses( $atts ) {
		wp_enqueue_style( 'trial-knowledge' );
		try {
			$g = TK_Guides::home();
		} catch ( TK_Api_Error $e ) {
			return TK_Render::unavailable();
		}
		return TK_Render_Guides::witnesses_list( (array) ( $g['witnesses'] ?? array() ) );
	}

	public static function glossary( $atts ) {
		wp_enqueue_style( 'trial-knowledge' );
		try {
			$gl = TK_Guides::glossary();
		} catch ( TK_Api_Error $e ) {
			return TK_Render::unavailable();
		}
		return TK_Render_Guides::glossary( $gl );
	}

	/**
	 * Published decisions, motions, notices … newest first.
	 *
	 * @param array $atts type (protocol excluded; decision|motion|response|notice|affidavit|indictment|exhibit|other), limit.
	 */
	public static function documents( $atts ) {
		$atts  = shortcode_atts( array( 'type' => '', 'limit' => 50 ), (array) $atts );
		$type  = preg_replace( '/[^a-z_]/', '', (string) $atts['type'] );
		$limit = max( 1, min( 200, (int) $atts['limit'] ) );
		wp_enqueue_style( 'trial-knowledge' );
		$path = '/v2/documents?limit=' . $limit . ( $type ? '&type=' . $type : '' );
		try {
			$d = TK_Rest_Proxy::cached_get( $path, array( 'lists' ) );
		} catch ( TK_Api_Error $e ) {
			return TK_Render::unavailable();
		}
		return TK_Render::documents( $d );
	}

	public static function register() {
		$map = array(
			'claim-card'       => 'claim_card',
			'source-citation'  => 'citation',
			'hearing-timeline' => 'timeline',
			'ask-the-trial'    => 'ask',
		);
		foreach ( $map as $dir => $cb ) {
			$path = TK_DIR . 'build/blocks/' . $dir;
			if ( ! file_exists( $path . '/block.json' ) ) {
				$path = TK_DIR . 'blocks/' . $dir; // unbuilt fallback (no editor script)
			}
			register_block_type( $path, array( 'render_callback' => array( __CLASS__, $cb ) ) );
		}
	}

	/** Registered on init so that templates and shortcodes can enqueue them (and add inline data) at any point. */
	public static function register_assets() {
		wp_register_style( 'trial-knowledge', TK_URL . 'assets/trial-knowledge.css', array(), TK_VERSION );
		wp_register_script( 'trial-knowledge-ask', TK_URL . 'assets/ask.js', array(), TK_VERSION, true );
		wp_register_script( 'trial-knowledge-glossary', TK_URL . 'assets/glossary.js', array(), TK_VERSION, true );
		wp_register_script( 'trial-knowledge-timeline', TK_URL . 'assets/timeline.js', array(), TK_VERSION, true );
		wp_register_script( 'trial-knowledge-tabs', TK_URL . 'assets/tabs.js', array(), TK_VERSION, true );
	}

	public static function assets() {
		wp_enqueue_style( 'trial-knowledge' );
	}

	/**
	 * @param array $atts Attributes: id (claim UUID), headingLevel.
	 */
	public static function claim_card( $atts ) {
		$atts = shortcode_atts( array( 'id' => '', 'claimId' => '', 'headingLevel' => 2 ), (array) $atts );
		$id   = $atts['claimId'] ? $atts['claimId'] : $atts['id'];
		if ( ! preg_match( '/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i', (string) $id ) ) {
			return current_user_can( 'edit_posts' ) ? TK_Render::error_box( __( 'יש לבחור טענה (מזהה UUID).', 'trial-knowledge' ) ) : '';
		}
		wp_enqueue_style( 'trial-knowledge' );
		try {
			$card = TK_Rest_Proxy::cached_get( '/v2/claims/' . strtolower( $id ), array( 'claim:' . strtolower( $id ), 'claims' ) );
		} catch ( TK_Api_Error $e ) {
			return 404 === $e->status ? ( current_user_can( 'edit_posts' ) ? TK_Render::error_box( __( 'הטענה טרם פורסמה.', 'trial-knowledge' ) ) : '' ) : TK_Render::unavailable();
		}
		return TK_Render::claim_card( $card, array( 'heading_level' => (int) $atts['headingLevel'] ) );
	}

	public static function citation( $atts ) {
		$atts = shortcode_atts( array( 'id' => '', 'sourceUnitId' => '' ), (array) $atts );
		$id   = $atts['sourceUnitId'] ? $atts['sourceUnitId'] : $atts['id'];
		if ( ! preg_match( '/^su_[0-9a-f]{26}$/', (string) $id ) ) {
			return current_user_can( 'edit_posts' ) ? TK_Render::error_box( __( 'מזהה ציטוט לא תקין.', 'trial-knowledge' ) ) : '';
		}
		wp_enqueue_style( 'trial-knowledge' );
		try {
			$c = TK_Rest_Proxy::cached_get( '/v2/citations/' . $id, array( 'citations', 'citation:' . $id ) );
		} catch ( TK_Api_Error $e ) {
			return 404 === $e->status ? '' : TK_Render::unavailable();
		}
		return TK_Render::citation( $c );
	}

	public static function timeline( $atts ) {
		wp_enqueue_style( 'trial-knowledge' );
		$as_of = isset( $_GET['tk_as_of'] ) ? sanitize_text_field( wp_unslash( $_GET['tk_as_of'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- read-only filter
		if ( $as_of && ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $as_of ) ) {
			$as_of = '';
		}
		$path = '/v2/timeline' . ( $as_of ? '?as_of=' . rawurlencode( $as_of . 'T23:59:59Z' ) : '' );
		try {
			$t = TK_Rest_Proxy::cached_get( $path, array( 'timeline', 'lists' ) );
		} catch ( TK_Api_Error $e ) {
			return TK_Render::unavailable();
		}
		return TK_Render::timeline( $t, $as_of );
	}

	public static function ask( $atts ) {
		wp_enqueue_style( 'trial-knowledge' );
		wp_enqueue_script( 'trial-knowledge-ask' );
		return TK_Render::ask_form( (array) $atts );
	}
}
