<?php
/**
 * In-memory stand-in for $wpdb, enough for TK_Store / TK_Sync: prepare, get_row, get_results,
 * get_col, get_var, query, replace, delete, update. It evaluates the small SQL subset the plugin
 * uses (SELECT with COUNT/SUM, WHERE … AND … with = <> < <= > >= IN, GROUP BY, ORDER BY, LIMIT;
 * UPDATE … SET col = v | col = col + 1; DELETE; TRUNCATE; DROP TABLE IF EXISTS).
 */

define( 'ARRAY_A', 'ARRAY_A' );
define( 'OBJECT', 'OBJECT' );

final class TK_Fake_WPDB {
	public $prefix = 'wp_';
	public $posts  = '';
	/** @var array table → pk → row */
	public $tables = array();
	/** @var array table → pk columns */
	public $pks = array();
	public $queries = array();
	public $last_error = '';

	public function __construct() {
		$this->pks = array(
			'wp_tk_store'      => array( 'path_hash' ),
			'wp_tk_store_tags' => array( 'tag', 'path_hash' ),
			'wp_tk_questions'  => array( 'qkey' ),
		);
		$this->reset();
	}

	public function reset() {
		$this->tables = array( 'wp_tk_store' => array(), 'wp_tk_store_tags' => array(), 'wp_tk_questions' => array() );
	}

	public function get_charset_collate() {
		return 'DEFAULT CHARSET=utf8mb4';
	}

	public function prepare( $q, ...$args ) {
		if ( 1 === count( $args ) && is_array( $args[0] ) ) {
			$args = $args[0];
		}
		$i = 0;
		return preg_replace_callback(
			'/%[sdf]/',
			function ( $m ) use ( &$i, $args ) {
				$v = $args[ $i++ ];
				if ( '%d' === $m[0] ) {
					return (string) (int) $v;
				}
				if ( '%f' === $m[0] ) {
					return (string) (float) $v;
				}
				return "'" . str_replace( array( '\\', "'" ), array( '\\\\', "\\'" ), (string) $v ) . "'";
			},
			$q
		);
	}

	private function key( $table, array $row ) {
		$k = array();
		foreach ( $this->pks[ $table ] ?? array_keys( $row ) as $c ) {
			$k[] = (string) ( $row[ $c ] ?? '' );
		}
		return implode( "\x1f", $k );
	}

	public function replace( $table, array $data, $format = null ) {
		if ( ! isset( $this->tables[ $table ] ) ) {
			return false;
		}
		$this->tables[ $table ][ $this->key( $table, $data ) ] = array_map( static function ( $v ) { return null === $v ? null : (string) $v; }, $data );
		return 1;
	}

	public function insert( $table, array $data, $format = null ) {
		return $this->replace( $table, $data, $format );
	}

	public function delete( $table, array $where, $format = null ) {
		$n = 0;
		foreach ( $this->tables[ $table ] ?? array() as $k => $row ) {
			if ( $this->match_eq( $row, $where ) ) {
				unset( $this->tables[ $table ][ $k ] );
				++$n;
			}
		}
		return $n;
	}

	public function update( $table, array $data, array $where, $format = null, $wf = null ) {
		$n = 0;
		foreach ( $this->tables[ $table ] ?? array() as $k => $row ) {
			if ( $this->match_eq( $row, $where ) ) {
				$this->tables[ $table ][ $k ] = array_merge( $row, array_map( 'strval', $data ) );
				++$n;
			}
		}
		return $n;
	}

	private function match_eq( array $row, array $where ) {
		foreach ( $where as $c => $v ) {
			if ( (string) ( $row[ $c ] ?? '' ) !== (string) $v ) {
				return false;
			}
		}
		return true;
	}

	// ------------------------------------------------------------------ SQL subset

	private function tokens( $sql ) {
		preg_match_all( "/'(?:[^'\\\\]|\\\\.)*'|-?\\d+(?:\\.\\d+)?|[A-Za-z_][A-Za-z0-9_.]*|<>|<=|>=|!=|[(),=<>*+\\-]/s", $sql, $m );
		return $m[0];
	}

	private static function lit( $t ) {
		if ( "'" === $t[0] ) {
			return stripcslashes( substr( $t, 1, -1 ) );
		}
		return $t;
	}

	/** Parse "a = 1 AND b IN ('x','y')" tokens into conditions. */
	private function conds( array $t, &$i ) {
		$out = array();
		while ( $i < count( $t ) ) {
			$col = $t[ $i++ ];
			$op  = strtoupper( $t[ $i++ ] );
			if ( 'IN' === $op ) {
				$vals = array();
				++$i; // (
				while ( ')' !== $t[ $i ] ) {
					if ( ',' !== $t[ $i ] ) {
						$vals[] = self::lit( $t[ $i ] );
					}
					++$i;
				}
				++$i;
				$out[] = array( $col, 'IN', $vals );
			} else {
				$out[] = array( $col, $op, self::lit( $t[ $i++ ] ) );
			}
			if ( $i < count( $t ) && 'AND' === strtoupper( $t[ $i ] ) ) {
				++$i;
				continue;
			}
			break;
		}
		return $out;
	}

