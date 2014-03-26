#include "ext_screen_layout.h"

#include <algorithm>
#include <isl/set.h>

#include <iostream>

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
		/*
		 * For each screen layout template, instantiate it by computing coordinates.
		 * Metric is : sum of distance between centers of each related screen.
		 */
		public:
			rectangle_packer (int _nb_screen, const pair & vscreen_max_size, const pair_list & screen_sizes, const sequence_pair & layout) : nb_screen (_nb_screen) {
				init_solver (nb_screen);

				// Virtual screen boundaries
				positive_or_zero (v_vscreen_size (X)); less_than_const (v_vscreen_size (X), vscreen_max_size.x);
				positive_or_zero (v_vscreen_size (Y)); less_than_const (v_vscreen_size (Y), vscreen_max_size.y);

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
							default: throw "unordered screens"; //TODO runtime error
						}

				/* Objective function. sum of :
				 * - constraint gap length
				 * - distance between centers on second axis
				 */
			}

			~rectangle_packer (void) { destroy_solver (); }

			void print (void) const {
				isl_printer * p = isl_printer_to_file (context, stderr);
				p = isl_printer_print_set (p, solutions);
				p = isl_printer_end_line (p);
				isl_printer_free (p);
			}

		private:
			enum axis { X = 1, Y = 0, Next = 2 }; // Always place Y before X, so that height is minimized

			// Var
			int nb_screen;
			isl_ctx * context;
			isl_local_space * ls;
			isl_set * solutions;

			// Variable indexes
			inline int v_objective (void) { return 0; }
			inline int v_vscreen_size (axis a) { return v_objective () + 1 + a; }
			inline int v_screen_pos (int sc, axis a) { return v_vscreen_size (Next) + a * nb_screen + sc; } // All Y before all X
			inline int v_max_var (int cnstr) { return v_screen_pos (0, Next) + cnstr; }

			inline int max_var_nb (void) { return (nb_screen * (nb_screen + 1)) / 2; }
			inline int v_nb (void) { return v_max_var (max_var_nb ()); }

			// Init
			void init_solver (int nb_screen) {
				context = isl_ctx_alloc ();
				isl_space * vars = isl_space_set_alloc (context, 0, v_nb ());
				ls = isl_local_space_from_space (isl_space_copy (vars));
				solutions = isl_set_universe (vars);
			}
			void destroy_solver (void) {
				isl_set_free (solutions);
				isl_local_space_free (ls);
				isl_ctx_free (context);
			}

			// Polyhedral contraints
			void positive_or_zero (int v) { // 0 <= v
				isl_constraint * positive = isl_inequality_alloc (isl_local_space_copy (ls));
				positive = isl_constraint_set_coefficient_si (positive, isl_dim_set, v, 1);
				solutions = isl_set_add_constraint (solutions, positive); 
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

	};

	void compute_screen_layout (const pair & vscreen_max_size, const pair_list & screen_sizes, const setting & user_constraints, pair & vscreen_size, pair_list & screen_positions) {
		int nb_screen = screen_sizes.size ();

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
				
				rectangle_packer packer (nb_screen, vscreen_max_size, screen_sizes, seq_pair);

				packer.print ();

				/*std::cout << "==============\n";
				  for (int sa = 0; sa < nb_screen; ++sa)
				  for (int sb = 0; sb < sa; ++sb) {
				  dir d = current[sa][sb];
				  if (d == left) std::cout << sa << " left of " << sb << "\n";
				  if (d == right) std::cout << sa << " right of " << sb << "\n";
				  if (d == above) std::cout << sa << " above " << sb << "\n";
				  if (d == under) std::cout << sa << " under " << sb << "\n";
				  }
				  */

			}

		} while (seq_pair.next ());
	}

}
