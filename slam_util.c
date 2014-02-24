#include <Python.h>

#include <isl/set.h>

/* ----------- Compute screen coordinates with Isl --------- */

// relation_dir enum
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

// Helpers for relation array
static inline int * relation_p (int nb_sc, int * rels, int x, int y) { return &rels[x + y * nb_sc]; }
static int relation_add (int nb_sc, int * rels, int sa, int c, int sb) {
	if (!(0 <= sa && sa < nb_sc) || !(0 <= sb && sb < nb_sc)) { PyErr_SetString (PyExc_IndexError, "relation screen index out of bounds"); return 0; }
	if (!(0 < c && c < C_NB)) { PyErr_SetString (PyExc_ValueError, "relation direction is invalid"); return 0; }
	if (sa <= sb) { *relation_p (nb_sc, rels, sa, sb) = c; }
	else { *relation_p (nb_sc, rels, sb, sa) = c; }
	return 1;
}

struct coord_t { long x, y; }; // Coord struct

static int compute_screen_positions_isl (long screen_max_width, long screen_max_height, int nb_screen, struct coord_t * screen_sizes, int * relations) {
	int i, j;
	printf ("screen_max_size = (%d,%d)\n", screen_max_width, screen_max_height);
	for (i = 0; i < nb_screen; ++i)
		printf ("screen_%d_size = (%d,%d)\n", i, screen_sizes[i].x, screen_sizes[i].y);
	for (j = 0; j < nb_screen; ++j)
		for (i = 0; i < j; ++i) {
			const char * s = relation_str (*relation_p (nb_screen, relations, i, j)); if (s == NULL) return 0;
			printf ("relation (%d, %s, %d)\n", i, s, j);
		}

	// Isl stuff
	isl_ctx * ctx = isl_ctx_alloc ();

	isl_ctx_free (ctx);
	return 1;
}

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
	if (compute_screen_positions_isl (screen_max_width, screen_max_height, nb_screen, screen_sizes, relations)) {
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

