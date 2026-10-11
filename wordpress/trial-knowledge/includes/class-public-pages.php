<?php
/**
 * Stable public URLs (spec §18) rendered with the theme:
 *   /{slug}/claim/{uuid}/    claim card       (templates/single-claim.php)
 *   /{slug}/answer/{uuid}/   answer permalink (templates/single-answer.php)
 *   /{slug}/source/{su_id}/  citation         (templates/single-source.php)
 *   /{slug}/hearing/{hr_id}/ hearing: digest + full protocol (templates/single-hearing.php)
 *   /{slug}/document/{sv_id}/ decision, motion, notice … (templates/single-document.php)
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
	}

	/** New URL patterns after a plugin update take effect without re-activating the plugin. */
	public static function maybe_flush() {
		if ( get_option( 'tk_rewrite_version' ) !== TK_VERSION ) {
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
		$paths = array(
			'claim'   => array( '/v2/claims/' . strtolower( $id ), array( 'claim:' . strtolower( $id ) ) ),
			'answer'  => array( '/v2/answers/' . strtolower( $id ), array( 'answer:' . strtolower( $id ) ) ),
			'source'  => array( '/v2/citations/' . $id, array( 'citations' ) ),
			'hearing'  => array( '/v2/hearings/' . $id, array( 'hearing:' . $id ) ),
			'document' => array( '/v2/documents/' . $id . '?page_from=' . self::page_param(), array( 'document:' . $id, 'lists' ) ),
		);
		if ( ! isset( $paths[ $type ] ) ) {
			return null;
		}
		try {
			$data          = TK_Rest_Proxy::cached_get( $paths[ $type ][0], $paths[ $type ][1] );
			self::$current = array( 'type' => $type, 'id' => $id, 'data' => $data, 'error' => null );
		} catch ( TK_Api_Error $e ) {
			self::$current = array( 'type' => $type, 'id' => $id, 'data' => null, 'error' => $e->status ? $e->status : 503 );
		}
		return self::$current;
	}

	public static function template( $template ) {
		$cur = self::load();
		if ( ! $cur ) {
			return $template;
		}
		if ( 404 === $cur['error'] ) {
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
				return $d['document']['title'] . ' | ' . get_bloginfo( 'name' );
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
		}
		echo '<link rel="canonical" href="' . esc_url( self::url( $cur['type'], $cur['id'] ) ) . '">' . "\n";
		if ( $desc ) {
			echo '<meta name="description" content="' . esc_attr( wp_trim_words( $desc, 40 ) ) . '">' . "\n";
		}
		if ( $ld ) {
			echo '<script type="application/ld+json">' . wp_json_encode( $ld, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ) . '</script>' . "\n";
		}
	}
}
