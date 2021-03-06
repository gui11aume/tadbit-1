"""
05 Jul 2013


"""
from pytadbit.imp.CONFIG import CONFIG, NROUNDS, STEPS, LSTEPS
from pytadbit.imp.structuralmodels import StructuralModels
from pytadbit.imp.impmodel import IMPmodel
from scipy import polyfit
from math import fabs, pow as power
from cPickle import load, dump
import multiprocessing as mu
from sys import stdout
from os.path import exists


import IMP.core
import IMP.algebra
import IMP.display
from IMP.container import ListSingletonContainer
from IMP import Model
from IMP import FloatKey
import IMP.kernel

IMP.set_check_level(IMP.NONE)
IMP.set_log_level(IMP.SILENT)


def generate_3d_models(zscores, resolution, start=1, n_models=5000, n_keep=1000,
                       close_bins=1, n_cpus=1, keep_all=False, verbose=0,
                       outfile=None, config=CONFIG['dmel_01'], values=None):
    """
    This function generates three-dimensional models starting from Hi-C data. 
    The final analysis will be performed on the n_keep top models.
    
    :param zscores: the dictionary of the Z-score values calculated from the 
       Hi-C pairwise interactions
    :param resolution:  number of nucleotides per Hi-C bin. This will be the 
       number of nucleotides in each model's particle
    :param 5000 n_models: number of models to generate
    :param 1000 n_keep: number of models used in the final analysis (usually 
       the top 20% of the generated models). The models are ranked according to
       their objective function value (the lower the better)
    :param False keep_all: whether or not to keep the discarded models (if 
       True, models will be stored under StructuralModels.bad_models) 
    :param 1 close_bins: number of particles away (i.e. the bin number 
       difference) a particle pair must be in order to be considered as
       neighbors (e.g. 1 means consecutive particles)
    :param n_cpus: number of CPUs to use
    :param False verbose: if set to True, information about the distance, force
       and Z-score between particles will be printed
    :param None values: the normalized Hi-C data in a list of lists (equivalent 
       to a square matrix)
    :param CONFIG['dmel_01'] config: a dictionary containing the standard 
       parameters used to generate the models. The dictionary should contain
       the keys kforce, lowrdist, maxdist, upfreq and lowfreq. Examples can be
       seen by doing:

       ::

         from pytadbit.imp.CONFIG import CONFIG

         where CONFIG is a dictionary of dictionaries to be passed to this function:

       :::

         CONFIG = {
          'dmel_01': {
              # Paramaters for the Hi-C dataset from:
              'reference' : 'victor corces dataset 2013',

              # Force applied to the restraints inferred to neighbor particles
              'kforce'    : 5,

              # Minimum distance between two non-bonded particles
              'lowrdist'  : 100,

              # Maximum experimental contact distance
              'maxdist'   : 600, # OPTIMIZATION: 500-1200

              # Maximum threshold used to decide which experimental values have to be
              # included in the computation of restraints. Z-score values greater than upfreq
              # and less than lowfreq will be included, while all the others will be rejected
              'upfreq'    : 0.3, # OPTIMIZATION: min/max Z-score

              # Minimum thresholds used to decide which experimental values have to be
              # included in the computation of restraints. Z-score values bigger than upfreq
              # and less that lowfreq will be include, whereas all the others will be rejected
              'lowfreq'   : -0.7 # OPTIMIZATION: min/max Z-score

              # Space occupied by a nucleotide (nm)
              'scale'     : 0.005

              }
          }

    :returns: a TheeDeeModels object

    """

    # Main config parameters
    global CONFIG
    CONFIG = config
    
    # Particles initial radius
    global RADIUS
    RADIUS = resolution * CONFIG['scale']
    CONFIG['lowrdist'] = RADIUS * 2.
    

    # get SLOPE and regression for all particles of the z-score data
    global SLOPE, INTERCEPT
    zsc_vals = [zscores[i][j] for i in zscores for j in zscores[i]]
    zmin = min(zsc_vals)
    zmax = max(zsc_vals)
    SLOPE, INTERCEPT   = polyfit([zmin, zmax], [CONFIG['maxdist'],
                                                CONFIG['lowrdist']], 1)
    # get SLOPE and regression for neighbors of the z-score data
    global NSLOPE, NINTERCEPT
    xarray = [zscores[i][j] for i in zscores for j in zscores[i]
              if abs(int(i) - int(j)) <= (close_bins + 1)]
    yarray = [RADIUS * 2 for _ in xrange(len(xarray))]
    NSLOPE, NINTERCEPT = polyfit(xarray, yarray, 1)

    # zsc = set([int (k) for k in zscores.keys()] +
    #           reduce(lambda x, y: x + y,
    #                  [[int (k) for k in j.keys()] for j in zscores.values()]
    #                  ))

    
    global LOCI, NLOCI
    LOCI = range(max([int (k) for k in zscores.keys()] +
                     reduce(lambda x, y: x + y,
                            [[int (k) for k in j.keys()]
                             for j in zscores.values()])) + 1)
    NLOCI = len(LOCI)
    
    # Z-scores
    global PDIST
    PDIST = zscores

    # random inital number
    global START
    START = start

    models, bad_models = multi_process_model_generation(
        n_cpus, n_models, n_keep, keep_all, verbose)
    
    if outfile:
        if exists(outfile):
            old_models, old_bad_models = load(open(outfile))
        else:
            old_models, old_bad_models = {}, {}
        models.update(old_models)
        bad_models.update(old_bad_models)
        out = open(outfile, 'w')
        dump((models, bad_models), out)
        out.close()
    else:
        return StructuralModels(NLOCI, models, bad_models, resolution,
                                original_data=values, config=CONFIG)


