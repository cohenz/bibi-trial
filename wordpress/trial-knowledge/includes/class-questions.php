<?php
/**
 * Visitors' questions (2.7.8): answers "שאלו" already produced (and paid for) become a public, browsable list.
 *
 *   {prefix}tk_questions   one row per question (qkey = sha256 of the API's normalized question):
 *                          the latest answer (envelope), a newer answer waiting for the admin when the question is
 *                          already shown (next_envelope), state pending|shown|hidden, topic, display text, opens
 *
 * Nothing is shown until the admin approves it (מאגר המשפט ← שאלות מבקרים). Only answers that passed the gates
 * (answered, false_premise_corrected) are synced. A visitor opening a question counts once a day per visitor; the
 * list is ordered by those counts, so the questions readers care about rise to the top.
 *
 * @package TrialKnowledge
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class TK_Questions {

	const DB_VERSION = '1';
	const OPT_DB     = 'tk_questions_db_version';
	const OPT_SINCE  = 'tk_questions_since';
	const OPT_LAST   = 'tk_questions_last_sync';
	const HOOK       = 'tk_questions_sync';
	const STATES     = array( 'pending', 'shown', 'hidden' );

	/** Topic key → label. The order is the order of the filter chips. */
	const TOPICS = array(
		'4000'    => 'תיק 4000',
		'2000'    => 'תיק 2000',
		'1000'    => 'תיק 1000',
		'general' => 'כללי',
	);

	/** Words that point a question to a case (first match by count wins; none → general). */
	const TOPIC_WORDS = array(
		'4000' => array( '4000', 'אלוביץ', 'בזק', 'וואלה', 'ישועה', 'פילבר', 'חפץ', 'רגולציה' ),
		'2000' => array( '2000', 'מוזס', 'ידיעות', 'ישראל היום', 'חוק ישראל היום' ),
		'1000' => array( '1000', 'מילצ', 'פאקר', 'שמפני', 'סיגר', 'קליין' ),
	);

	public static function init() {
		add_action( self::HOOK, array( __CLASS__, 'cron_sync' ) );
		add_action( 'init', array( __CLASS__, 'maybe_schedule' ), 20 );
		add_action( 'rest_api_init', array( __CLASS__, 'routes' ) );
		add_shortcode( 'tk_questions', array( __CLASS__, 'shortcode' ) );
	}

	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'tk_questions';
	}

	public static function install() {
		global $wpdb;
		if ( ! function_exists( 'dbDelta' ) ) {
			require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		}
		$c = $wpdb->get_charset_collate();
		$t = self::table();
		dbDelta(
			"CREATE TABLE {$t} (
  qkey char(64) NOT NULL,
  answer_id char(36) NOT NULL DEFAULT '',
  question text NOT NULL,
  display_question text NOT NULL,
  envelope longtext NOT NULL,
  next_envelope longtext NOT NULL,
  answer_status varchar(40) NOT NULL DEFAULT '',
  state varchar(12) NOT NULL DEFAULT 'pending',
  topic varchar(12) NOT NULL DEFAULT 'general',
  opens int(10) unsigned NOT NULL DEFAULT 0,
  answered_at datetime NOT NULL,
  created_at datetime NOT NULL,
  updated_at datetime NOT NULL,
  PRIMARY KEY  (qkey),
  KEY state_opens (state,opens)
) {$c};"
		);
		update_option( self::OPT_DB, self::DB_VERSION, true );
	}

	public static function maybe_upgrade() {
		if ( get_option( self::OPT_DB ) !== self::DB_VERSION ) {
			self::install();
		}
	}

	public static function maybe_schedule() {
		self::maybe_upgrade();
		if ( ! wp_next_scheduled( self::HOOK ) ) {
			wp_schedule_event( time() + 2 * MINUTE_IN_SECONDS, 'hourly', self::HOOK );
		}
	}

	public static function deactivate() {
		wp_clear_scheduled_hook( self::HOOK );
	}

	// ------------------------------------------------------------------ pure helpers (tested without WordPress)

	public static function qkey( $normalized ) {
		return hash( 'sha256', (string) $normalized );
	}

	/** The short public id of a question (anchors, the open counter). */
	public static function short_id( $qkey ) {
		return substr( (string) $qkey, 0, 12 );
	}

	/** A first guess at the topic, from the question and the short answer; the admin can change it. */
	public static function guess_topic( $text ) {
		$t     = ' ' . str_replace( array( '׳', '’', "'" ), '', (string) $text ) . ' ';
		$best  = 'general';
		$score = 0;
		foreach ( self::TOPIC_WORDS as $topic => $words ) {
			$n = 0;
			foreach ( $words as $w ) {
				$n += mb_substr_count( $t, str_replace( "'", '', $w ) );
			}
			if ( $n > $score ) {
				$best  = (string) $topic; // PHP turns the key '1000' into an int
				$score = $n;
			}
		}
		return $best;
	}

	/**
	 * The row after an answer from the API arrives.
	 *
	 * A new question waits for the admin. A newer answer to a question that is not shown replaces the old one; for a
	 * question already shown it waits in next_envelope, so nothing changes on the site without the admin.
	 *
	 * @param array|null $row  Existing row (or null).
	 * @param array      $item /v2/admin/answers item with envelope.
	 * @param string     $now  'Y-m-d H:i:s' UTC.
	 * @return array|null The row to store, or null when nothing changes.
	 */
	public static function merge( $row, array $item, $now ) {
		$env = (array) ( $item['envelope'] ?? array() );
		$aid = (string) ( $item['answer_id'] ?? ( $env['answer_id'] ?? '' ) );
		if ( '' === $aid || empty( $env ) ) {
			return null;
		}
		$at   = substr( str_replace( 'T', ' ', (string) ( $item['created_at'] ?? $now ) ), 0, 19 );
		$json = wp_json_encode( $env, JSON_UNESCAPED_UNICODE );
		if ( null === $row ) {
			$q = (string) ( $item['question'] ?? ( $env['question'] ?? '' ) );
			return array(
				'qkey'             => self::qkey( (string) ( $item['normalized_question'] ?? ( $env['normalized_question'] ?? $q ) ) ),
				'answer_id'        => $aid,
				'question'         => $q,
				'display_question' => '',
				'envelope'         => $json,
				'next_envelope'    => '',
				'answer_status'    => (string) ( $item['answer_status'] ?? '' ),
				'state'            => 'pending',
				'topic'            => self::guess_topic( $q . ' ' . ( $env['answer_short'] ?? '' ) ),
				'opens'            => 0,
				'answered_at'      => $at,
				'created_at'       => $now,
				'updated_at'       => $now,
			);
		}
		$row = (array) $row;
		if ( $row['answer_id'] === $aid || ( $row['answered_at'] ?? '' ) > $at ) {
			return null; // the same answer, or an older one
		}
		if ( 'shown' === $row['state'] ) {
			$next = json_decode( (string) $row['next_envelope'], true );
			if ( is_array( $next ) && ( $next['answer_id'] ?? '' ) === $aid ) {
				return null;
			}
			$row['next_envelope'] = $json;
		} else {
			$row['envelope']      = $json;
			$row['answer_id']     = $aid;
			$row['answer_status'] = (string) ( $item['answer_status'] ?? $row['answer_status'] );
			$row['answered_at']   = $at;
		}
		$row['updated_at'] = $now;
		return $row;
	}

	/** Shown rows, most opened first, then the newest. */
	public static function sort_public( array $rows ) {
		usort(
			$rows,
			static function ( $a, $b ) {
				return ( (int) $b['opens'] <=> (int) $a['opens'] ) ?: strcmp( (string) $b['answered_at'], (string) $a['answered_at'] );
			}
		);
		return $rows;
	}

	public static function label( array $row ) {
		$d = trim( (string) ( $row['display_question'] ?? '' ) );
		return '' !== $d ? $d : (string) ( $row['question'] ?? '' );
	}

	// ------------------------------------------------------------------ storage

	public static function get( $qkey ) {
		global $wpdb;
		$r = $wpdb->get_row( $wpdb->prepare( 'SELECT * FROM ' . self::table() . ' WHERE qkey = %s', $qkey ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared,WordPress.DB.DirectDatabaseQuery
		return $r ? $r : null;
	}

	public static function rows( $state = '' ) {
		global $wpdb;
		$t = self::table();
		if ( in_array( $state, self::STATES, true ) ) {
			return (array) $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$t} WHERE state = %s ORDER BY answered_at DESC", $state ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
		}
		return (array) $wpdb->get_results( "SELECT * FROM {$t} ORDER BY answered_at DESC", ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
	}

	public static function counts() {
		$out = array_fill_keys( self::STATES, 0 );
		foreach ( self::rows() as $r ) {
			if ( isset( $out[ $r['state'] ] ) ) {
				++$out[ $r['state'] ];
			}
		}
		return $out;
	}

	public static function put( array $row ) {
		global $wpdb;
		return false !== $wpdb->replace( self::table(), $row ); // phpcs:ignore WordPress.DB.DirectDatabaseQuery
	}

	/**
	 * Admin changes to one row: state, topic, display text, accepting the newer answer.
	 *
	 * @param string $qkey   Row key.
	 * @param array  $change Any of state, topic, display_question, accept_update (bool).
	 */
	public static function update( $qkey, array $change ) {
		$row = self::get( $qkey );
		if ( ! $row ) {
			return false;
		}
		if ( isset( $change['state'] ) && in_array( $change['state'], self::STATES, true ) ) {
			$row['state'] = $change['state'];
		}
		if ( isset( $change['topic'] ) && isset( self::TOPICS[ $change['topic'] ] ) ) {
			$row['topic'] = $change['topic'];
		}
		if ( isset( $change['display_question'] ) ) {
			$d                       = trim( (string) $change['display_question'] );
			$row['display_question'] = $d === $row['question'] ? '' : mb_substr( $d, 0, 300 );
		}
		if ( ! empty( $change['accept_update'] ) && '' !== $row['next_envelope'] ) {
			$next                 = json_decode( (string) $row['next_envelope'], true );
			$row['envelope']      = $row['next_envelope'];
			$row['answer_id']     = (string) ( $next['answer_id'] ?? $row['answer_id'] );
			$row['answer_status'] = (string) ( $next['answer_status'] ?? $row['answer_status'] );
			$row['next_envelope'] = '';
		}
		$row['updated_at'] = gmdate( 'Y-m-d H:i:s' );
		return self::put( $row );
	}

	/** Pull answers stored since the last sync. @return array counts (new, updated). */
	public static function sync( $limit = 200 ) {
		self::maybe_upgrade();
		$since = (string) get_option( self::OPT_SINCE, '' );
		$path  = '/v2/admin/answers?status=answered,false_premise_corrected&envelope=true&limit=' . (int) $limit .
			( '' !== $since ? '&since=' . rawurlencode( $since ) : '' );
		$res   = tk_api()->get( $path, true );
		$items = array_reverse( (array) ( $res['items'] ?? array() ) ); // oldest first: the newest answer wins
		$now   = gmdate( 'Y-m-d H:i:s' );
		$out   = array( 'new' => 0, 'updated' => 0 );
		$max   = $since;
		foreach ( $items as $it ) {
			$q   = (string) ( $it['normalized_question'] ?? '' );
			$old = '' !== $q ? self::get( self::qkey( $q ) ) : null;
			$row = self::merge( $old, (array) $it, $now );
			if ( $row && self::put( $row ) ) {
				++$out[ $old ? 'updated' : 'new' ];
			}
			$c = (string) ( $it['created_at'] ?? '' );
			if ( $c > $max ) {
				$max = $c;
			}
		}
		if ( $max !== $since ) {
			update_option( self::OPT_SINCE, $max, false );
		}
		update_option( self::OPT_LAST, array( 'at' => $now, 'result' => $out ), false );
		return $out;
	}

	public static function cron_sync() {
		try {
			self::sync();
		} catch ( TK_Api_Error $e ) {
			update_option( self::OPT_LAST, array( 'at' => gmdate( 'Y-m-d H:i:s' ), 'error' => $e->getMessage() ), false );
		}
	}

	// ------------------------------------------------------------------ open counter (public)

	public static function routes() {
		register_rest_route(
			'trial-knowledge/v1',
			'/questions/(?P<id>[0-9a-f]{12})/open',
			array(
				'methods'             => 'POST',
				'callback'            => array( __CLASS__, 'opened' ),
				'permission_callback' => '__return_true',
			)
		);
	}

	/** A visitor opened a shown question: +1, once a day per visitor and question. */
	public static function opened( $req ) {
		global $wpdb;
		$id  = (string) $req->get_param( 'id' );
		$t   = self::table();
		$row = $wpdb->get_row( $wpdb->prepare( "SELECT qkey FROM {$t} WHERE state = 'shown' AND qkey LIKE %s", $wpdb->esc_like( $id ) . '%' ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
		if ( ! $row ) {
			return new WP_REST_Response( array( 'ok' => false ), 404 );
		}
		$seen = 'tk_qo_' . substr( hash( 'sha256', TK_Rest_Proxy::visitor_ip() . '|' . $id . '|' . gmdate( 'Y-m-d' ) ), 0, 32 );
		if ( ! get_transient( $seen ) ) {
			set_transient( $seen, 1, DAY_IN_SECONDS );
			$wpdb->query( $wpdb->prepare( "UPDATE {$t} SET opens = opens + 1 WHERE qkey = %s", $row['qkey'] ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.DirectDatabaseQuery
		}
		return new WP_REST_Response( array( 'ok' => true ), 200 );
	}

	// ------------------------------------------------------------------ public rendering

	public static function shortcode() {
		wp_enqueue_style( 'trial-knowledge' );
		wp_enqueue_script( 'trial-knowledge-questions' );
		return self::render_public( self::rows( 'shown' ) );
	}

	/** The public list: topic chips, then each question collapsed, most opened first. @param array $rows shown rows. */
	public static function render_public( array $rows ) {
		$rows = self::sort_public( $rows );
		if ( ! $rows ) {
			return '<p class="tk-muted">' . esc_html__( 'עדיין אין כאן שאלות. אפשר לשאול בעמוד הבית.', 'trial-knowledge' ) . '</p>';
		}
		$by = array();
		foreach ( $rows as $r ) {
			$by[ $r['topic'] ] = ( $by[ $r['topic'] ] ?? 0 ) + 1;
		}
		$out  = '<div class="tk-qs" dir="rtl" lang="he" data-endpoint="' . esc_url( rest_url( 'trial-knowledge/v1/questions/' ) ) . '">';
		$out .= '<div class="tk-qs__bar" role="group" aria-label="' . esc_attr__( 'סינון לפי נושא', 'trial-knowledge' ) . '">';
		$out .= '<button type="button" class="tk-qs__chip" data-topic="" aria-pressed="true">' . esc_html__( 'הכול', 'trial-knowledge' ) . ' <span class="tk-qs__n">' . count( $rows ) . '</span></button>';
		foreach ( self::TOPICS as $k => $label ) {
			if ( ! empty( $by[ $k ] ) ) {
				$out .= '<button type="button" class="tk-qs__chip" data-topic="' . esc_attr( $k ) . '" aria-pressed="false">' . esc_html( $label ) . ' <span class="tk-qs__n">' . (int) $by[ $k ] . '</span></button>';
			}
		}
		$out .= '</div><div class="tk-qs__list">';
		foreach ( $rows as $r ) {
			$env = json_decode( (string) $r['envelope'], true );
			if ( ! is_array( $env ) ) {
				continue;
			}
			$sid  = self::short_id( $r['qkey'] );
			$out .= '<details class="tk-q" id="q-' . esc_attr( $sid ) . '" data-id="' . esc_attr( $sid ) . '" data-topic="' . esc_attr( $r['topic'] ) . '">' .
				'<summary class="tk-q__s"><span class="tk-q__t">' . esc_html( self::label( $r ) ) . '</span>' .
				( isset( self::TOPICS[ $r['topic'] ] ) && 'general' !== $r['topic'] ? '<span class="tk-q__topic">' . esc_html( self::TOPICS[ $r['topic'] ] ) . '</span>' : '' ) .
				'</summary><div class="tk-q__a">' . TK_Render::answer( $env ) . '</div></details>';
		}
		return $out . '</div></div>';
	}
}
