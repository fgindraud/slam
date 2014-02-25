#include <Python.h>

#include <isl/set.h>

/* --------------------- Relation direction enum ----------- */

enum relation_dir_t {
	C_NONE = 0,
	C_LEFT_OF = 1, C_RIGHT_OF = 4,
	C_ABOVE = 2, C_BELOW = 3,
	C_NB = 5
};
static int relation_reverse_dir (int c) { return C_NB - c; }
static const char * relation_str (int c) {
	switch (c) {
		case C_NONE: return "<none>";
		case C_LEFT_OF: return "left-of";
		case C_RIGHT_OF: return "right-of";
		case C_ABOVE: return "above";
		case C_BELOW: return "below";
		default: PyErr_SetString (PyExc_ValueError, "not a relation"); return NULL;
	}
}

/* ----------- Compute screen coordinates with Isl --------- */

struct coord_t { long x, y; }; // Coord struct

// Helpers for relation array
static inline int * relation_p (int nb_sc, int * rels, int x, int y) { return &rels[x + y * nb_sc]; }
static int relation_add (int nb_sc, int * rels, int sa, int c, int sb) {
	if (!(0 <= sa && sa < nb_sc) || !(0 <= sb && sb < nb_sc)) { PyErr_SetString (PyExc_IndexError, "relation screen index out of bounds"); return 0; }
	if (!(0 < c && c < C_NB)) { PyErr_SetString (PyExc_ValueError, "relation direction is invalid"); return 0; }
	if (sa <= sb) { *relation_p (nb_sc, rels, sa, sb) = c; }
	else { *relation_p (nb_sc, rels, sb, sa) = c; }
	return 1;
}

/* Isl helpers
 *
 * Solution parameters :
 * [0, 1] virtual screen (height, width)
 * [2 + 2i, 3 + 2i] screen i base coordinates (y, x)
 */
static __isl_give isl_set * isl_solution_vscreen_limit (__isl_take isl_set * set, __isl_keep isl_local_space * ls, int comp, int max) {
	isl_constraint * lower = isl_inequality_alloc (isl_local_space_copy (ls));
	lower = isl_constraint_set_coefficient_si (lower, isl_dim_set, comp, 1);
	set = isl_set_add_constraint (set, lower); // 0 <= comp

	isl_constraint * higher = isl_inequality_alloc (isl_local_space_copy (ls));
	higher = isl_constraint_set_coefficient_si (higher, isl_dim_set, comp, -1);
	higher = isl_constraint_set_constant_si (higher, max);
	return isl_set_add_constraint (set, higher); // comp <= max
}

static __isl_give isl_set * isl_solution_screen_in_vscreen (__isl_take isl_set * set, __isl_keep isl_local_space * ls, int comp, int screen, int screen_size) {
	isl_constraint * lower = isl_inequality_alloc (isl_local_space_copy (ls));
	lower = isl_constraint_set_coefficient_si (lower, isl_dim_set, 2 + 2 * screen + comp, 1);
	set = isl_set_add_constraint (set, lower); // 0 <= screen.comp

	isl_constraint * higher = isl_inequality_alloc (isl_local_space_copy (ls));
	higher = isl_constraint_set_coefficient_si (higher, isl_dim_set, 2 + 2 * screen + comp, -1);
	higher = isl_constraint_set_constant_si (higher, -screen_size);
	higher = isl_constraint_set_coefficient_si (higher, isl_dim_set, comp, 1);
	return isl_set_add_constraint (set, higher); // screen.comp + screen.size <= comp
}

static __isl_give isl_set * isl_solution_screen_before (__isl_take isl_set * set, __isl_keep isl_local_space * ls, int comp, int sa, int screen_size, int sb) {
	isl_constraint * rel = isl_inequality_alloc (isl_local_space_copy (ls));
	rel = isl_constraint_set_coefficient_si (rel, isl_dim_set, 2 + 2 * sa + comp, -1);
	rel = isl_constraint_set_constant_si (rel, -screen_size);
	rel = isl_constraint_set_coefficient_si (rel, isl_dim_set, 2 + 2 * sb + comp, 1);
	return isl_set_add_constraint (set, rel); // sa.comp + sa.size <= sb.comp
}

