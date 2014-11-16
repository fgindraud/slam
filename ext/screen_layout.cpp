#include "screen_layout.h"

#include <algorithm>
#include <stdexcept>
#include <limits>
#include <isl/set.h>

namespace screen_layout {

	class sequence_pair {
		/* 
		 * Sequence pair enumeration of screen layout template (relations between screens but no absolute positionning)
		 * cf doc (packing paper)
		 *
		 * Instead of computing permutations of items [screen ids], we compute permutations of items positions offsets.
		 * This is equivalent (bijection with items themselves), but let us compute item order very fast.
		 */
		public:
			typedef std::vector< int > index_vector;

			sequence_pair (int size) : a (size), b (size) { for (int i = 0; i < size; ++i) a[i] = b[i] = i; }
			bool next (void) { return std::next_permutation (a.begin (), a.end ()) || std::next_permutation (b.begin (), b.end ()); }

			dir ordering (int sa, int sb) const {
				int left_diff = a[sb] - a[sa]; int right_diff = b[sb] - b[sa];
				if (left_diff > 0) return right_diff > 0 ? left : above;
				else return right_diff > 0 ? under : right;
			}
		private:
			index_vector a, b;
	};

	class rectangle_packer {
		/* [ISL]
		 * For each screen layout template, instantiate it by computing coordinates.
		 * Metric is : sum of distance between centers of each related screen.
		 */
		public:
			rectangle_packer (int _nb_screen, const pair & vscreen_min_size, const pair & vscreen_max_size, const pair_list & screen_sizes, const sequence_pair & layout) : nb_screen (_nb_screen) {
				init_solver ();

				// Virtual screen boundaries
				more_than_const (v_vscreen_size (X), vscreen_min_size.x); less_than_const (v_vscreen_size (X), vscreen_max_size.x);
				more_than_const (v_vscreen_size (Y), vscreen_min_size.y); less_than_const (v_vscreen_size (Y), vscreen_max_size.y);

				// Screens inside virtual screen
				for (int sc = 0; sc < nb_screen; ++sc) {
					positive_or_zero (v_screen_pos (sc, X)); offseted_less_than_var (v_screen_pos (sc, X), screen_sizes[sc].x, v_vscreen_size (X));
					positive_or_zero (v_screen_pos (sc, Y)); offseted_less_than_var (v_screen_pos (sc, Y), screen_sizes[sc].y, v_vscreen_size (Y));
				}

				// Screen ordering constraints
				for (int sa = 0;  sa < nb_screen; ++sa)
					for (int sb = 0; sb < sa; ++sb)
						switch (layout.ordering (sa, sb)) {
							case left: offseted_less_than_var (v_screen_pos (sa, X), screen_sizes[sa].x, v_screen_pos (sb, X)); break;
							case right: offseted_less_than_var (v_screen_pos (sb, X), screen_sizes[sb].x, v_screen_pos (sa, X)); break;
							case above: offseted_less_than_var (v_screen_pos (sa, Y), screen_sizes[sa].y, v_screen_pos (sb, Y)); break;
							case under: offseted_less_than_var (v_screen_pos (sb, Y), screen_sizes[sb].y, v_screen_pos (sa, Y)); break;
							default: throw std::runtime_error ("rectangle_packer: unordered screens despite sequence pair"); 
						}

				/* Objective function. sum of :
				 * - constraint gap length
				 * - distance between centers on second axis
				 */	
				const int constraint_gap_coeff = 1;
				const int center_distance_coeff = 1;
				
				std::vector< int > coeffs (v_nb (), 0); // More practical to gather coeffs
				coeffs[v_objective ()] = -1; // 0 = -o + sum(...)

				for (int sa = 0;  sa < nb_screen; ++sa)
					for (int sb = 0; sb < sa; ++sb)
						switch (layout.ordering (sa, sb)) {
							case left:
								coeffs[v_screen_pos (sa, X)] -= constraint_gap_coeff; coeffs[v_screen_pos (sb, X)] += constraint_gap_coeff; // o += sb.x - sa.x
								coeffs[distance_var (v_screen_pos (sa, Y), screen_sizes[sa].y, v_screen_pos (sb, Y), screen_sizes[sb].y)] += center_distance_coeff; // o += dist (sa.cy, sb.cy)
								break;
							case right:
								coeffs[v_screen_pos (sb, X)] -= constraint_gap_coeff; coeffs[v_screen_pos (sa, X)] += constraint_gap_coeff; // o += sa.x - sb.x
								coeffs[distance_var (v_screen_pos (sb, Y), screen_sizes[sb].y, v_screen_pos (sa, Y), screen_sizes[sa].y)] += center_distance_coeff; // o += dist (sb.cy, sa.cy)
								break;
							case above:
								coeffs[v_screen_pos (sa, Y)] -= constraint_gap_coeff; coeffs[v_screen_pos (sb, Y)] += constraint_gap_coeff; // o += sb.y - sa.y
								coeffs[distance_var (v_screen_pos (sa, X), screen_sizes[sa].x, v_screen_pos (sb, X), screen_sizes[sb].x)] += center_distance_coeff; // o += dist (sa.cx, sb.cx)
								break;
							case under:
								coeffs[v_screen_pos (sb, Y)] -= constraint_gap_coeff; coeffs[v_screen_pos (sa, Y)] += constraint_gap_coeff; // o += sa.y - sb.y
								coeffs[distance_var (v_screen_pos (sb, X), screen_sizes[sb].x, v_screen_pos (sa, X), screen_sizes[sa].x)] += center_distance_coeff; // o += dist (sb.cx, sa.cx)
								break;
							default:
								break; // Error handled before
						}
				equality (coeffs);
			}

