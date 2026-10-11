<?php
/**
 * Stable public URLs (spec §18) rendered with the theme:
 *   /{slug}/claim/{uuid}/    claim card       (templates/single-claim.php)
 *   /{slug}/answer/{uuid}/   answer permalink (templates/single-answer.php)
 *   /{slug}/source/{su_id}/  citation         (templates/single-source.php)
 *   /{slug}/hearing/{hr_id}/ hearing: digest + full protocol (templates/single-hearing.php)
 *   /{slug}/document/{sv_id}/ decision, motion, notice … (templates/single-document.php)
 *   /{slug}/case/{1000|2000|4000}/ case guide          (templates/single-case.php)
 *   /{slug}/witness/{w_slug}/ witness page             (templates/single-witness.php)
 *   /{slug}/timeline/         dual zoomable timeline   (templates/single-timeline.php)
 *   /{slug}/witnesses/        all witnesses            (templates/single-witnesses.php)
 *   /{slug}/glossary/         glossary                 (templates/single-glossary.php)
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Public_Pages {

	/** @var array|null data for the current virtual page */
	public static $current = null;

	public static function init() {
		add_action( 'init', array( __CLASS__, 'rewrite' ) );
		add_action( 'init', array( __CLASS__, 'maybe_flush' ), 99 );
		add_filter( 'query_vars', array( __CLASS__, 'vars' ) );
		add_filter( 'template_include', array( __CLASS__, 'template' ) );
		add_filter( 'pre_get_document_title', array( __CLASS__, 'title' ) );
		add_action( 'wp_head', array( __CLASS__, 'head' ), 1 );
	}

	private static function slug() {
		$cfg = TK_Settings_Store::get();
		return trim( sanitize_title( $cfg['public_slug'] ? $cfg['public_slug'] : 'trial' ), '/' );
	}

	public static function rewrite() {
		$s = self::slug();
		add_rewrite_rule( '^' . $s . '/(claim|answer)/([0-9a-fA-F-]{36})/?$', 'index.php?tk_type=$matches[1]&tk_id=$matches[2]', 'top' );
		add_rewrite_rule( '^' . $s . '/source/(su_[0-9a-f]{26})/?$', 'index.php?tk_type=source&tk_id=$matches[1]', 'top' );
		add_rewrite_rule( '^' . $s . '/hearing/(hr_[0-9a-f]{26})/?$', 'index.php?tk_type=hearing&tk_id=$matches[1]', 'top' );
		add_rewrite_rule( '^' . $s . '/document/(sv_[0-9a-f]{26})/?$', 'index.php?tk_type=document&tk_id=$matches[1]', 'top' );
		add_rewrite_rule( '^' . $s . '/case/(1000|2000|4000)/?$', 'index.php?tk_type=case&tk_id=$matches[1]', 'top' );
		add_rewrite_rule( '^' . $s . '/witness/(w_[0-9a-f]{10})/?$', 'index.php?tk_type=witness&tk_id=$matches[1]', 'top' );
		add_rewrite_rule( '^' . $s . '/(timeline|witnesses|glossary)/?$', 'index.php?tk_type=$matches[1]&tk_id=all', 'top' );
	}

	/** Section pages without an id: /{slug}/timeline/, /{slug}/witnesses/, /{slug}/glossary/. */
	public static function section_url( $name ) {
		return home_url( '/' . self::slug() . '/' . $name . '/' );
	}

	/** Canonical URL of the current virtual page. */
	public static function current_url( array $cur ) {
		return 'all' === $cur['id'] ? self::section_url( $cur['type'] ) : self::url( $cur['type'], $cur['id'] );
	}

	/** Hearing tab requested with ?tk_tab= (summary|qa|full|source); a transcript page request opens "full". */
	public static function tab_param() {
		$t = isset( $_GET['tk_tab'] ) ? sanitize_key( wp_unslash( $_GET['tk_tab'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- read-only navigation
		if ( in_array( $t, array( 'summary', 'qa', 'full', 'source' ), true ) ) {
			return $t;
		}
		return isset( $_GET['tk_p'] ) ? 'full' : 'summary'; // phpcs:ignore WordPress.Security.NonceVerification.Recommended
	}

	/** Case filter for the timeline (?tk_case=4000). */
	public static function case_param() {
		$c = isset( $_GET['tk_case'] ) ? preg_replace( '/[^0-9]/', '', (string) wp_unslash( $_GET['tk_case'] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Recommended,WordPress.Security.ValidatedSanitizedInput.InputNotSanitized -- digits only
		return in_array( $c, array( '1000', '2000', '4000' ), true ) ? $c : '';
	}

	/** After a plugin update: new URL patterns and the upgrade routine run without re-activating the plugin. */
	public static function maybe_flush() {
		if ( get_option( 'tk_rewrite_version' ) !== TK_VERSION ) {
			TK_Sync::upgrade(); // 2.5: local-copy tables (dbDelta) and sync schedules
			flush_rewrite_rules();
			update_option( 'tk_rewrite_version', TK_VERSION );
		}
	}

	/** Page number requested for transcripts and documents (?tk_p=). */
	public static function page_param() {
		$p = isset( $_GET['tk_p'] ) ? absint( wp_unslash( $_GET['tk_p'] ) ) : 1; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- read-only navigation
		return max( 1, min( 5000, $p ) );
	}

	public static function activate() {
		self::rewrite();
		flush_rewrite_rules();
	}

	public static function deactivate() {
		flush_rewrite_rules();
	}

	public static function vars( $vars ) {
		$vars[] = 'tk_type';
		$vars[] = 'tk_id';
		return $vars;
	}

	public static function url( $type, $id ) {
		return home_url( '/' . self::slug() . '/' . $type . '/' . rawurlencode( $id ) . '/' );
	}

	private static function load() {
		if ( null !== self::$current ) {
			return self::$current;
		}
		$type = get_query_var( 'tk_type' );
		$id   = get_query_var( 'tk_id' );
		if ( ! $type || ! $id ) {
			return null;
		}
		$guides = array( 'case', 'witness', 'timeline', 'witnesses', 'glossary' );
		if ( in_array( $type, $guides, true ) ) {
			try {
				$data          = self::load_guide( $type, $id );
				self::$current = array( 'type' => $type, 'id' => $id, 'data' => $data, 'error' => null === $data ? 404 : null );
			} catch ( TK_Api_Error $e ) {
				self::$current = array( 'type' => $type, 'id' => $id, 'data' => null, 'error' => $e->status ? $e->status : 503 );
			}
			return self::$current;
		}
		$path = self::request_path( $type, $id );
		if ( '' === $path ) {
			return null;
		}
		try {
			$data          = TK_Rest_Proxy::cached_get( $path );
			self::$current = array( 'type' => $type, 'id' => $id, 'data' => $data, 'error' => null );
		} catch ( TK_Api_Error $e ) {
			self::$current = array( 'type' => $type, 'id' => $id, 'data' => null, 'error' => $e->status ? $e->status : 503 );
		}
		return self::$current;
	}

	/**
	 * API path of a non-guide virtual page (shared with the full sync); '' for unknown types.
	 *
	 * @param string $type claim|answer|source|hearing|document.
	 * @param string $id   Object id.
	 */
	public static function request_path( $type, $id ) {
		switch ( $type ) {
			case 'claim':
				return TK_Paths::claim( $id );
			case 'answer':
				return TK_Paths::answer( $id );
			case 'source':
				return TK_Paths::citation( $id );
			case 'hearing':
				return TK_Paths::hearing( $id );
			case 'document':
				return TK_Paths::document( $id, self::page_param() );
		}
		return '';
	}

	/** Transcript request of the hearing page (the 25-page window containing ?tk_p=). */
	public static function transcript_path( $hearing_id ) {
		return TK_Paths::transcript( $hearing_id, self::page_param() );
	}

	/**
	 * Data of a guide page; null → not found (a case guide that is not published yet).
	 *
	 * @throws TK_Api_Error On API errors.
	 */
	private static function load_guide( $type, $id ) {
		switch ( $type ) {
			case 'case':
				return TK_Guides::case_guide( $id );
			case 'witness':
				try {
					return TK_Guides::witness( $id );
				} catch ( TK_Api_Error $e ) {
					if ( 404 === $e->status ) {
						return null;
					}
					throw $e;
				}
			case 'timeline':
				return TK_Guides::timeline();
			case 'witnesses':
				return TK_Guides::home();
			case 'glossary':
				return TK_Guides::glossary();
		}
		return null;
	}

	public static function template( $template ) {
		$cur = self::load();
		if ( ! $cur ) {
			return $template;
		}
		if ( 404 === $cur['error'] && 'case' === $cur['type'] ) {
			status_header( 404 ); // friendly "guide in preparation" page, still a 404 for crawlers
		} elseif ( 404 === $cur['error'] ) {
			global $wp_query;
			$wp_query->set_404();
			status_header( 404 );
			return get_404_template();
		}
		wp_enqueue_style( 'trial-knowledge' );
		$file = TK_DIR . 'templates/single-' . $cur['type'] . '.php';
		$over = locate_template( array( 'trial-knowledge/single-' . $cur['type'] . '.php' ) ); // theme override.
		return $over ? $over : $file;
	}

	public static function title( $title ) {
		$cur = self::load();
		if ( ! $cur || ! $cur['data'] ) {
			return $title;
		}
		$d = $cur['data'];
		switch ( $cur['type'] ) {
			case 'claim':
				return $d['bundle']['question'] . ' | ' . get_bloginfo( 'name' );
			case 'answer':
				return $d['question'] . ' | ' . get_bloginfo( 'name' );
			case 'source':
				return sprintf( '%s — עמ׳ %d | %s', $d['document']['title'], $d['citation']['page'], get_bloginfo( 'name' ) );
			case 'hearing':
				return sprintf( 'דיון %s | %s', $d['hearing']['hearing_date'], get_bloginfo( 'name' ) );
			case 'document':
				return TK_Render::display_title( $d['document'] ) . ' | ' . get_bloginfo( 'name' );
			case 'case':
				return trim( ( $d['title'] ?? '' ) . ( ! empty( $d['subtitle'] ) ? ' — ' . $d['subtitle'] : '' ) ) . ' | ' . get_bloginfo( 'name' );
			case 'witness':
				return $d['name'] . ' — עדות במשפט | ' . get_bloginfo( 'name' );
			case 'timeline':
				return 'ציר הזמן של המשפט | ' . get_bloginfo( 'name' );
			case 'witnesses':
				return 'העדים במשפט | ' . get_bloginfo( 'name' );
			case 'glossary':
				return 'מילון מונחים | ' . get_bloginfo( 'name' );
		}
		return $title;
	}

	public static function head() {
		$cur = self::load();
		if ( ! $cur || ! $cur['data'] ) {
			return;
		}
		$d    = $cur['data'];
		$desc = '';
		$ld   = null;
		if ( 'claim' === $cur['type'] ) {
			$b    = $d['bundle'];
			$desc = $b['answer_short'] ?? '';
			$ld   = array(
				'@context'     => 'https://schema.org',
				'@type'        => 'Article',
				'headline'     => $b['question'],
				'description'  => $desc,
				'dateModified' => $b['as_of'],
				'inLanguage'   => 'he',
				'citation'     => array_map(
					static function ( $c ) {
						return TK_Public_Pages::url( 'source', $c['source_unit_id'] );
					},
					array_slice( $b['citations'], 0, 20 )
				),
			);
		} elseif ( 'answer' === $cur['type'] ) {
			$desc = $d['answer_short'];
			if ( 'answered' !== $d['answer_status'] ) {
				echo '<meta name="robots" content="noindex">' . "\n"; // thin/negative answers are not indexed (spec §18)
			}
		} elseif ( 'source' === $cur['type'] ) {
			$desc = wp_trim_words( $d['text'], 30 );
		} elseif ( 'case' === $cur['type'] ) {
			$one  = TK_Render_Guides::block( $d, 'one_line' );
			$desc = $one ? $one[0]['text'] : '';
		} elseif ( 'witness' === $cur['type'] && ! empty( $d['hearings'][0]['digest_sentences'][0]['text'] ) ) {
			$desc = $d['hearings'][0]['digest_sentences'][0]['text'];
		} elseif ( 'witness' === $cur['type'] && ! empty( $d['appearances'][0]['description'] ) ) {
			$desc = $d['appearances'][0]['description'];
		} elseif ( 'document' === $cur['type'] && ! empty( $d['document']['brief']['summary'] ) && is_string( $d['document']['brief']['summary'] ) ) {
			$desc = $d['document']['brief']['summary'];
		}
		echo '<link rel="canonical" href="' . esc_url( self::current_url( $cur ) ) . '">' . "\n";
		if ( $desc ) {
			echo '<meta name="description" content="' . esc_attr( wp_trim_words( $desc, 40 ) ) . '">' . "\n";
		}
		if ( $ld ) {
			echo '<script type="application/ld+json">' . wp_json_encode( $ld, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ) . '</script>' . "\n";
		}
	}
}
