#include <Python.h>

/* Exception :
 * PyErr_SetString (err, str); return NULL;
 * err:
 *	PyExc_TypeError, PyExc_ValueError
 */

/* ----------- Compute screen coordinates with Isl --------- */

static PyObject * compute_screen_positions (PyObject * self, PyObject * args) {
	const char * s;
	if (!PyArg_ParseTuple (args, "s", &s))
		return NULL;
	printf ("TEST %s\n", s);
	Py_RETURN_NONE;
}

static char compute_screen_positions_doc[] =
"Computes screen positions from:\n"
"- (w, h) : screen maximum sizes\n"
"- [(w0, h0), ...] : screens sizes\n"
"- [(sA, sB, constraint), ...] : sequence of constraints\n"
"Returns:\n"
"[(x0, y0), ...] : sequence of coordinates for screens\n"
;

/* ---------------------- Module defintion ------------------ */

static PyMethodDef slam_util_methods[] = {
	{ "compute_screen_positions", compute_screen_positions, METH_VARARGS, compute_screen_positions_doc },
	{ NULL, NULL, 0, NULL }
};

PyMODINIT_FUNC initslam_util (void) {
	(void) Py_InitModule ("slam_util", slam_util_methods);
}

