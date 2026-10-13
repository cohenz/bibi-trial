<?php
/**
 * Gutenberg blocks (dynamic, server-rendered) and equivalent shortcodes.
 *
 * Blocks: trial-knowledge/claim-card, source-citation, hearing-timeline, ask-the-trial
 * Shortcodes: [tk_claim_card id=""], [tk_citation id=""], [tk_hearing_timeline], [tk_ask],
 *             [tk_documents type="decision" limit="50" procedural="hide|show"],
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
		// 2.4: a hearing day known from a court notice that is newer than the latest transcribed hearing,
		// and the newest substantive documents (both cached; silently skipped on API errors).
		try {
			$opts['latest_day'] = TK_Render_Guides::latest_hearing_day( TK_Guides::timeline(), (string) ( $g['latest_hearing']['hearing_date'] ?? '' ) );
		} catch ( TK_Api_Error $e ) {
			$opts['latest_day'] = null;
		}
		try {
			$ld                  = TK_Rest_Proxy::cached_get( TK_Paths::latest_documents() );
			$opts['latest_docs'] = (array) ( $ld['items'] ?? array() );
		} catch ( TK_Api_Error $e ) {
			$opts['latest_docs'] = array();
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
		return TK_Render_Guides::timeline( $t, $case ? $case : (string) $atts['case'], self::toggle_opts() );
	}

	/** Procedural-documents toggle state and its no-JS links (?tk_all=1). */
	public static function toggle_opts() {
		return array(
			'all'      => self::all_param(),
			'show_url' => add_query_arg( 'tk_all', '1' ),
			'hide_url' => remove_query_arg( 'tk_all' ),
		);
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
	 * Published decisions, motions, notices … newest first, with the brief title and summary (2.4).
	 * Procedural documents are hidden by default; ?tk_all=1 (a plain link, works without JS) shows them.
	 *
	 * @param array $atts type (protocol excluded; decision|motion|response|notice|affidavit|indictment|exhibit|other), limit,
	 *                    procedural (hide|show; default hide).
	 */
	public static function documents( $atts ) {
		$req = self::documents_request( $atts, self::all_param() );
		wp_enqueue_style( 'trial-knowledge' );
		try {
			$d = TK_Rest_Proxy::cached_get( $req['path'] );
		} catch ( TK_Api_Error $e ) {
			return TK_Render::unavailable();
		}
		$opts = array_merge( self::toggle_opts(), array( 'mode' => $req['mode'] ) );
		if ( 'substantive' === $req['mode'] ) {
			$opts['hidden_count'] = self::procedural_count( $req['type'] );
		}
		$labels = array( 'decision' => 'החלטות', 'motion' => 'בקשות', 'response' => 'תגובות', 'notice' => 'הודעות' );
		$bar    = isset( $labels[ $req['type'] ] ) ? TK_Render_Nav::bar( 'documents', array( array( __( 'מסמכים', 'trial-knowledge' ), TK_Public_Pages::section_url( 'documents' ) ), array( $labels[ $req['type'] ], '' ) ) ) : '';
		return $bar . TK_Render::documents( $d, $opts );
	}

	/**
	 * API requests of one [tk_documents] instance (shared with the full sync, so both use the same paths).
	 *
	 * @param array $atts Shortcode attributes.
	 * @param bool  $all  ?tk_all=1 (procedural documents shown).
	 * @return array type, limit, mode (substantive|with_procedural|all), path, procedural_path ('' unless substantive)
	 */
	public static function documents_request( $atts, $all ) {
		$atts  = shortcode_atts( array( 'type' => '', 'limit' => TK_Paths::DOC_LIMIT, 'procedural' => 'hide' ), (array) $atts );
		$type  = preg_replace( '/[^a-z_]/', '', (string) $atts['type'] );
		$limit = max( 1, min( 200, (int) $atts['limit'] ) );
		$mode  = 'show' === $atts['procedural'] ? 'all' : ( $all ? 'with_procedural' : 'substantive' );
		return array(
			'type'            => $type,
			'limit'           => $limit,
			'mode'            => $mode,
			'path'            => TK_Paths::documents_list( $type, $limit, 'substantive' === $mode ? 'substantive' : '' ),
			'procedural_path' => 'substantive' === $mode ? TK_Paths::documents_list( $type, TK_Paths::PROCEDURAL_LIMIT, 'procedural' ) : '',
		);
	}

	/** ?tk_all=1 — show procedural documents too (lists and timeline). */
	public static function all_param() {
		return isset( $_GET['tk_all'] ) && '1' === (string) wp_unslash( $_GET['tk_all'] ); // phpcs:ignore WordPress.Security.NonceVerification.Recommended,WordPress.Security.ValidatedSanitizedInput -- compared to a literal
	}

	/**
	 * Number of procedural documents of a type (one cached request of up to 200 ids); null when unknown.
	 *
	 * @param string $type Source type or ''.
	 */
	public static function procedural_count( $type ) {
		try {
			$p = TK_Rest_Proxy::cached_get( TK_Paths::documents_list( $type, TK_Paths::PROCEDURAL_LIMIT, 'procedural' ) );
		} catch ( TK_Api_Error $e ) {
			return null;
		}
		$n = count( (array) ( $p['items'] ?? array() ) );
		return $n >= TK_Paths::PROCEDURAL_LIMIT ? null : $n;
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
		wp_register_script( 'trial-knowledge-reading', TK_URL . 'assets/reading.js', array(), TK_VERSION, true );
		wp_register_script( 'trial-knowledge-p315', TK_URL . 'assets/p315.js', array(), TK_VERSION, true );
		wp_register_script( 'trial-knowledge-questions', TK_URL . 'assets/questions.js', array(), TK_VERSION, true );
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
			$card = TK_Rest_Proxy::cached_get( TK_Paths::claim( $id ) );
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
			$c = TK_Rest_Proxy::cached_get( TK_Paths::citation( $id ) );
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
		// stored per day (2.5): a future day is "now"; days before the investigations are the first day
		if ( $as_of && $as_of > gmdate( 'Y-m-d' ) ) {
			$as_of = '';
		} elseif ( $as_of && $as_of < '2016-01-01' ) {
			$as_of = '2016-01-01';
		}
		try {
			$t = TK_Rest_Proxy::cached_get( TK_Paths::timeline( $as_of ) );
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
