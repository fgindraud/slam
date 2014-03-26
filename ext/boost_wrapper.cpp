#include "screen_layout.h"

#include <boost/python.hpp>
namespace py = boost::python;

/* ------------------------- screen layout ------------------ */
namespace screen_layout {
	static pair mk_pair (py::object iterable) { return pair (py::extract< int > (iterable[0]), py::extract< int > (iterable[1])); }
	static py::tuple mk_py_tuple (const pair & p) { return py::make_tuple (p.x, p.y); }

	const char * py_doc =
		"Input {\n"
		"   (w, h) : virtual screen maximum size\n"
		"   [(w0, h0), ...] : screen sizes\n"
		"   [(sA, constraint, sB), ...] : sequence of relation between screens\n"
		"}\n"
		"Output {\n"
		"   (w, h) : virtual screen size\n"
		"   [(x0, y0), ...] : sequence of coordinates for screens\n"
		"}\n";

	static py::object py_func (py::object py_screen_max_size, py::object py_screen_sizes, py::object py_constraints) {
		int nb_screen = py::len (py_screen_sizes);
		pair screen_max_size = mk_pair (py_screen_max_size);
		
		pair_list screen_sizes;
		for (int i = 0; i < nb_screen; ++i) screen_sizes.push_back (mk_pair (py_screen_sizes[i]));
		
		setting constraints = mk_setting (nb_screen);
		for (int i = 0; i < py::len (py_constraints); ++i) {
			py::object t = py_constraints[i];
			int sa = py::extract< int > (t[0]); int sb = py::extract< int > (t[2]);
			constraints[sa][sb] = py::extract< dir > (t[1]);
			constraints[sb][sa] = invert_dir (constraints[sa][sb]);
		}

		pair_list screen_positions;
		pair screen_size;
		if (not compute_screen_layout (screen_max_size, screen_sizes, constraints, screen_size, screen_positions))
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

	enum_< screen_layout::dir > ("dir")
		.value ("none", screen_layout::none)
		.value ("left", screen_layout::left)
		.value ("right", screen_layout::right)
		.value ("above", screen_layout::above)
		.value ("under", screen_layout::under)
		;

	def ("screen_layout", screen_layout::py_func, screen_layout::py_doc);
}