def multi_process_model_generation(n_cpus, n_models, n_keep, keep_all, verbose):
    """
    Parallelize the
    :func:`pytadbit.imp.imp_model.StructuralModels.generate_IMPmodel`.

    :param n_cpus: number of CPUs to use
    :param n_models: number of models to generate
    """
    pool = mu.Pool(n_cpus)
    jobs = {}
    for rand_init in xrange(START, n_models + START):
        jobs[rand_init] = pool.apply_async(_do_it, args=(rand_init, verbose))

    pool.close()
    pool.join()

    results = []
    for rand_init in xrange(START, n_models + START):
        results.append((rand_init, jobs[rand_init].get()))

    models = {}
    bad_models = {}
    for i, (_, m) in enumerate(
        sorted(results, key=lambda x: x[1]['objfun'])[:n_keep]):
        models[i] = m
    if keep_all:
        for i, (_, m) in enumerate(
        sorted(results, key=lambda x: x[1]['objfun'])[n_keep:]):
            bad_models[i+n_keep] = m
    return models, bad_models


def _do_it(num, verbose):
    """
    Workaround in order pass to the multiprocessing queue a pickable object.
    """
    return generate_IMPmodel(num, verbose)


def generate_IMPmodel(rand_init, verbose=0):
    """
    :param rand_init: random number kept as model key, for reproducibility.

    :returns: a model, that is a dictionary with the log of the objective
       function value optimization, and the coordinates of each particles.

    """
    IMP.random_number_generator.seed(rand_init)

    log_energies = []
    model = {'rk'    : IMP.FloatKey("radius"),
             'model' : Model(),
             'ps'    : None,
             'pps'   : None}
    model['ps'] = ListSingletonContainer(IMP.core.create_xyzr_particles(
        model['model'], NLOCI, RADIUS, 100000))
    model['ps'].set_name("")

    # initialize each particles
    for i in range(0, NLOCI):
        p = model['ps'].get_particle(i)
        p.set_name(str(LOCI[i]))
        # radius = diameter/2 (0.01/2)
        # computed following the relationship with the 30nm vs 40nm fiber
        newrk = RADIUS
        p.set_value(model['rk'], newrk)

    # Restraints between pairs of LOCI proportional to the PDIST
    # model['pps']  = IMP.ParticlePairs() # this was used for IMP
    # version: 847e65d44da7d06718bcad366b09264c818752d5
    model['pps']  = IMP.kernel.ParticlePairsTemp()

    # CALL BIG FUNCTION
    addAllHarmonics(model, verbose=verbose)

    # Setup an excluded volume restraint between a bunch of particles
    # with radius
    r = IMP.core.ExcludedVolumeRestraint(model['ps'], CONFIG['kforce'])
    model['model'].add_restraint(r)

    if verbose == 3:
        print "Total number of restraints: %i" % (
            model['model'].get_number_of_restraints())

    # Set up optimizer
    lo = IMP.core.ConjugateGradients()
    lo.set_model(model['model'])
    o = IMP.core.MonteCarloWithLocalOptimization(lo, LSTEPS)
    o.set_return_best(True)
    fk = IMP.core.XYZ.get_xyz_keys()
    ptmp = model['ps'].get_particles()
    mov = IMP.core.NormalMover(ptmp, fk, 0.25)
    o.add_mover(mov)
    # o.add_optimizer_state(log)

    # Optimizer's parameters
    if verbose == 3:
        print "nrounds: %i, steps: %i, lsteps: %i" % (NROUNDS, STEPS, LSTEPS)

    # Start optimization and save an VRML after 100 MC moves
    log_energies.append(model['model'].evaluate(False))
    if verbose == 3:
        print "Start", log_energies[-1]

    #"""simulated_annealing: preform simulated annealing for at most nrounds
    # iterations. The optimization stops if the score does not change more than
    #    a value defined by endLoopValue and for stopCount iterations. 
    #   @param endLoopCount = Counter that increments if the score of two models
    # did not change more than a value
    #   @param stopCount = Maximum values of iteration during which the score
    # did not change more than a specific value
    #   @paramendLoopValue = Threshold used to compute the value  that defines
    # if the endLoopCounter should be incremented or not"""
    # IMP.fivec.simulatedannealing.partial_rounds(m, o, nrounds, steps)
    endLoopCount = 0
    stopCount = 10
    endLoopValue = 0.00001
    # alpha is a parameter that takes into account the number of particles in
    # the model (NLOCI).
    # The multiplier (in this case is 1.0) is used to give a different weight
    # to the number of particles
    alpha = 1.0 * NLOCI
    # During the firsts hightemp iterations, do not stop the optimization
    hightemp = int(0.025 * NROUNDS)
    for i in range(0, hightemp):
        temperature = alpha * (1.1 * NROUNDS - i) / NROUNDS
        o.set_kt(temperature)
        log_energies.append(o.optimize(STEPS))
        if verbose == 3:
            print i, log_energies[-1], o.get_kt()
    # After the firsts hightemp iterations, stop the optimization if the score
    # does not change by more than a value defined by endLoopValue and
    # for stopCount iterations
    lownrj = log_energies[-1]
    for i in range(hightemp, NROUNDS):
        temperature = alpha * (1.1 * NROUNDS - i) / NROUNDS
        o.set_kt(temperature)
        log_energies.append(o.optimize(STEPS))
        if verbose == 3:
            print i, log_energies[-1], o.get_kt()
        # Calculate the score variation and check if the optimization
        # can be stopped or not
        if lownrj > 0:
            deltaE = fabs((log_energies[-1] - lownrj) / lownrj)
        else:
            deltaE = log_energies[-1]
        if (deltaE < endLoopValue and endLoopCount == stopCount):
            break
        elif (deltaE < endLoopValue and endLoopCount < stopCount):
            endLoopCount += 1
            lownrj = log_energies[-1]
        else:
            endLoopCount = 0
            lownrj = log_energies[-1]
    #"""simulated_annealing_full: preform simulated annealing for nrounds
    # iterations"""
    # # IMP.fivec.simulatedannealing.full_rounds(m, o, nrounds, steps)
    # alpha = 1.0 * NLOCI
    # for i in range(0,nrounds):
    #    temperature = alpha * (1.1 * nrounds - i) / nrounds
    #    o.set_kt(temperature)
    #    e = o.optimize(steps)
    #    print str(i) + " " + str(e) + " " + str(o.get_kt())
    # Print the IMP score of the final model

    log_energies.append(model['model'].evaluate(False))
    if verbose >=1:
        if verbose >= 2 or not rand_init % 100:
            print 'Model %s IMP Objective Function: %s' % (
                rand_init, log_energies[-1])
    x, y, z, radius = (FloatKey("x"), FloatKey("y"),
                       FloatKey("z"), FloatKey("radius"))

    result = IMPmodel({'log_objfun' : log_energies,
                       'objfun'     : log_energies[-1],
                       'x'          : [],
                       'y'          : [],
                       'z'          : [],
                       'radius'     : [],
                       'cluster'    : 'Singleton',
                       'rand_init'  : rand_init})
    for part in model['ps'].get_particles():
        result['x'].append(part.get_value(x))
        result['y'].append(part.get_value(y))
        result['z'].append(part.get_value(z))
        result['radius'].append(part.get_value(radius))
        if verbose == 3:
            print (part.get_name(), part.get_value(x), part.get_value(y),
                   part.get_value(z), part.get_value(radius))
    return result


