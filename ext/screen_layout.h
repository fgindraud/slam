// Copyright (c) 2013-2015 Francois GINDRAUD
// 
// Permission is hereby granted, free of charge, to any person obtaining
// a copy of this software and associated documentation files (the
// "Software"), to deal in the Software without restriction, including
// without limitation the rights to use, copy, modify, merge, publish,
// distribute, sublicense, and/or sell copies of the Software, and to
// permit persons to whom the Software is furnished to do so, subject to
// the following conditions:
// 
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
// 
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
// MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
// LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
// OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
// WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

#ifndef H_SCREEN_LAYOUT
#define H_SCREEN_LAYOUT

#include <vector>

namespace screen_layout {

	struct pair {
		int x; int y;
		pair (void) : x (0), y (0) {}
		pair (int _x, int _y) : x (_x), y (_y) {}
		pair operator+ (const pair & other) const { return pair (x + other.x, y + other.y); }
		bool operator< (const pair & other) const { return x < other.x || (x == other.x && y < other.y); }
	};

	typedef std::vector< pair > pair_list;

	// Convention between python and c++
	typedef int dir;
	enum {
		none = 0,
		left = 1,
		right = 2,
		above = 3,
		under = 4
	};
	static inline int dir_invert (dir d) {
		switch (d) {
			case left: return right;
			case right: return left;
			case above: return under;
			case under: return above;
			default: return none;
		}
	}
	static inline const char * dir_str (dir d) {
		switch (d) {
			case left: return "left";
			case right: return "right";
			case above: return "above";
			case under: return "under";
			default: return "none";
		}
	}

	typedef std::vector< std::vector< dir > > setting;
	static inline setting mk_setting (int nb_screen) { return setting (nb_screen, std::vector< dir > (nb_screen, none)); }

	bool compute_screen_layout (const pair & vscreen_min_size, const pair & vscreen_max_size, const pair_list & screen_sizes, const setting & user_constraints, pair & vscreen_size, pair_list & screen_positions);
}

#endif