			~rectangle_packer (void) { destroy_solver (); }

			bool solve (void) {
				if (solutions != 0) {
					solution = isl_set_sample_point (isl_set_lexmin (solutions));
					solutions = 0;
				}
				return not isl_point_is_void (solution);
			}

			long objective (void) const { return solution_val (v_objective ()); }
			pair virtual_screen (void) const { return pair (solution_val (v_vscreen_size (X)), solution_val (v_vscreen_size (Y))); }
			pair_list screen_positions (void) const {
				pair_list positions (nb_screen);
				for (int sc = 0; sc < nb_screen; ++sc) {
					positions[sc].x = solution_val (v_screen_pos (sc, X));
					positions[sc].y = solution_val (v_screen_pos (sc, Y));
				}
				return positions;
			}

		private:
			enum axis { X = 1, Y = 0, Next = 2 }; // Always place Y before X, so that height is minimized

			// Var
			int nb_screen;
			isl_ctx * context;
			isl_local_space * ls;
			isl_set * solutions;
			isl_point * solution;

			// Variable indexes
			inline int v_objective (void) const { return 0; }
			inline int v_vscreen_size (axis a) const { return v_objective () + 1 + a; }
			inline int v_screen_pos (int sc, axis a) const { return v_vscreen_size (Next) + a * nb_screen + sc; } // All Y before all X
			inline int v_max_var (int cnstr) const { return v_screen_pos (0, Next) + cnstr; }

			inline int max_var_nb (void) const { return (nb_screen * (nb_screen - 1)) / 2; }
			inline int v_nb (void) const { return v_max_var (max_var_nb ()); }

			// Init
			void init_solver (void) {
				context = isl_ctx_alloc ();
				isl_space * vars = isl_space_set_alloc (context, 0, v_nb ());
				ls = isl_local_space_from_space (isl_space_copy (vars));
				solutions = isl_set_universe (vars);
				solution = 0;
				next_max_var = 0;
			}
			void destroy_solver (void) {
				if (solution != 0) isl_point_free (solution);
				if (solutions != 0) isl_set_free (solutions);
				isl_local_space_free (ls);
				isl_ctx_free (context);
			}

