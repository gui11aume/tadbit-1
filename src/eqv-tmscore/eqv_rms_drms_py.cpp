#include "Python.h"
#include "eqv-drmsd-tadbit.cpp"
// #include <iostream>
// using namespace std;
//cout << "START" << endl << flush;

/* The function doc string */
PyDoc_STRVAR(rmsdRMSD_wrapper__doc__,
"From 2 lists of xyz positions, and a given threshold (nm), return the \n\
number of equivalent positions, the RMSD and the dRMSD.\n\
   :param xyz_a: first list of tuples of (x, y, z ) coordinates.\n\
   :param xyz_b: second list of tuples of (x, y, z ) coordinates.\n\
   :param dcutoff: distance cutoff to consider 2 particles as equivalent \n\
      in position (nm)\n\
   :param consistency: whether to get consistency per particle\n\
\n\
   :returns: a list with the number of equivalent positions, the RMSD and \n\
      the dRMSD, of the alignment. If consistency is True, returns list of \n\
      0 or 1 if a given particle is in equivalent position in both strands.\n\
");


static PyObject* rmsdRMSD_wrapper(PyObject* self, PyObject* args)
{
  PyObject *py_xA;
  PyObject *py_xB;
  PyObject *py_yA;
  PyObject *py_yB;
  PyObject *py_zA;
  PyObject *py_zB;
  int size;
  float thres;
  int consistency=0;
 
  if (!PyArg_ParseTuple(args, "OOOOOOifi", &py_xA, &py_yA, &py_zA, &py_xB, &py_yB, 
			&py_zB, &size, &thres, &consistency))
    return NULL;
 
  float **xyzA;
  float **xyzB;
  int i;
  xyzA = new float*[size];
  xyzB = new float*[size];

  for (i=0; i<size; i++){
    xyzB[i] = new float[3];
    memset(xyzB[i], 0, 3*sizeof(float));
    xyzA[i] = new float[3];
    memset(xyzA[i], 0, 3*sizeof(float));
    xyzA[i][0] = PyFloat_AS_DOUBLE(PyList_GET_ITEM(py_xA, i));
    xyzB[i][0] = PyFloat_AS_DOUBLE(PyList_GET_ITEM(py_xB, i));
    xyzA[i][1] = PyFloat_AS_DOUBLE(PyList_GET_ITEM(py_yA, i));
    xyzB[i][1] = PyFloat_AS_DOUBLE(PyList_GET_ITEM(py_yB, i));
    xyzA[i][2] = PyFloat_AS_DOUBLE(PyList_GET_ITEM(py_zA, i));
    xyzB[i][2] = PyFloat_AS_DOUBLE(PyList_GET_ITEM(py_zB, i));
  }
  float rms, drms;

  int *cons_list;
  cons_list = new int[size];

  int eqv;
  rmsdRMSD(xyzA, xyzB, size, thres, eqv, rms, drms, cons_list, consistency);

  PyObject * py_result = NULL;
  if (consistency){
    py_result = PyList_New(size);
    for (i=0; i<size; i++)
      PyList_SetItem(py_result, i, PyInt_FromLong(cons_list[i]));
  }else{
    py_result = PyList_New(3);
    PyList_SetItem(py_result, 0, PyInt_FromLong(eqv));
    PyList_SetItem(py_result, 1, PyFloat_FromDouble(rms));
    PyList_SetItem(py_result, 2, PyFloat_FromDouble(drms));
  }

  // free
  delete[] cons_list;
  for (int i=0; i<size; i++){
    delete[] xyzA[i];
    delete[] xyzB[i];
  }
  delete[] xyzA;
  delete[] xyzB;

  // give it to me
  return py_result;
}
 
static PyMethodDef Eqv_rms_drmsMethods[] =
  {
    {"rmsdRMSD_wrapper", rmsdRMSD_wrapper, METH_VARARGS, 
    rmsdRMSD_wrapper__doc__},
    {NULL, NULL, 0, NULL}
  };

PyMODINIT_FUNC
 
initeqv_rms_drms(void)
{
  (void) Py_InitModule3("eqv_rms_drms", Eqv_rms_drmsMethods, 
			"Functions to compaire two Chromatin strands.");
}
