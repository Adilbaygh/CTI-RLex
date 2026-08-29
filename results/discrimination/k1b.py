import sys; sys.path.insert(0,"src")
from leximin.dag import load_cti_benchmark, solve_cti_rlex
from leximin.dag.experiments import solve_robust_proportional

m=load_cti_benchmark("DATA/CacheValley_2025_Benchmark/benchmark.json")
R=solve_cti_rlex(m).guarantees; P=solve_robust_proportional(m).guarantees
keys=sorted(R)
sr=sorted(R[k] for k in keys); sp=sorted(P[k] for k in keys)
TOL=1e-9
print("i  sorted RLex   sorted PROP    diff")
first=None
for i,(a,b) in enumerate(zip(sr,sp),1):
    d=a-b
    mark=""
    if first is None and abs(d)>TOL:
        first=i; mark="  <-- FIRST DIFFERENCE"
    print(f"{i:2d}  {a:.6f}      {b:.6f}     {d:+.6f}{mark}")
print()
if first is None:
    print("VERDICT: identical sorted vectors")
else:
    better = "CTI-RLex" if sr[first-1] > sp[first-1] else "PROP-BR"
    print(f"VERDICT: sorted vectors first differ at position {first}; {better} is higher there")
    print(f"         => sort_up(rho_RLex) {'>' if better=='CTI-RLex' else '<'}_lex sort_up(rho_PROP)")
print(f"positions where RLex is strictly higher: {sum(1 for a,b in zip(sr,sp) if a>b+TOL)}")
print(f"positions where PROP is strictly higher: {sum(1 for a,b in zip(sr,sp) if b>a+TOL)}")
print(f"claimants at the common floor: RLex={sum(1 for v in sr if abs(v-sr[0])<=TOL)}  PROP={sum(1 for v in sp if abs(v-sp[0])<=TOL)}")
