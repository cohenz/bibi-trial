<?php
/**
 * Public API request paths (2.5). Every reader-facing GET is built here, so that the renderers
 * and the local-copy prefetcher (TK_Sync) produce byte-identical keys for the same object.
 * Also the object tags of every path (used to mark stored copies stale).
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Paths {

	/** Pages per transcript/document request (services/common/ntk_common/db/public.py TEXT_PAGES_MAX). */
	const WINDOW = 25;

	/** Default page size of [tk_documents]. */
	const DOC_LIMIT = 50;

	/** Size of the request that counts procedural documents. */
	const PROCEDURAL_LIMIT = 200;

	/**
	 * Canonical form of a request path: query parameters sorted by name (then value) and
	 * re-encoded uniformly, empty query dropped. Equal requests → equal strings.
	 *
	 * @param string $path   Path with optional query (/v2/x?b=1&a=2).
	 * @param array  $params Extra query parameters merged in.
	 * @return string
	 */
	public static function canonical( $path, array $params = array() ) {
		$path  = (string) $path;
		$q     = '';
		$frag  = strpos( $path, '#' );
		$path  = false === $frag ? $path : substr( $path, 0, $frag );
		$qpos  = strpos( $path, '?' );
		if ( false !== $qpos ) {
			$q    = substr( $path, $qpos + 1 );
			$path = substr( $path, 0, $qpos );
		}
		$path  = '/' . ltrim( preg_replace( '#/{2,}#', '/', $path ), '/' );
		$pairs = array();
		foreach ( explode( '&', $q ) as $part ) {
			if ( '' === $part ) {
				continue;
			}
			$kv      = explode( '=', $part, 2 );
			$pairs[] = array( rawurldecode( str_replace( '+', ' ', $kv[0] ) ), isset( $kv[1] ) ? rawurldecode( str_replace( '+', ' ', $kv[1] ) ) : '' );
		}
		foreach ( $params as $k => $v ) {
			$pairs[] = array( (string) $k, is_bool( $v ) ? ( $v ? '1' : '0' ) : (string) $v );
		}
		usort(
			$pairs,
			static function ( $a, $b ) {
				return strcmp( $a[0], $b[0] ) ?: strcmp( $a[1], $b[1] );
			}
		);
		$out = array();
		foreach ( $pairs as $p ) {
			$out[] = rawurlencode( $p[0] ) . '=' . rawurlencode( $p[1] );
		}
		return $path . ( $out ? '?' . implode( '&', $out ) : '' );
	}

	/** First page of the 25-page window that contains $page (1, 26, 51 …). */
	public static function window_start( $page ) {
		$p = max( 1, (int) $page );
		return $p - ( ( $p - 1 ) % self::WINDOW );
	}

	/**
	 * Window starts of a text with $page_count pages.
	 *
	 * @param int|null $page_count Pages (unknown → one window).
	 * @return int[]
	 */
	public static function windows( $page_count ) {
		$n   = max( 1, (int) $page_count );
		$out = array();
		for ( $p = 1; $p <= $n; $p += self::WINDOW ) {
			$out[] = $p;
		}
		return $out;
	}

	public static function guide() {
		return '/v2/guide';
	}

	public static function guide_case( $key ) {
		return '/v2/guide/cases/' . preg_replace( '/[^0-9]/', '', (string) $key );
	}

	public static function guide_witness( $slug ) {
		return '/v2/guide/witnesses/' . preg_replace( '/[^A-Za-z0-9_]/', '', (string) $slug );
	}

	public static function guide_timeline() {
		return '/v2/guide/timeline';
	}

	public static function glossary() {
		return '/v2/glossary';
	}

	public static function hearing( $id ) {
		return '/v2/hearings/' . preg_replace( '/[^A-Za-z0-9_]/', '', (string) $id );
	}

	/** Transcript window of a hearing that contains page $page. */
	public static function transcript( $id, $page = 1 ) {
		return self::canonical( self::hearing( $id ) . '/transcript?page_from=' . self::window_start( $page ) );
	}

	/** Document window that contains page $page. */
	public static function document( $sv, $page = 1 ) {
		return self::canonical( '/v2/documents/' . preg_replace( '/[^A-Za-z0-9_]/', '', (string) $sv ) . '?page_from=' . self::window_start( $page ) );
	}

	public static function claim( $id ) {
		return '/v2/claims/' . strtolower( preg_replace( '/[^A-Fa-f0-9-]/', '', (string) $id ) );
	}

	public static function answer( $id ) {
		return '/v2/answers/' . strtolower( preg_replace( '/[^A-Fa-f0-9-]/', '', (string) $id ) );
	}

	public static function citation( $id ) {
		return '/v2/citations/' . preg_replace( '/[^A-Za-z0-9_]/', '', (string) $id );
	}

	/** Hearing timeline block (/v2/timeline), optionally as of a day (YYYY-MM-DD). */
	public static function timeline( $as_of = '' ) {
		$as_of = preg_match( '/^\d{4}-\d{2}-\d{2}$/', (string) $as_of ) ? $as_of : '';
		return self::canonical( '/v2/timeline' . ( $as_of ? '?as_of=' . rawurlencode( $as_of . 'T23:59:59Z' ) : '' ) );
	}

	/**
	 * Document list (/v2/documents).
	 *
	 * @param string $type         Source type or ''.
	 * @param int    $limit        1..200.
	 * @param string $significance '' | substantive | procedural.
	 */
	public static function documents_list( $type, $limit, $significance = '', $offset = 0 ) {
		$params = array( 'limit' => max( 1, min( 200, (int) $limit ) ) );
		if ( (int) $offset > 0 ) {
			$params['offset'] = (int) $offset;
		}
		$type   = preg_replace( '/[^a-z_]/', '', (string) $type );
		if ( $type ) {
			$params['type'] = $type;
		}
		if ( in_array( $significance, array( 'substantive', 'procedural' ), true ) ) {
			$params['significance'] = $significance;
		}
		return self::canonical( '/v2/documents', $params );
	}

	/** Newest substantive documents on the start page. */
	public static function latest_documents() {
		return self::documents_list( '', 3, 'substantive' );
	}

	/**
	 * Kind of a stored path (admin statistics, pruning).
	 *
	 * @param string $path Canonical path.
	 */
	public static function kind( $path ) {
		$p = (string) strtok( (string) $path, '?' );
		$map = array(
			'#^/v2/guide$#'                      => 'guide',
			'#^/v2/guide/cases/[^/]+$#'          => 'case',
			'#^/v2/guide/witnesses/[^/]+$#'      => 'witness',
			'#^/v2/guide/timeline$#'             => 'guide_timeline',
			'#^/v2/glossary$#'                   => 'glossary',
			'#^/v2/hearings/[^/]+/transcript$#'  => 'transcript',
			'#^/v2/hearings/[^/]+$#'             => 'hearing',
			'#^/v2/hearings$#'                   => 'list',
			'#^/v2/documents/[^/]+$#'            => 'document',
			'#^/v2/documents$#'                  => 'list',
			'#^/v2/claims/[^/]+$#'               => 'claim',
			'#^/v2/answers/[^/]+$#'              => 'answer',
			'#^/v2/citations/[^/]+$#'            => 'citation',
			'#^/v2/timeline$#'                   => 'timeline',
		);
		foreach ( $map as $re => $kind ) {
			if ( preg_match( $re, $p ) ) {
				return $kind;
			}
		}
		return 'other';
	}

	/** Object id in a stored path (/v2/hearings/hr_x/transcript → hr_x), or ''. */
	public static function object_id( $path ) {
		$p = (string) strtok( (string) $path, '?' );
		if ( preg_match( '#^/v2/(?:guide/cases|guide/witnesses|hearings|documents|claims|answers|citations)/([^/]+)#', $p, $m ) ) {
			return $m[1];
		}
		return '';
	}

	/**
	 * Object tags of a path: webhooks and the changes sync mark stored copies stale by these.
	 *
	 * @param string $path Canonical path.
	 * @return string[]
	 */
	public static function tags( $path ) {
		$id = self::object_id( $path );
		switch ( self::kind( $path ) ) {
			case 'guide':
				return array( 'guide', 'guide:home', 'lists' );
			case 'case':
				return array( 'guide', 'guide:case:' . $id, 'case:' . $id, 'lists' );
			case 'witness':
				return array( 'guide', 'witness:' . $id, 'lists' );
			case 'guide_timeline':
				return array( 'guide', 'timeline', 'lists' );
			case 'glossary':
				return array( 'glossary' ); // editorial and static; refreshed by the daily full sync
			case 'hearing':
			case 'transcript':
				return array( 'hearing:' . $id );
			case 'document':
				return array( 'document:' . $id );
			case 'list':
				return array( 'documents', 'lists' );
			case 'claim':
				return array( 'claim:' . $id, 'claims' );
			case 'answer':
				return array( 'answer:' . $id );
			case 'citation':
				return array( 'citation:' . $id );
			case 'timeline':
				return array( 'timeline', 'lists' );
		}
		return array( 'other' );
	}

	/**
	 * Extra tags found in a response: the source version behind a hearing or a citation, so that a
	 * source_version.* webhook (which names only the sv) reaches protocol pages and citations.
	 *
	 * @param array $body Response.
	 * @return string[]
	 */
	public static function body_tags( $body ) {
		$out = array();
		if ( ! is_array( $body ) ) {
			return $out;
		}
		$clean = static function ( $v ) {
			return preg_replace( '/[^A-Za-z0-9_\-]/', '', (string) $v );
		};
		if ( isset( $body['hearing'] ) && is_array( $body['hearing'] ) && ! empty( $body['hearing']['source_version_id'] ) ) {
			$out[] = 'document:' . $clean( $body['hearing']['source_version_id'] );
		}
		if ( isset( $body['citation'] ) && is_array( $body['citation'] ) && ! empty( $body['citation']['source_version_id'] ) ) {
			$out[] = 'document:' . $clean( $body['citation']['source_version_id'] );
		}
		if ( ! empty( $body['hearing_id'] ) && is_string( $body['hearing_id'] ) ) {
			$out[] = 'hearing:' . $clean( $body['hearing_id'] );
		}
		return $out;
	}
}