	private function test( array $row, array $conds ) {
		foreach ( $conds as $c ) {
			list( $col, $op, $v ) = $c;
			$a = $row[ $col ] ?? null;
			$num = is_numeric( $a ) && ( is_array( $v ) || is_numeric( $v ) );
			switch ( $op ) {
				case 'IN':
					$ok = in_array( (string) $a, array_map( 'strval', $v ), true );
					break;
				case '=':
					$ok = $num ? (float) $a === (float) $v : (string) $a === (string) $v;
					break;
				case '<>':
				case '!=':
					$ok = $num ? (float) $a !== (float) $v : (string) $a !== (string) $v;
					break;
				case '<':
					$ok = $num ? (float) $a < (float) $v : strcmp( (string) $a, (string) $v ) < 0;
					break;
				case '<=':
					$ok = $num ? (float) $a <= (float) $v : strcmp( (string) $a, (string) $v ) <= 0;
					break;
				case '>':
					$ok = $num ? (float) $a > (float) $v : strcmp( (string) $a, (string) $v ) > 0;
					break;
				case '>=':
					$ok = $num ? (float) $a >= (float) $v : strcmp( (string) $a, (string) $v ) >= 0;
					break;
				case 'LIKE':
					$re = '/^' . str_replace( array( '%', '_' ), array( '.*', '.' ), preg_quote( str_replace( '\\_', "\x01", $v ), '/' ) ) . '$/s';
					$ok = (bool) preg_match( str_replace( "\x01", '_', $re ), (string) $a );
					break;
				default:
					throw new RuntimeException( 'fake wpdb: operator ' . $op );
			}
			if ( ! $ok ) {
				return false;
			}
		}
		return true;
	}

	private function select( $sql ) {
		$t = $this->tokens( $sql );
		$i = 1;
		$cols = array();
		while ( 'FROM' !== strtoupper( $t[ $i ] ) ) {
			if ( ',' === $t[ $i ] ) {
				++$i;
				continue;
			}
			$fn = strtoupper( $t[ $i ] );
			if ( in_array( $fn, array( 'COUNT', 'SUM', 'MIN', 'MAX' ), true ) && '(' === ( $t[ $i + 1 ] ?? '' ) ) {
				$arg = $t[ $i + 2 ];
				$i  += 4;
				$col = array( 'fn' => $fn, 'arg' => $arg, 'as' => $fn . '(' . $arg . ')' );
			} elseif ( 'DISTINCT' === $fn ) {
				++$i;
				continue;
			} else {
				$col = array( 'fn' => null, 'arg' => $t[ $i ], 'as' => $t[ $i ] );
				++$i;
			}
			if ( isset( $t[ $i ] ) && 'AS' === strtoupper( $t[ $i ] ) ) {
				$col['as'] = $t[ $i + 1 ];
				$i        += 2;
			}
			$cols[] = $col;
		}
		$table = $t[ ++$i ];
		++$i;
		if ( ! isset( $this->tables[ $table ] ) ) {
			return array();
		}
		$conds = array();
		$group = null;
		$order = array();
		$limit = null;
		while ( $i < count( $t ) ) {
			$kw = strtoupper( $t[ $i ] );
			if ( 'WHERE' === $kw ) {
				++$i;
				$conds = $this->conds( $t, $i );
			} elseif ( 'GROUP' === $kw ) {
				$group = $t[ $i + 2 ];
				$i    += 3;
			} elseif ( 'ORDER' === $kw ) {
				$i += 2;
				while ( $i < count( $t ) && 'LIMIT' !== strtoupper( $t[ $i ] ) ) {
					$c   = $t[ $i++ ];
					$dir = 'ASC';
					if ( $i < count( $t ) && in_array( strtoupper( $t[ $i ] ), array( 'ASC', 'DESC' ), true ) ) {
						$dir = strtoupper( $t[ $i++ ] );
					}
					$order[] = array( $c, $dir );
					if ( $i < count( $t ) && ',' === $t[ $i ] ) {
						++$i;
					}
				}
			} elseif ( 'LIMIT' === $kw ) {
				$limit = (int) $t[ $i + 1 ];
				$i    += 2;
			} else {
				throw new RuntimeException( 'fake wpdb: unexpected ' . $t[ $i ] . ' in ' . $sql );
			}
		}
		$rows = array_values( array_filter( $this->tables[ $table ], function ( $r ) use ( $conds ) {
			return $this->test( $r, $conds );
		} ) );
		if ( $order ) {
			usort( $rows, static function ( $a, $b ) use ( $order ) {
				foreach ( $order as $o ) {
					$x = $a[ $o[0] ] ?? '';
					$y = $b[ $o[0] ] ?? '';
					$c = is_numeric( $x ) && is_numeric( $y ) ? ( $x <=> $y ) : strcmp( (string) $x, (string) $y );
					if ( 0 !== $c ) {
						return 'DESC' === $o[1] ? -$c : $c;
					}
				}
				return 0;
			} );
		}
		$aggregate = (bool) array_filter( $cols, static function ( $c ) { return null !== $c['fn']; } );
		if ( $aggregate ) {
			$groups = array();
			foreach ( $rows as $r ) {
				$groups[ null === $group ? '' : (string) $r[ $group ] ][] = $r;
			}
			if ( ! $groups && null === $group ) {
				$groups[''] = array();
			}
			$out = array();
			foreach ( $groups as $g ) {
				$o = array();
				foreach ( $cols as $c ) {
					if ( 'COUNT' === $c['fn'] ) {
						$o[ $c['as'] ] = (string) count( $g );
					} elseif ( 'SUM' === $c['fn'] ) {
						$o[ $c['as'] ] = $g ? (string) array_sum( array_column( $g, $c['arg'] ) ) : null;
					} elseif ( 'MIN' === $c['fn'] || 'MAX' === $c['fn'] ) {
						$v             = array_column( $g, $c['arg'] );
						$o[ $c['as'] ] = $v ? (string) ( 'MIN' === $c['fn'] ? min( $v ) : max( $v ) ) : null;
					} else {
						$o[ $c['as'] ] = $g ? $g[0][ $c['arg'] ] : null;
					}
				}
				$out[] = $o;
			}
			$rows = $out;
		} else {
			$rows = array_map( static function ( $r ) use ( $cols ) {
				if ( 1 === count( $cols ) && '*' === $cols[0]['arg'] ) {
					return $r;
				}
				$o = array();
				foreach ( $cols as $c ) {
					$o[ $c['as'] ] = $r[ $c['arg'] ] ?? null;
				}
				return $o;
			}, $rows );
		}
		if ( null !== $limit ) {
			$rows = array_slice( $rows, 0, $limit );
		}
		return $rows;
	}

