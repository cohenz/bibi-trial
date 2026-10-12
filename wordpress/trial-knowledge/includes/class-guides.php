<?php
/**
 * Reader guides (2.3): cached reads of the public guide API and small helpers
 * shared by the entry-point pages (start page, case, witness, timeline, glossary).
 *
 *   GET /v2/guide                   start page data (cases, indictment, witnesses, latest hearing, counts)
 *   GET /v2/guide/cases/{key}       case guide (404 until published)
 *   GET /v2/guide/witnesses/{slug}  witness page
 *   GET /v2/guide/timeline          dual-track timeline
 *   GET /v2/glossary                editorial glossary
 *
 * Responses come from the local copy (TK_Store); their tags (TK_Paths::tags) let artifact and
 * corpus webhooks mark them stale.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Guides {

	const CASE_KEYS = array( '4000', '2000', '1000' );

	public static function valid_case( $key ) {
		return in_array( (string) $key, self::CASE_KEYS, true );
	}

	public static function valid_witness( $slug ) {
		return (bool) preg_match( '/^w_[0-9a-f]{10}$/', (string) $slug );
	}

	/** @return array /v2/guide */
	public static function home() {
		return TK_Rest_Proxy::cached_get( TK_Paths::guide() );
	}

	/**
	 * Published case guide, or null when it is not published yet (the 404 is cached
	 * too, so unpublished case pages do not hit the API on every view).
	 *
	 * @param string $key 1000|2000|4000.
	 * @return array|null
	 * @throws TK_Api_Error On transport errors.
	 */
	public static function case_guide( $key ) {
		if ( ! self::valid_case( $key ) ) {
			return null;
		}
		$path = TK_Paths::guide_case( $key );
		$data = TK_Cache::remember(
			$path,
			static function () use ( $path ) {
				return TK_Store::fetch_live( $path ); // 404 → array( '__missing' => true )
			}
		);
		return empty( $data['__missing'] ) ? $data : null;
	}

	/** @return array /v2/guide/witnesses/{slug} (throws 404 for unknown slugs) */
	public static function witness( $slug ) {
		return TK_Rest_Proxy::cached_get( TK_Paths::guide_witness( $slug ) );
	}

	/** @return array /v2/guide/timeline */
	public static function timeline() {
		return TK_Rest_Proxy::cached_get( TK_Paths::guide_timeline() );
	}

	/** @return array /v2/glossary */
	public static function glossary() {
		return TK_Rest_Proxy::cached_get( TK_Paths::glossary() );
	}

	/** Witness list from the start-page data; empty on API errors (callers degrade to plain names). */
	public static function witnesses() {
		try {
			$g = self::home();
		} catch ( TK_Api_Error $e ) {
			return array();
		}
		return (array) ( $g['witnesses'] ?? array() );
	}

	/**
	 * 'נאשם 1 — בנימין נתניהו' → array( 'בנימין נתניהו', 'נאשם 1' ).
	 *
	 * @param string $raw Witness string as printed in a hearing.
	 * @return array{0:string,1:string|null}
	 */
	public static function split_label( $raw ) {
		$raw = trim( (string) $raw );
		if ( preg_match( '/^\s*(נאש[םמ]ת?\s*\d+)\s*[—–-]\s*/u', $raw, $m ) ) {
			return array( trim( substr( $raw, strlen( $m[0] ) ) ), trim( $m[1] ) );
		}
		return array( $raw, null );
	}

	private static function fold( $name ) {
		return preg_replace( '/\s+/u', ' ', trim( (string) $name ) );
	}

	/** slug → the person's name as the site shows it (filled by slug_map()). */
	private static $names = array();

	/**
	 * name → slug map from a witness list. Every way a name was printed (``variants``: "מר אילן ישועה",
	 * "אלעד אבירם" for "אבירם אלעד", …) maps to the one person.
	 *
	 * @param array $witnesses /v2/guide witnesses.
	 * @return array
	 */
	public static function slug_map( array $witnesses ) {
		$map = array();
		foreach ( $witnesses as $w ) {
			if ( empty( $w['name'] ) || empty( $w['slug'] ) ) {
				continue;
			}
			self::$names[ $w['slug'] ] = $w['name'];
			$map[ self::fold( $w['name'] ) ] = $w['slug'];
			foreach ( (array) ( $w['variants'] ?? array() ) as $v ) {
				$map[ self::fold( $v ) ] = $map[ self::fold( $v ) ] ?? $w['slug'];
				list( $n ) = self::split_label( $v );
				$map[ self::fold( $n ) ] = $map[ self::fold( $n ) ] ?? $w['slug'];
			}
		}
		return $map;
	}

	/** Slug for a raw hearing witness string, or ''. */
	public static function slug_for( $raw, array $map ) {
		$whole = self::fold( $raw );
		if ( isset( $map[ $whole ] ) ) {
			return $map[ $whole ];
		}
		list( $name ) = self::split_label( $raw );
		$name         = self::fold( $name );
		return isset( $map[ $name ] ) ? $map[ $name ] : '';
	}

	/** The person's name for a slug from the last slug_map(), or ''. */
	public static function name_for( $slug ) {
		return (string) ( self::$names[ $slug ] ?? '' );
	}

	/**
	 * Notable Q/A exchanges of one hearing, with question/answer text, taken from the
	 * witness pages of the hearing's witnesses (the digest itself carries ids only).
	 *
	 * @param array $hearing Hearing object.
	 * @param array $map     name → slug.
	 * @return array
	 */
	public static function hearing_exchanges( array $hearing, array $map ) {
		$out = array();
		foreach ( (array) ( $hearing['witnesses'] ?? array() ) as $raw ) {
			$slug = self::slug_for( $raw, $map );
			if ( ! $slug ) {
				continue;
			}
			try {
				$w = self::witness( $slug );
			} catch ( TK_Api_Error $e ) {
				continue;
			}
			foreach ( (array) ( $w['notable_exchanges'] ?? array() ) as $x ) {
				if ( ( $x['hearing_id'] ?? '' ) === $hearing['id'] ) {
					$out[ $x['question_unit_id'] . '|' . $x['answer_unit_id'] ] = $x;
				}
			}
		}
		return array_values( $out );
	}

	/**
	 * Compact glossary for assets/glossary.js.
	 *
	 * @param array $gl /v2/glossary.
	 * @return array
	 */
	public static function glossary_script_data( array $gl ) {
		$terms = array();
		foreach ( (array) ( $gl['terms'] ?? array() ) as $t ) {
			if ( empty( $t['id'] ) || empty( $t['term'] ) ) {
				continue;
			}
			$link    = isset( $t['link'] ) && is_array( $t['link'] ) ? $t['link'] : null;
			$is_case = $link && 'case' === ( $link['type'] ?? '' ) && self::valid_case( $link['key'] ?? '' );
			$terms[] = array(
				'id'      => (string) $t['id'],
				'term'    => (string) $t['term'],
				'aliases' => array_values( array_filter( array_map( 'strval', (array) ( $t['aliases'] ?? array() ) ) ) ),
				'short'   => (string) ( $t['short'] ?? '' ),
				'url'     => $is_case ? TK_Public_Pages::url( 'case', $link['key'] ) : TK_Public_Pages::section_url( 'glossary' ) . '#term-' . rawurlencode( $t['id'] ),
				'more'    => $is_case ? __( 'לעמוד התיק', 'trial-knowledge' ) : __( 'עוד במילון', 'trial-knowledge' ),
			);
		}
		return array( 'terms' => $terms, 'note' => (string) ( $gl['note'] ?? '' ), 'label' => __( 'הסבר מונח', 'trial-knowledge' ), 'close' => __( 'סגירה', 'trial-knowledge' ) );
	}

	/** Load glossary.js with the glossary inline (once per request; silent on API errors). */
	public static function enqueue_glossary() {
		static $done = false;
		if ( $done ) {
			return;
		}
		$done = true;
		try {
			$gl = self::glossary();
		} catch ( TK_Api_Error $e ) {
			return;
		}
		wp_enqueue_script( 'trial-knowledge-glossary' );
		wp_add_inline_script(
			'trial-knowledge-glossary',
			'window.TKGlossary = ' . wp_json_encode( self::glossary_script_data( $gl ), JSON_UNESCAPED_UNICODE | JSON_HEX_TAG | JSON_HEX_AMP ) . ';',
			'before'
		);
	}

	/** Load the page scripts for tabs (hearing pages). */
	public static function enqueue_tabs() {
		wp_enqueue_script( 'trial-knowledge-tabs' );
	}

	public static function enqueue_timeline() {
		wp_enqueue_script( 'trial-knowledge-timeline' );
	}
}
