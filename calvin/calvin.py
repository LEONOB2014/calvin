from pyomo.environ import *
from pyomo.opt import TerminationCondition
import numpy as np
import pandas as pd
import os

class CALVIN():

  def __init__(self, linksfile, ic=None):
    df = pd.read_csv(linksfile)
    df['link'] = df.i.map(str) + '_' + df.j.map(str) + '_' + df.k.map(str)
    df.set_index('link', inplace=True)

    self.df = df
    self.linksfile = os.path.splitext(linksfile)[0] # filename w/o extension

    # self.T = len(self.df)
    SR_stats = pd.read_csv('calvin/data/SR_stats.csv', index_col=0).to_dict()
    self.min_storage = SR_stats['min']
    self.max_storage = SR_stats['max']

    if ic:
      self.apply_ic(ic)

    # a few network fixes to make things work
    self.add_ag_region_sinks()
    self.fix_hydropower_lbs()

    self.nodes = pd.unique(df[['i','j']].values.ravel()).tolist()
    self.links = list(zip(df.i,df.j,df.k))
    self.networkcheck() # make sure things aren't broken
    

  def apply_ic(self, ic):
    for k in ic:
      ix = (self.df.i.str.contains('INITIAL') &
            self.df.j.str.contains(k))
      self.df.loc[ix, ['lower_bound','upper_bound']] = ic[k]

  def inflow_multiplier(self, proj):

  	# This function is essential for running climate change scenarios in CALVIN.
  	# Function pulls in a csv with mutlipliers for every CALVIN rim inflow at each month. An example is provided in the "data" folder called sample-multipliers.csv.
  	# In this function, the same multipliers are used for each year of the model run. Further code development could include using different multipliers for every year.

    # read in multipliers
    mult = pd.read_csv('calvin/data/multipliers/multipliers_%s.csv' % proj, index_col=0, header=0)
    months = ['10-31','11-30','12-31','1-31','2-28','3-31','4-30','5-31','6-30','7-31','8-31','9-30']
    
    # iterate over rim inflows
    for key in mult.index:
      for m in months:

      	# boolean to find the rim inflow at the month specified
        ix = (self.df.i.str.contains('INFLOW') & self.df.i.str.contains(m) & self.df.j.str.contains(key))
        
        # apply multiplier for given rim inflow
        self.df.loc[ix, ['lower_bound','upper_bound']] *= mult.loc[key,m]

      # The minimum instream flow requirement (MIF) from Grant Lake (GNT) to Mono Lake (ML) is fixed at the GNT rim inflow.
      # When changes are made to GNT inflow, the same multiplier needs to be applied to the GNT-ML links to avoid further infeasabilities.
      # We've had problems in the past where solution would not converge due to small debug flows caused by Mono Lake MIF.

      if 'GNT' in key:
        ix = (self.df.i.str.contains(key) & self.df.j.str.contains('SR_ML'))
        row_iterator = self.df.loc[ix].iterrows()

        for row in row_iterator:
          iz = (self.df.i.str.contains('INFLOW') & self.df.j.str.contains(row[1]['i']))
          iy = (self.df.i.str.contains(row[1]['i']) & self.df.j.str.contains(row[1]['j']))
          if self.df.loc[iy,['lower_bound']].values[0] > self.df.loc[iz,['lower_bound']].values[0]:
            self.df.loc[iy, ['lower_bound']] = self.df.loc[iz, ['lower_bound']].values[0]
            #print('Fixed ML lower bound')

    print('Inflows adjusted for climate projection')
  
  def yolobypass_ub(self):

  	# This function increases the Yolo Bypass upper bound. In the original Python CALVIN model, had a low upper bound which caused infeasabilities. This fix was recommended by Mustafa Dogan.

    ix = (self.df.i.str.contains('C20') & self.df.j.str.contains('D55'))
    self.df.loc[ix,'upper_bound'] = 1e9


  def water_availability(self, multiplier,linksfile):

  	# This function multiplies all CALVIN inflows by the multiplier provided.
  	# This was used in Max Fefer's MS thesis to adjust water availability for a sensitivity analysis. 

    mbah = pd.read_csv(linksfile)
    ix = self.df.i.str.contains('INFLOW')
    
    # A modifier "mod" is needed to ensure inflows are changed correctly
    div = mbah.loc[mbah.i.str.contains('INFLOW'), 'lower_bound'].values.sum()

    #Get yearly sums instead of 82 year sum.
    mod = div/self.df.loc[ix, 'lower_bound'].values.sum()

    self.df.loc[ix, ['lower_bound','upper_bound']] *= multiplier*mod





  def eop_constraint_multiplier(self, x):

  	# This function imposes a multiplier for end of period storage at specified reservoirs in SR_stats.csv (SR_stats.csv is located in the nested folder "data").
  	# Multiplier should only be from 0 to 1. Outside this range exceeds min/max reservoir storage.
  	

  	# Optional: Save carryover storage values for easy access later using "matrix" dataframe below. 
    # matrix = pd.DataFrame(index=self.max_storage,columns=['carryover'])
    # print(matrix)


    for k in self.max_storage:
      ix = (self.df.i.str.contains(k) &
            self.df.j.str.contains('FINAL'))
      lb = self.min_storage[k] + (self.max_storage[k]-self.min_storage[k])*x

      self.df.loc[ix,'lower_bound'] = lb
      self.df.loc[ix,'upper_bound'] = self.max_storage[k]

      # matrix['carryover'][k] = self.df.loc[ix,'upper_bound'].values[0]
    
    # matrix.to_csv('GAH.csv')

  def eop_constraint_multiplier_bywateryeartype(self, i, scenario):
  	
  	# Still experimental. 
  	# Function works, but model results have not been feasible. More work required.
  	# Idea here is to impose a carryover storage constraint based upon CDEC water year type.
  	# The carryover storage for each reservoir (and water year type) is the median of historically observed carryover storages from CDEC for a given reservoir water year type. 
  	# Model results for this experiment are included in the "carryover-lf" folder.

    reservoirs = pd.read_csv('calvin/data/carryover/reservoirs_reindex_forcarryover.csv',index_col=0)
    
    # CDEC determines water year type (WYT) for 2 river basins, Sacramento River (SR) and San Joaquin River (SJR)
    # reservoirs in CALVIN regions 1 and 2 use SR WYT and regions 3, 4, and 5 use SJR WYT.

    SR_WYT = pd.read_csv('calvin/data/carryover/WYT_SR.csv', index_col=0)
    SJR_WYT = pd.read_csv('calvin/data/carryover/WYT_SJR.csv', index_col=0)

    # read in previously calculated carryover storage values for each reservoir and WYT.

    carryover = pd.read_csv('calvin/data/carryover/carryover_storage.csv',index_col=0)
    
    for res in reservoirs.index:
      print(res)
      print(scenario)

      if reservoirs['loc'][res] == 'SR':
        wyt = SR_WYT[scenario][i]
      else:
        wyt = SJR_WYT[scenario][i]

      new_carryover = carryover[wyt][res]
      print(new_carryover)

      # Apply carryover storage at reservoir on 9-30-FINAL link

      ix = (self.df.i.str.contains('SR_%s.%s-09-30' % (res,i)) & self.df.j.str.contains('FINAL'))
      print(self.df.loc[ix,'lower_bound'])

      # We placed the statements below to only allow the script to decrease carryover storage from the existing values in CALVIN.
      # 
      if self.df.loc[ix,'lower_bound'].values[0] > new_carryover:
        self.df.loc[ix,['lower_bound','upper_bound']] = new_carryover
        print(self.df.loc[ix,['lower_bound','upper_bound']])
      else:
        continue


  def no_gw_overdraft(self):
    pass
    #impose constraints..every year?

  def networkcheck(self):
    nodes = self.nodes
    links = self.df.values

    num_in = {n: 0 for n in nodes}
    num_out = {n: 0 for n in nodes}
    lb_in = {n: 0 for n in nodes} 
    lb_out = {n: 0 for n in nodes}
    ub_in = {n: 0 for n in nodes} 
    ub_out = {n: 0 for n in nodes}

    # loop over links
    for l in links:
      lb = float(l[5])
      ub = float(l[6])
      num_in[l[1]] += 1
      lb_in[l[1]] += lb
      ub_in[l[1]] += ub
      num_out[l[0]] += 1
      lb_out[l[0]] += lb
      ub_out[l[0]] += ub

      if lb > ub:
        raise ValueError('lb > ub for link %s' % (l[0]+'-'+l[1]))
    
    for n in nodes:
      if num_in[n] == 0 and n not in ['SOURCE','SINK']:
        raise ValueError('no incoming link for ' + n)
      if num_out[n] == 0 and n not in ['SOURCE','SINK']:
        raise ValueError('no outgoing link for ' + n)

      if ub_in[n] < lb_out[n]:
        raise ValueError('ub_in < lb_out for %s (%d < %d)' % (n, ub_in[n], lb_out[n]))
      if lb_in[n] > ub_out[n]:
        raise ValueError('lb_in > ub_out for %s (%d > %d)' % (n, lb_in[n], ub_out[n]))

  def add_ag_region_sinks(self):
    # hack to get rid of surplus water at no cost
    df = self.df
    links = df[df.i.str.contains('HSU') & ~df.j.str.contains('DBUG')].copy(deep=True)
    if not links.empty:
      maxub = links.upper_bound.max()
      links.j = links.apply(lambda l: 'SINK.'+l.i.split('.')[1], axis=1)
      links.cost = 0.0
      links.amplitude = 1.0
      links.lower_bound = 0.0
      links.upper_bound = maxub
      links['link'] = links.i.map(str) + '_' + links.j.map(str) + '_' + links.k.map(str)
      links.set_index('link', inplace=True)
      self.df = self.df.append(links.drop_duplicates())


  def fix_hydropower_lbs(self):
    # storage piecewise links > 0 should have 0.0 lower bound
    # the k=0 pieces should always have lb = dead pool
    def get_lb(link):
      if link.i.split('.')[0] == link.j.split('.')[0]:
        if link.k > 0:
          return 0.0
        elif link.i.split('.')[0] in self.min_storage:
          return min(self.min_storage[link.i.split('.')[0]], link.lower_bound)
      return link.lower_bound

    ix = (self.df.i.str.contains('SR_') & self.df.j.str.contains('SR_'))
    self.df.loc[ix, 'lower_bound'] = self.df.loc[ix].apply(get_lb, axis=1)

  def remove_debug_links(self):
    df = self.df
    ix = df.index[df.index.str.contains('DBUG')]
    df.drop(ix, inplace=True, axis=0)
    self.nodes = pd.unique(df[['i','j']].values.ravel()).tolist()
    self.links = list(zip(df.i,df.j,df.k))
    return df


  def create_pyomo_model(self, debug_mode=False, debug_cost=2e7):

    # work on a local copy of the dataframe
    if not debug_mode and self.df.index.str.contains('DBUG').any():
      # previously ran in debug mode, but now done
      df = self.remove_debug_links()
      df.to_csv(self.linksfile + '-final.csv')

    else:
      df = self.df

    print('Creating Pyomo Model (debug=%s)' % debug_mode)

    model = ConcreteModel()

    model.N = Set(initialize=self.nodes)
    model.k = Set(initialize=range(15))
    model.A = Set(within=model.N*model.N*model.k, 
                  initialize=self.links, ordered=True)
    model.source = Param(initialize='SOURCE')
    model.sink = Param(initialize='SINK')

    def init_params(p):
      if p == 'cost' and debug_mode:
        return (lambda model,i,j,k: debug_cost 
                  if ('DBUG' in str(i)+'_'+str(j))
                  else 1.0)
      else:
        return lambda model,i,j,k: df.loc[str(i)+'_'+str(j)+'_'+str(k)][p]

    model.u = Param(model.A, initialize=init_params('upper_bound'), mutable=True)
    model.l = Param(model.A, initialize=init_params('lower_bound'), mutable=True)
    model.a = Param(model.A, initialize=init_params('amplitude'))
    model.c = Param(model.A, initialize=init_params('cost'))

    # The flow over each arc
    model.X = Var(model.A, within=Reals)

    # Minimize total cost
    def obj_fxn(model):
      return sum(model.c[i,j,k]*model.X[i,j,k] for (i,j,k) in model.A)
    model.total = Objective(rule=obj_fxn, sense=minimize)

    # Enforce an upper bound limit on the flow across each arc
    def limit_rule_upper(model, i, j, k):
      return model.X[i,j,k] <= model.u[i,j,k]
    model.limit_upper = Constraint(model.A, rule=limit_rule_upper)

    # Enforce a lower bound limit on the flow across each arc
    def limit_rule_lower(model, i, j, k):
      return model.X[i,j,k] >= model.l[i,j,k]
    model.limit_lower = Constraint(model.A, rule=limit_rule_lower)

    # To speed up creating the mass balance constraints, first
    # create dictionaries of arcs_in and arcs_out of every node
    # These are NOT Pyomo data, and Pyomo does not use "model._" at all
    arcs_in = {}
    arcs_out = {}

    def arc_list_hack(model, i,j,k):
      if j not in arcs_in:
        arcs_in[j] = []
      arcs_in[j].append((i,j,k))

      if i not in arcs_out:
        arcs_out[i] = []
      arcs_out[i].append((i,j,k))
      return [0]

    model._ = Set(model.A, initialize=arc_list_hack)

    # Enforce flow through each node (mass balance)
    def flow_rule(model, node):
      if node in [value(model.source), value(model.sink)]:
          return Constraint.Skip
      outflow  = sum(model.X[i,j,k]/model.a[i,j,k] for i,j,k in arcs_out[node])
      inflow = sum(model.X[i,j,k] for i,j,k in arcs_in[node])
      return inflow == outflow
    model.flow = Constraint(model.N, rule=flow_rule)

    model.dual = Suffix(direction=Suffix.IMPORT)

    self.model = model


  def solve_pyomo_model(self, solver='glpk', nproc=1, debug_mode=False, maxiter=30):
    from pyomo.opt import SolverFactory
    opt = SolverFactory(solver)

    if nproc > 1 and solver is not 'glpk':
      opt.options['threads'] = nproc
    
    if debug_mode:
      run_again = True
      i = 0
      vol_total = 0

      while run_again and i < maxiter:
        print('-----Solving Pyomo Model (debug=%s)' % debug_mode)
        self.results = opt.solve(self.model)
        print('Finished. Fixing debug flows...')
        run_again,vol = self.fix_debug_flows()
        i += 1
        vol_total += vol

      if run_again:
        print(('Warning: Debug mode maximum iterations reached.'
               ' Will still try to solve without debug mode.'))
      else:
        print('All debug flows eliminated (iter=%d, vol=%0.2f)' % (i,vol_total))

    else:
      print('-----Solving Pyomo Model (debug=%s)' % debug_mode)
      self.results = opt.solve(self.model, tee=False)

      if self.results.solver.termination_condition == TerminationCondition.optimal:
        print('Optimal Solution Found (debug=%s).' % debug_mode)
        self.model.solutions.load_from(self.results)
      else:
        raise RuntimeError('Problem Infeasible. Run again starting from debug mode.')


  def fix_debug_flows(self, tol=1e-7):

    df, model = self.df, self.model
    dbix = (df.i.str.contains('DBUGSRC') | df.j.str.contains('DBUGSNK'))
    debuglinks = df[dbix].values

    run_again = False
    vol_total = 0

    for dbl in debuglinks:
      s = tuple(dbl[0:3])

      if model.X[s].value > tol:
        run_again = True

        # if we need to get rid of extra water,
        # raise some upper bounds (just do them all)
        if 'DBUGSNK' in dbl[1]:
          raiselinks = df[(df.i == dbl[0]) & ~ df.j.str.contains('DBUGSNK')].values

          for l in raiselinks:
            s2 = tuple(l[0:3])
            iv = model.u[s2].value
            v = model.X[s].value*1.2
            model.u[s2].value += v
            vol_total += v
            #print('%s UB raised by %0.2f (%0.2f%%)' % (l[0]+'_'+l[1], v, v*100/iv))
            df.loc['_'.join(str(x) for x in l[0:3]), 'upper_bound'] = model.u[s2].value

        # if we need to bring in extra water
        # this is a much more common problem
        # want to avoid reducing carryover requirements. look downstream instead.
        max_depth = 10

        if 'DBUGSRC' in dbl[0]:
          vol_to_reduce = max(model.X[s].value*1.2, 0.5)
          #print('Volume to reduce: %.2e' % vol_to_reduce)

          children = [dbl[1]]
          for i in range(max_depth):
            children += df[df.i.isin(children)
                           & ~ df.j.str.contains('DBUGSNK')].j.tolist()
          children = set(children)
          reducelinks = (df[df.i.isin(children)
                           & (df.lower_bound > 0)]
                         .sort_values(by='lower_bound', ascending=False).values)

          if reducelinks.size == 0:
            raise RuntimeError(('Not possible to reduce LB on links'
                                ' with origin %s by volume %0.2f' % 
                                (dbl[1],vol_to_reduce)))

          for l in reducelinks:
            s2 = tuple(l[0:3])
            iv = model.l[s2].value
            dl = model.dual[model.limit_lower[s2]] if s2 in model.limit_lower else 0.0

            if iv > 0 and vol_to_reduce > 0 and dl > 1e6:
              v = min(vol_to_reduce, iv)
              # don't allow big reductions on carryover links
              carryover = ['SR_', 'INITIAL', 'FINAL', 'GW_']
              if any(c in l[0] for c in carryover) and any(c in l[1] for c in carryover): 
                v = min(v, max(25.0, 0.1*iv))
              model.l[s2].value -= v
              vol_to_reduce -= v
              vol_total += v
              #print('%s LB reduced by %.2e (%0.2f%%). Dual=%.2e' % (l[0]+'_'+l[1], v, v*100/iv, dl))
              df.loc['_'.join(str(x) for x in l[0:3]), 'lower_bound'] = model.l[s2].value
              
            if vol_to_reduce == 0:
              break

          #if vol_to_reduce > 0:
            #print('Debug -> %s: could not reduce full amount (%.2e left)' % (dbl[1],vol_to_reduce))

    self.df, self.model = df, model
    return run_again,vol_total