static __isl_give isl_set * isl_solution_screen_no_intersect (__isl_take isl_set * set, __isl_keep isl_local_space * ls, struct coord_t * screen_sizes, int sa, int sb);
static __isl_give isl_set * isl_solution_screen_rel (__isl_take isl_set * set, __isl_keep isl_local_space * ls, struct coord_t * screen_sizes, int sa, int c, int sb) {
	switch (c) {
		case C_NONE: return isl_solution_screen_no_intersect (set, ls, screen_sizes, sa, sb); // or of the 4 others
		case C_LEFT_OF: return isl_solution_screen_before (set, ls, 1, sa, screen_sizes[sa].x, sb); // sa.x + sa.w <= sb.x
		case C_RIGHT_OF: return isl_solution_screen_before (set, ls, 1, sb, screen_sizes[sb].x, sa); // sb.x + sb.w <= sa.x
		case C_ABOVE: return isl_solution_screen_before (set, ls, 0, sa, screen_sizes[sa].y, sb); // sa.y + sa.h <= sb.y
		case C_BELOW: return isl_solution_screen_before (set, ls, 0, sb, screen_sizes[sb].y, sa); // sb.y + sb.h <= sa.y
		default: return set;
	}
}

static void print_set (__isl_keep isl_set * set) {
	isl_printer * p = isl_printer_to_file (isl_set_get_ctx (set), stderr);
	p = isl_printer_print_set (p, set);
	p = isl_printer_end_line (p);
	isl_printer_free (p);
}

static __isl_give isl_set * isl_solution_screen_no_intersect (__isl_take isl_set * set, __isl_keep isl_local_space * ls, struct coord_t * screen_sizes, int sa, int sb) {
	isl_set * unioned = isl_set_empty (isl_local_space_get_space (ls));
	int rels[] = { C_LEFT_OF, C_RIGHT_OF, C_ABOVE, C_BELOW }; int i; int b = sizeof (rels) / sizeof (rels[0]); 
	for (i = 0; i < b; ++i) {
		isl_set * new = isl_set_universe (isl_local_space_get_space (ls));	
		unioned = isl_set_union (unioned, isl_solution_screen_rel (new, ls, screen_sizes, sa, rels[i], sb));
	}
	return isl_set_intersect (set, unioned);
}

static int isl_compute_screen_positions (long screen_max_width, long screen_max_height, int nb_screen, struct coord_t * screen_sizes, int * relations) {
	int i, j;
	isl_ctx * ctx = isl_ctx_alloc ();
	isl_space * vars = isl_space_set_alloc (ctx, 0, 2 + 2 * nb_screen);
	isl_local_space * ls = isl_local_space_from_space (isl_space_copy (vars));
	isl_set * solutions = isl_set_universe (vars);

	solutions = isl_solution_vscreen_limit (solutions, ls, 0, screen_max_height); // Max height & width
	solutions = isl_solution_vscreen_limit (solutions, ls, 1, screen_max_width);

	for (i = 0; i < nb_screen; ++i) { // Screens inside virtual screen
		solutions = isl_solution_screen_in_vscreen (solutions, ls, 0, i, screen_sizes[i].y);
		solutions = isl_solution_screen_in_vscreen (solutions, ls, 1, i, screen_sizes[i].x);
	}

	for (j = 0; j < nb_screen; ++j) // Add relations
		for (i = 0; i < j; ++i)
			solutions = isl_solution_screen_rel (solutions, ls, screen_sizes, i, *relation_p (nb_screen, relations, i, j), j);

	print_set (solutions);

	isl_set_free (solutions);
	isl_local_space_free (ls);
	isl_ctx_free (ctx);
	return 1;
}

