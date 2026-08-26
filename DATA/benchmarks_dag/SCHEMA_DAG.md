# Leximin DAG benchmark schema (v0.1)

Input format for the generalized (DAG) leximin allocation solver. Differs from the earlier
rooted-tree benchmark: routing is a decision, so edges carry flow and consumers sit on nodes.

```jsonc
{
  "name": "cache_valley_2025",
  "meta": { ...provenance, units, calibration, year notes... },
  "periods": ["2005", ..., "2018"],          // K, ordered
  "nodes": { "n0": {"lon":.., "lat":..}, ... },   // V
  "sources": {                                 // S ⊆ V, with scarce supply per period
     "n61": { "Q_af": { "2005": 34591.0, ... } }   // Q_{k,s} gross supply (acre-feet)
  },
  "edges": [                                   // E, directed (already oriented → DAG)
     { "id":"e0", "from":"n..", "to":"n..",
       "type":"canal"|"pipe",                  // τ_e (heterogeneous)
       "capacity_af": 12345.6,                 // C_e gross capacity per season (acre-feet)
       "eta": 0.90 }                           // η_e conveyance efficiency ∈ (0,1]
  ],
  "consumers": [                               // F, each withdraws at a node
     { "id":"f0", "node":"n..", "weight":1.0,  // w_f (Stage-2)
       "demand_af": { "2005": 800.0, ... } }   // d_{k,f} net demand (acre-feet)
  ]
}
```

## Model mapping (see Model/MATHEMATICAL_MODEL.md)
- Flow conservation (C) at every node, per period; edge delivers η·q downstream.
- Stage 1 max–min λ*; full leximin; Stage 2 S*; Stage 3 Ω; PoF.
- `capacity_af` bounds gross flow entering the edge; `Q_af` bounds source injection;
  `demand_af` is the net requirement, `eta` the multiplicative loss.

## This instance (cache_valley_2025)
- 121 nodes, 124 edges (119 canal + 5 pipe), 1 source, 26 consumers (sink nodes), 14 periods (years).
- Capacities from real MaxCFS × season (180 d). η by type (literature: canal .90 / pipe .97).
- Demand anchored to source physical capacity (D_full = 0.75·cap·η ≈ 25,706 af), split across
  consumers ∝ incident canal capacity.
- Supply Q_k follows the REAL Cache Valley interannual withdrawal pattern (Utah Water Budget
  2005–2018), scaled to the network. 6 of 14 years are scarce (droughts 2014, 2017 the tightest,
  Q/need ≈ 0.79) → real supply-driven scarcity, not a capacity artifact.

## Honest labels
- **data:** topology, capacity, type (Utah Canals); acres (WRLU 2025); supply pattern &
  efficiency ratio (Utah Water Budget).
- **literature:** per-edge η split.
- **assumption/scenario:** demand distribution across nodes; demand anchoring level; season
  length; Stage-2 weights; land-use(2025)/water-budget(2005–2018) year mismatch (declared).
