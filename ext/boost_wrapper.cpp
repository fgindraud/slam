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

#include "screen_layout.h"

#include <boost/python.hpp>
namespace py = boost::python;

/* ------------------------- screen layout ------------------ */
namespace screen_layout {
	static pair mk_pair (py::object iterable) { return pair (py::extract< int > (iterable[0]), py::extract< int > (iterable[1])); }
	static py::tuple mk_py_tuple (const pair & p) { return py::make_tuple (p.x, p.y); }

	const char * py_doc =
		"Computes the optimal screen layout coordinates\n"
		"Input {\n"
		"   (w, h) : virtual screen maximum size\n"
		"   [(w0, h0), ...] : screen sizes\n"
		"   [[c00, c01, ...], [c10, ...], ...] : relation between screens as a matrix\n"
		"}\n"
		"Output {\n"
		"   (w, h) : virtual screen size\n"
		"   [(x0, y0), ...] : sequence of coordinates for screens\n"
		"}\n";

	static py::object py_func (py::object py_screen_min_size, py::object py_screen_max_size, py::object py_screen_sizes, py::object py_constraints) {
		int nb_screen = py::len (py_screen_sizes);
		pair screen_max_size = mk_pair (py_screen_max_size);
		pair screen_min_size = mk_pair (py_screen_min_size);
		
		pair_list screen_sizes;
		for (int i = 0; i < nb_screen; ++i) screen_sizes.push_back (mk_pair (py_screen_sizes[i]));
		
		setting constraints = mk_setting (nb_screen);
		for (int i = 0; i < py::len (py_constraints) && i < nb_screen; ++i) {
			py::object t = py_constraints[i];
			for (int j = 0; j < py::len (t) && j < nb_screen; ++j)
				constraints[i][j] = py::extract< dir > (t[j]);
		}

		pair_list screen_positions;
		pair screen_size;
		if (not compute_screen_layout (screen_min_size, screen_max_size, screen_sizes, constraints, screen_size, screen_positions))
			return py::object (); // None

		py::list py_screen_pos;
		for (int i = 0; i < nb_screen; ++i)
			py_screen_pos.append (mk_py_tuple (screen_positions[i]));

		return py::make_tuple (mk_py_tuple (screen_size), py_screen_pos);
	}
}

/* ---------------------- Module defintion ------------------ */

BOOST_PYTHON_MODULE (slam_ext) {
	using namespace boost::python;

	def ("Dir_invert", screen_layout::dir_invert);
	def ("Dir_str", screen_layout::dir_str);

	def ("screen_layout", screen_layout::py_func, screen_layout::py_doc);
}
