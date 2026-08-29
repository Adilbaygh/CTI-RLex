import json, time, sys
sys.path.insert(0, "src")
from leximin.dag import load_cti_benchmark, solve_cti_rlex
from leximin.dag.experiments import solve_robust_proportional, solve_utilitarian, lp_dimensions

for name, path in [("Little Bear (v2, 3 claimants)", "DATA/LittleBearRiver_2025_Benchmark/benchmark.json"),
                   ("Cache Valley (v3, 10 claimants)", "DATA/CacheValley_2025_Benchmark/benchmark.json")]:
    print("="*78); print(name)
    m = load_cti_benchmark(path)
    print("  LP dims:", lp_dimensions(m))
    t=time.time(); rlex = solve_cti_rlex(m); t_r=time.time()-t
    t=time.time(); prop = solve_robust_proportional(m); t_p=time.time()-t
    R = rlex.guarantees; P = prop.guarantees
    keys = sorted(R)
    sr = sorted(round(R[k],6) for k in keys)
    sp = sorted(round(P[k],6) for k in keys)
    delta = sum(R[k]-P[k] for k in keys)
    nplus = sum(1 for k in keys if R[k] > P[k] + 1e-9)
    print(f"  CTI-RLex levels     : {len(rlex.leximin_levels)}  distinct values={len(set(sr))}")
    for lv in rlex.leximin_levels:
        print(f"      theta*={lv.level:.6f}  blocked={list(lv.blocked_claimants)}")
    print(f"  sorted rho (RLex)   : {sr}")
    print(f"  sorted rho (PROP-BR): {sp}")
    print(f"  min guarantee       : RLex={min(sr):.6f}  PROP={min(sp):.6f}")
    print(f"  LEXIMIN GAIN  delta = {delta:.6f}   strictly improved n+ = {nplus} of {len(keys)}")
    print(f"  nominal delivery    : RLex={rlex.nominal_beneficial_delivery:.1f}  PROP={prop.nominal_beneficial_delivery:.1f}")
    print(f"  runtime             : RLex={t_r:.2f}s  PROP={t_p:.2f}s")
    print(f"  max residual        : {max(rlex.residuals.values()):.2e}")
