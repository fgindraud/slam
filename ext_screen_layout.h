#ifndef H_SCREEN_LAYOUT
#define H_SCREEN_LAYOUT

#include <vector>

namespace screen_layout {

	struct pair {
		int x; int y;
		pair (void) : x (0), y (0) {}
		pair (int _x, int _y) : x (_x), y (_y) {}
		pair operator+ (const pair & other) const { return pair (x + other.x, y + other.y); }
	};

	typedef std::vector< pair > pair_list;

	enum dir { none, left, right, above, under };

	typedef std::vector< std::vector< dir > > setting;
	static inline setting mk_setting (int nb_screen) { return setting (nb_screen, std::vector< dir > (nb_screen, none)); }

	int compute_screen_layout (const pair & vscreen_max_size, const pair_list & screen_sizes, const setting & user_constraints, pair & vscreen_size, pair_list & screen_positions);
}

#endif