def addAllHarmonics(model, verbose=False):
    """
    Add harmonics to all pair of particles.
    """
    for i in range(0, NLOCI):
        p1 = model['ps'].get_particle(i)
        x = p1.get_name()
        num_loci1 = int(x)

        for j in range(i+1, NLOCI):
            p2 = model['ps'].get_particle(j)
            y = p2.get_name()
            num_loci2 = int(y)

            log = addHarmonicPair(model, p1, p2, x, y, j, num_loci1, num_loci2)
            if verbose:
                stdout.write(log)
                

def addHarmonicPair(model, p1, p2, x, y, j, num_loci1, num_loci2):
    """
    add harmonic to a given pair of particles

    :param model: a model dictionary that contains IMP model, singleton
       containers...
    :param p1: first particle
    :param p2: second particle
    :param x: first particle name
    :param y: second particle name
    :param j: id of second particle
    :param num_loci1: index of the first particle
    :param num_loci2: index of the second particle
    """
    seqdist = num_loci2 - num_loci1
    log = ''
    # SHORT RANGE DISTANCE BETWEEN TWO CONSECUTIVE LOCI
    if (seqdist == 1):
        if (x in PDIST and y in PDIST[x]
            and float(PDIST[x][y]) > 0):
            kforce1 = CONFIG['kforce']
            log += addHarmonicNeighborsRestraints(model, p1, p2, kforce1)
            #print "harmo1\t%s\t%s\t%f\t%f" % ( x, y, dist1, kforce1)
        else:
            kforce1 = CONFIG['kforce']
            dist1 = (p1.get_value(model['rk']) + p2.get_value(model['rk']))
            log += addHarmonicUpperBoundRestraints(model, p1, p2,
                                                   dist1, kforce1)
            #print "upper1\t%s\t%s\t%f\t%f" % ( x, y, dist1, kforce1)

            # SHORT RANGE DISTANCE BETWEEN TWO SEQDIST = 2
    elif (seqdist == 2):
        if (x in PDIST and y in PDIST[x] and float(PDIST[x][y]) > 0):
            kforce2 = CONFIG['kforce']
            log += addHarmonicNeighborsRestraints(model, p1, p2, kforce2)
        else:
            p3 = model['ps'].get_particle(j-1)
            kforce2 = CONFIG['kforce']
            dist2 = (p1.get_value(model['rk']) + p2.get_value(model['rk'])
                    + 2.0 * p3.get_value(model['rk']))
            log += addHarmonicUpperBoundRestraints(model, p1, p2,
                                                   dist2, kforce2)
            #print "upper2\t%s\t%s\t%f\t%f" % ( x, y, dist2, kforce2)

    else:

        # LONG RANGE DISTANCE DISTANCE BETWEEN TWO NON-CONSECUTIVE LOCI
        if (x in PDIST and y in PDIST[x]):
            # FREQUENCY > UPFREQ
            if (float(PDIST[x][y]) > CONFIG['upfreq']):
                kforce3 = kForce(float(PDIST[x][y]))
                log += addHarmonicRestraints(model, p1, p2,
                                             float(PDIST[x][y]), kforce3)
                #print "harmo3\t%s\t%s\t%f\t%f" % ( x, y, dist3, kforce3)
            # FREQUENCY > LOW THIS HAS TO BE THE THRESHOLD FOR
            # "PHYSICAL INTERACTIONS"
            elif (float(PDIST[x][y]) < CONFIG['lowfreq']):
                kforce3 = kForce(float(PDIST[x][y]))
                log += addHarmonicLowerBoundRestraints(model, p1, p2,
                                                       float(PDIST[x][y]),
                                                       kforce3)
           #print "lower3\t%s\t%s\t%f\t%f" % ( x, y, dist3, kforce3)
            else:
                return log

        # X IN PDIST BY Y NOT IN PDIST[X]
        elif (x in PDIST): # and y not in PDIST[x]):
            if (num_loci2 > num_loci1):
                prev_num = num_loci2 - 1
                pnext_num = num_loci2 + 1
            else:
                prev_num = num_loci1 - 1
                pnext_num = num_loci1 + 1
            prev = str(prev_num)
            pnext = str(pnext_num)

            if (prev in PDIST[x] and pnext in PDIST[x]):
                virt_freq = (float(PDIST[x][prev]) +
                             float(PDIST[x][pnext])) / 2.0
                if (virt_freq > CONFIG['upfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicRestraints(model, p1, p2,
                                                 virt_freq, kforce4)
                    #print "harmo4\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                elif (virt_freq < CONFIG['lowfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicLowerBoundRestraints(model, p1, p2,
                                                           virt_freq, kforce4)
                    #print "lower4\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                else:
                    return log

            elif (pnext in PDIST[x]):
                virt_freq = float(PDIST[x][pnext])
                if (virt_freq > CONFIG['upfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicRestraints(model, p1, p2,
                                                 virt_freq, kforce4)
                    #print "harmo5\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                elif (virt_freq < CONFIG['lowfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicLowerBoundRestraints(model, p1, p2,
                                                           virt_freq, kforce4)
                    #print "lower5\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                else:
                    return log

            elif (prev in PDIST[x]):
                virt_freq = float(PDIST[x][prev])
                if (virt_freq > CONFIG['upfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicRestraints(model, p1, p2,
                                                 virt_freq, kforce4)
                    #print "harmo6\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                elif (virt_freq < CONFIG['lowfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicLowerBoundRestraints(model, p1, p2,
                                                           virt_freq, kforce4)
                    #print "lower6\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                else:
                    return log

            else:
                return log

        # MISSING DATA (X)
        else:
            if (num_loci2 > num_loci1):
                xprev_num = num_loci1 - 1
                xpnext_num = num_loci1 + 1
                prev_num = num_loci2 - 1
                pnext_num = num_loci2 + 1
            else:
                xprev_num = num_loci2 - 1
                xpnext_num = num_loci2 + 1
                prev_num = num_loci1 - 1
                pnext_num = num_loci1 + 1
            xprev = str(xprev_num)
            xpnext = str(xpnext_num)
            prev = str(prev_num)
            pnext = str(pnext_num)

            # CASE 1
            if (xprev in PDIST and xpnext in PDIST):
                if (y in PDIST[xprev] and y in PDIST[xpnext]):
                    virt_freq = (float(PDIST[xprev][y]) +
                                 float(PDIST[xpnext][y]) ) / 2.0
                    kforce4 = 0.5 * kForce(virt_freq)
                elif (y in PDIST[xprev]):
                    virt_freq = float(PDIST[xprev][y])
                    kforce4 = 0.5 * kForce(virt_freq)
                elif (y in PDIST[xpnext]):
                    virt_freq = float(PDIST[xpnext][y])
                    kforce4 = 0.5 * kForce(virt_freq)
                else:
                    return log

                if (virt_freq > CONFIG['upfreq']):
                    log += addHarmonicRestraints(model, p1, p2,
                                                 virt_freq, kforce4)
                elif (virt_freq < CONFIG['lowfreq']):
                    log += addHarmonicLowerBoundRestraints(model, p1, p2,
                                                           virt_freq, kforce4)
                    #print "lower7\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                else:
                    return log

            # CASE 2
            elif (xprev in PDIST and y in PDIST[xprev]):
                virt_freq = float(PDIST[xprev][y])
                if (virt_freq > CONFIG['upfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicRestraints(model, p1, p2,
                                                 virt_freq, kforce4)
                    #print "harmo8\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                elif (virt_freq < CONFIG['lowfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicLowerBoundRestraints(model, p1, p2,
                                                           virt_freq, kforce4)
                    #print "lower8\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                else:
                    return log

            # CASE 3
            elif (xpnext in PDIST and y in PDIST[xpnext]):
                virt_freq = float(PDIST[xpnext][y])
                if (virt_freq > CONFIG['upfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicRestraints(model, p1, p2,
                                                 virt_freq, kforce4)
                    #print "harmo9\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                elif (virt_freq < CONFIG['lowfreq']):
                    kforce4 = 0.5 * kForce(virt_freq)
                    log += addHarmonicLowerBoundRestraints(model, p1, p2,
                                                           virt_freq, kforce4)
                    #print "lower9\t%s\t%s\t%f\t%f" % ( x, y, dist4, kforce4)
                else:
                    return log

            else:
                return log
    return log


def distConseq12(freq):
    """
    Function mapping the Z-scores into distances for neighbor fragments
    """
    return (NSLOPE * freq) + NINTERCEPT


def distance(freq):
    """
    Function mapping the Z-scores into distances for non-neighbor fragments
    """
    return (SLOPE * freq) + INTERCEPT


def addHarmonicNeighborsRestraints(model, p1, p2, kforce):
    dist = distConseq12(PDIST[p1.get_name()][p2.get_name()])
    p = IMP.ParticlePair(p1, p2)
    model['pps'].append(p)
    dr = IMP.core.DistanceRestraint(IMP.core.Harmonic(dist, kforce),p1, p2)
    model['model'].add_restraint(dr)
    return "addHn\t%s\t%s\t%f\t%f\n" % (p1.get_name(), p2.get_name(),
                                        dist, kforce)


def addHarmonicUpperBoundRestraints(model, p1, p2, dist, kforce):
    #dist = (p1.get_value(rk) + p2.get_value(rk))
    p = IMP.ParticlePair(p1, p2)
    model['pps'].append(p)
    dr = IMP.core.DistanceRestraint(IMP.core.HarmonicUpperBound(dist, kforce),
                                    p1, p2)
    model['model'].add_restraint(dr)
    return "addHu\t%s\t%s\t%f\t%f\n" % (p1.get_name(), p2.get_name(),
                                        dist, kforce)


def addHarmonicRestraints(model, p1, p2, freq, kforce):
    dist = distance(freq)
    p = IMP.ParticlePair(p1, p2)
    model['pps'].append(p)
    dr = IMP.core.DistanceRestraint(IMP.core.Harmonic(dist, kforce),p1, p2)
    model['model'].add_restraint(dr)
    return "addHa\t%s\t%s\t%f\t%f\n" % (p1.get_name(), p2.get_name(),
                                        dist, kforce)

def addHarmonicLowerBoundRestraints(model, p1, p2, freq, kforce):
    dist = distance(freq)
    p = IMP.ParticlePair(p1, p2)
    model['pps'].append(p)
    dr = IMP.core.DistanceRestraint(IMP.core.HarmonicLowerBound(dist, kforce),
                                    p1, p2)
    model['model'].add_restraint(dr)
    return "addHl\t%s\t%s\t%f\t%f\n" % (p1.get_name(), p2.get_name(),
                                        dist, kforce)


def kForce(freq):
    """
    Function to assign to each restraint a force proportional to the underlying
    experimental value.
    """
    return power(fabs(freq), 0.5 )