			// Polyhedral contraints
			void positive_or_zero (int v) { // 0 <= v
				more_than_const (v, 0);
			}
			void more_than_const (int v, int constant) { // constant <= v
				isl_constraint * more = isl_inequality_alloc (isl_local_space_copy (ls));
				more = isl_constraint_set_coefficient_si (more, isl_dim_set, v, 1);
				more = isl_constraint_set_constant_si (more, -constant);
				solutions = isl_set_add_constraint (solutions, more); 
			}
			void less_than_const (int v, int constant) { // v <= constant
				isl_constraint * less = isl_inequality_alloc (isl_local_space_copy (ls));
				less = isl_constraint_set_coefficient_si (less, isl_dim_set, v, -1);
				less = isl_constraint_set_constant_si (less, constant);
				solutions = isl_set_add_constraint (solutions, less); 
			}
			void offseted_less_than_var (int v, int offset, int v2) { // v + offset <= v2
				isl_constraint * less = isl_inequality_alloc (isl_local_space_copy (ls));
				less = isl_constraint_set_coefficient_si (less, isl_dim_set, v, -1);
				less = isl_constraint_set_constant_si (less, -offset);
				less = isl_constraint_set_coefficient_si (less, isl_dim_set, v2, 1);
				solutions = isl_set_add_constraint (solutions, less);
			}
			void offseted_diff_less_than_var (int va, int vb, int offset, int mv) { // va - vb + offset <= mv
				isl_constraint * less = isl_inequality_alloc (isl_local_space_copy (ls));
				less = isl_constraint_set_coefficient_si (less, isl_dim_set, va, -1);
				less = isl_constraint_set_coefficient_si (less, isl_dim_set, vb, 1);
				less = isl_constraint_set_constant_si (less, -offset);
				less = isl_constraint_set_coefficient_si (less, isl_dim_set, mv, 1);
				solutions = isl_set_add_constraint (solutions, less);
			}
			void equality (const std::vector< int > & coeffs) {
				isl_constraint * equ = isl_equality_alloc (isl_local_space_copy (ls));
				for (unsigned c = 0; c < coeffs.size (); ++c)
					equ = isl_constraint_set_coefficient_si (equ, isl_dim_set, c, coeffs[c]);
				solutions = isl_set_add_constraint (solutions, equ);
			}

			/* Distance helper
			 * - picks a free variable (mv)
			 * - add { a - b <= mv, b - a <= mv }
			 * - with minimization : mv = max (a - b, b - a) = dist (a, b)
			 *
			 * Here we compare distance between centers, so offset with size/2 each time (var are corners)
			 */
			int next_max_var;
			int distance_var (int sa_var, int sa_size, int sb_var, int sb_size) {
				int mv = v_max_var (next_max_var++);
				offseted_diff_less_than_var (sa_var, sb_var, (sa_size - sb_size) / 2, mv); // a - b
				offseted_diff_less_than_var (sb_var, sa_var, (sb_size - sa_size) / 2, mv); // b - a
				return mv;
			}

			// Solution value
			long solution_val (int v) const {
				isl_val * val = isl_point_get_coordinate_val (solution, isl_dim_set, v);
				long val_int = isl_val_get_num_si (val);
				isl_val_free (val);
				return val_int;
			}
	};

	bool compute_screen_layout (const pair & vscreen_min_size, const pair & vscreen_max_size, const pair_list & screen_sizes, const setting & user_constraints, pair & vscreen_size, pair_list & screen_positions) {
		int nb_screen = screen_sizes.size ();
		const long init = std::numeric_limits< long >::max ();
		long last_objective = init;

		// Iterate over layout templates
		sequence_pair seq_pair (nb_screen);
		do {
			// Compare layout template to user constraints
			int ok = 1;
			for (int sa = 0; ok && sa < nb_screen; ++sa)
				for (int sb = 0; ok && sb < sa; ++sb)
					ok = user_constraints[sa][sb] == none || user_constraints[sa][sb] == seq_pair.ordering (sa, sb);

			if (ok) {
				// Compute positions	
				rectangle_packer packer (nb_screen, vscreen_min_size, vscreen_max_size, screen_sizes, seq_pair);
				if (packer.solve ()) {
					long objective = packer.objective ();
					pair virtual_screen_size = packer.virtual_screen ();

					// Record solution only if better objective (and smaller)
					if (objective < last_objective || (objective == last_objective && virtual_screen_size < vscreen_size)) {
						last_objective = objective;
						vscreen_size = virtual_screen_size;
						screen_positions = packer.screen_positions ();
					}
				}
			}
		} while (seq_pair.next ());
		return last_objective != init;
	}

}
