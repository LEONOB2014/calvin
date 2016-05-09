To run the optimization: 
```
pyomo --solver=glpk --report-timing --solver-suffix=dual pyvin.py CrazyMatrix.dat --json
```

Then run `postprocess.py` to format the results as time series. 