	public function query( $sql ) {
		$this->queries[] = $sql;
		$t  = $this->tokens( $sql );
		$kw = strtoupper( $t[0] );
		if ( 'SELECT' === $kw ) {
			return count( $this->select( $sql ) );
		}
		if ( 'TRUNCATE' === $kw ) {
			$this->tables[ $t[2] ] = array();
			return true;
		}
		if ( 'DROP' === $kw ) {
			unset( $this->tables[ end( $t ) ] );
			return true;
		}
		if ( 'DELETE' === $kw ) {
			$table = $t[2];
			$i     = 4;
			$conds = isset( $t[3] ) ? $this->conds( $t, $i ) : array();
			$n     = 0;
			foreach ( $this->tables[ $table ] ?? array() as $k => $r ) {
				if ( $this->test( $r, $conds ) ) {
					unset( $this->tables[ $table ][ $k ] );
					++$n;
				}
			}
			return $n;
		}
		if ( 'UPDATE' === $kw ) {
			$table = $t[1];
			$i     = 3; // after SET
			$sets  = array();
			while ( $i < count( $t ) && 'WHERE' !== strtoupper( $t[ $i ] ) ) {
				$col = $t[ $i ];
				$i  += 2; // col =
				if ( isset( $t[ $i + 1 ] ) && '+' === $t[ $i + 1 ] ) {
					$sets[ $col ] = array( 'add', $t[ $i ], (int) $t[ $i + 2 ] );
					$i           += 3;
				} else {
					$sets[ $col ] = array( 'val', self::lit( $t[ $i ] ) );
					++$i;
				}
				if ( $i < count( $t ) && ',' === $t[ $i ] ) {
					++$i;
				}
			}
			$conds = array();
			if ( $i < count( $t ) ) {
				++$i;
				$conds = $this->conds( $t, $i );
			}
			$n = 0;
			foreach ( $this->tables[ $table ] ?? array() as $k => $r ) {
				if ( ! $this->test( $r, $conds ) ) {
					continue;
				}
				foreach ( $sets as $c => $s ) {
					$r[ $c ] = 'add' === $s[0] ? (string) ( (int) $r[ $s[1] ] + $s[2] ) : (string) $s[1];
				}
				$this->tables[ $table ][ $k ] = $r;
				++$n;
			}
			return $n;
		}
		throw new RuntimeException( 'fake wpdb: unsupported ' . $sql );
	}

	public function get_results( $sql, $output = OBJECT ) {
		$this->queries[] = $sql;
		$rows            = $this->select( $sql );
		return ARRAY_A === $output ? $rows : array_map( static function ( $r ) { return (object) $r; }, $rows );
	}

	public function get_row( $sql, $output = OBJECT ) {
		$rows = $this->get_results( $sql, $output );
		return $rows ? $rows[0] : null;
	}

	public function get_col( $sql ) {
		$this->queries[] = $sql;
		return array_map( static function ( $r ) { return reset( $r ); }, $this->select( $sql ) );
	}

	public function get_var( $sql ) {
		$this->queries[] = $sql;
		$rows            = $this->select( $sql );
		return $rows ? reset( $rows[0] ) : null;
	}
}
