from pyomo.environ import *
import pandas as pd
import sys
from calvin import *

# Run as: python main-annual.py 0.25
# (Requires 25% of active capacity as carryover constraint)

eop = None

for i in range(1922,2004):

  print('\nNow running WY %d' % i)

  calvin = CALVIN('calvin/data/annual/linksWY%d.csv' % i, ic=eop)
  # calvin.inflow_multiplier(0.9)

  # omit this next line to use the EOP constraints from the 82-year optimal run
  calvin.eop_constraint_multiplier(float(sys.argv[1]))

  calvin.create_pyomo_model(debug_mode=True, debug_cost=2e8)
  # calvin.solve_pyomo_model(solver='glpk', nproc=1, debug_mode=True, maxiter=15)
  calvin.solve_pyomo_model(solver='cplex', nproc=32, debug_mode=True, maxiter=25)

  calvin.create_pyomo_model(debug_mode=False)
  # calvin.solve_pyomo_model(solver='glpk', nproc=1, debug_mode=False)
  calvin.solve_pyomo_model(solver='cplex', nproc=32, debug_mode=False)

  # this will append to results files
  eop = postprocess(calvin.df, calvin.model, 
                    resultdir='results-annual-'+sys.argv[1], annual=True) 

# this is only required as a separate step when running annual loop
aggregate_regions('results-annual-'+sys.argv[1])