// Python interface
static PyObject * compute_screen_positions (PyObject * self, PyObject * args) {
	Py_ssize_t i;
	Py_ssize_t nb_screen; struct coord_t * screen_sizes = NULL; int * relations = NULL;
	PyObject * screen_sizes_seq = NULL; PyObject * relations_seq = NULL;
	PyObject * ret_screen_pos_list = NULL;

	// Unpack args
	long screen_max_width, screen_max_height;
	PyObject * tuple_list_screen_sizes; PyObject * tuple_list_relations;
	if (!PyArg_ParseTuple (args, "(ll)OO", &screen_max_width, &screen_max_height, &tuple_list_screen_sizes, &tuple_list_relations)) goto done;

	// Unpack sizes
	screen_sizes_seq = PySequence_Fast (tuple_list_screen_sizes, "screen sizes not a sequence"); if (screen_sizes_seq == NULL) goto done;
	nb_screen = PySequence_Fast_GET_SIZE (screen_sizes_seq);
	screen_sizes = calloc (nb_screen, sizeof (struct coord_t));
	relations = calloc (nb_screen * nb_screen, sizeof (int));
	if (screen_sizes == NULL || relations == NULL) { PyErr_SetNone (PyExc_MemoryError); goto done; }

	for (i = 0; i < nb_screen; ++i) {
		PyObject * tuple = PySequence_Fast (PySequence_Fast_GET_ITEM (screen_sizes_seq, i), "screen size not a sequence"); if (tuple == NULL) goto done;
		if (PySequence_Fast_GET_SIZE (tuple) == 2) {
			screen_sizes[i].x = PyInt_AsLong (PySequence_Fast_GET_ITEM (tuple, 0));
			screen_sizes[i].y = PyInt_AsLong (PySequence_Fast_GET_ITEM (tuple, 1));
		} else { PyErr_SetString (PyExc_ValueError, "screen size not a sequence of pairs"); }
		Py_DECREF (tuple); if (PyErr_Occurred ()) goto done;
	}

	// Unpack relations
	relations_seq = PySequence_Fast (tuple_list_relations, "relations not a sequence"); if (relations_seq == NULL) goto done;
	Py_ssize_t nb_rel = PySequence_Fast_GET_SIZE (relations_seq);
	for (i = 0; i < nb_rel; ++i) {
		int sa, c, sb;
		PyObject * tuple = PySequence_Fast (PySequence_Fast_GET_ITEM (relations_seq, i), "relations not a sequence of 3-uple"); if (tuple == NULL) goto done;
		if (PySequence_Fast_GET_SIZE (tuple) == 3) {
			sa = PyInt_AsLong (PySequence_Fast_GET_ITEM (tuple, 0));
			c = PyInt_AsLong (PySequence_Fast_GET_ITEM (tuple, 1));
			sb = PyInt_AsLong (PySequence_Fast_GET_ITEM (tuple, 2));
		} else { PyErr_SetString (PyExc_ValueError, "screen size not a sequence of pairs"); }
		Py_DECREF (tuple);
		if (PyErr_Occurred () || !relation_add (nb_screen, relations, sa, c, sb)) goto done;
	}

	// Compute
	if (isl_compute_screen_positions (screen_max_width, screen_max_height, nb_screen, screen_sizes, relations)) {
		Py_INCREF (Py_None);
		ret_screen_pos_list = Py_None;
	}
done:
	Py_XDECREF (screen_sizes_seq); Py_XDECREF (relations_seq);
	free (screen_sizes); free (relations);
	return ret_screen_pos_list;
}

PyDoc_STRVAR (compute_screen_positions_doc,
		"Computes screen positions from:\n"
		"- (w, h) : screen maximum sizes\n"
		"- [(w0, h0), ...] : screens sizes\n"
		"- [(sA, constraint, sB), ...] : sequence of relation between screens\n"
		"Returns:\n"
		"[(x0, y0), ...] : sequence of coordinates for screens\n"
		);

/* ---------------------- Module defintion ------------------ */

static PyMethodDef slam_util_methods[] = {
	{ "compute_screen_positions", compute_screen_positions, METH_VARARGS, compute_screen_positions_doc },
	{ NULL, NULL, 0, NULL }
};

PyMODINIT_FUNC initslam_util (void) {
	(void) Py_InitModule ("slam_util", slam_util_methods);
}

