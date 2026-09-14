# 5GPy

This fork extends the original 5GPy with the 3-layer architecture (User Application / O-RAN
Applications / Fronthaul) and the dynamic Edge-Cloud placement module used by the
"Aprendizado de Máquina para Alocação Dinâmica de Funções de Rede O-RAN e vBBU em um Continuum
Edge-Cloud no 6G" dissertation. See "Architecture extensions" below for what was added on top of
the original simulator.

Dependencies:

5GPy runs with Python 3.6.9 (tested here on 3.12 as well). Install the dependencies with:

-pip install -r requirements.txt

or individually: simpy, networkx, scipy, psutil, numpy.

All simulation configurations must be put at:

-configurations.xml

The initialization of a simulation is done at:

-simulation.py

To run a simulation, execute:

-python3 simulation.py

The classes representing the network topology elements are within:

-network.py

Utility methods can be found and must be placed at:

-utiliy.py

## Architecture extensions

The default `configurations.xml` is now a scaled-up scenario: 20 RRHs, 10 Edge nodes and 1 Cloud
node (one IoT use case, as before). `configurations_test_sample.xml` keeps the original minimal
4-RRH/1-Edge "Test Sample" scenario used while first building this architecture - copy it over
`configurations.xml` to go back to it.

- **Layer 1 - User Application**: `network.UseCase` carries a use case's `maxLatency`/`minBandwidth`/
  `trafficPattern` requirements (configured under `<UseCases>`); each `UserEquipment` is created
  with the use case served by its RRH.
- **Layer 2 - O-RAN Applications**: `network.NonRTRIC`, `network.NearRTRIC` and `network.RTRIC`
  (configured under `<ORANFunctions>`) represent the Non-RT RIC/rApps, Near-RT RIC/xApps and RT-RIC.
  They are placed once at simulation bootstrap by the `ControlPlane`. Simulating their E2/A1 message
  traffic is not implemented yet.
- **Layer 3 - Fronthaul**: each `RRH` owns a `network.VBBU`, the placeable function that processes
  its baseband signal. Its host (`Edge:*`/`Cloud:*`, configured under `<ProcessingNodes>` with
  `role="Edge"`/`"Cloud"`) is re-evaluated by the `ControlPlane` on every uplink CPRI/eCPRI frame,
  which is what allows it to migrate between Edge and Cloud during the simulation.
- **Placement**: `network.ControlPlane` decides where to host every Layer 2/3 function through a
  pluggable `network.PlacementPolicy`. The current policy, `network.LatencyAwarePolicy`, is a simple
  heuristic (prefer Edge for RT/NearRT-loop functions, Cloud otherwise, least-loaded node with spare
  capacity). A trained ML/RL agent plugs in by implementing `PlacementPolicy.decide()` and being
  passed to `ControlPlane` in `simulation.py` - no other simulator code needs to change.
- **Metrics**: `utility.py` records latency-loop compliance, migrations, node utilization, blocking,
  active-node count and energy consumption during the run; `simulation.py` exports them to
  `metrics_latency.csv`, `metrics_migrations.csv`, `metrics_utilization.csv`, `metrics_blocking.csv`,
  `metrics_active_nodes.csv` and `metrics_energy.csv` at the end of `env.run()`. These last three
  carry forward the metrics from the group's prior Cloud-Fog work (`old/graph.py`'s
  `getBlockingProbability`, `countActNodes`, `overallPowerConsumption`):
  - **Blocking**: `network.LatencyAwarePolicy.decide()` returns `None` when no candidate node has
    spare capacity; `ControlPlane.placeFunction()` then records the blocking instead of forcing the
    function onto an overloaded node, and the RRH drops that uplink frame rather than sending it.
  - **Active nodes**: `ControlPlane` tracks which nodes currently host at least one function
    (`hostedFunctions`); `ControlPlane.activeNodes()` returns that live list.
  - **Energy**: each `EdgeNode`/`CloudNode` has an `activationPower` cost (configured under
    `<ProcessingNodes>`, same fog/cloud cost ratio as `old/graph.py`'s `costs` dict).
    `ControlPlane.energyConsumption()` sums it over active nodes only, or over every candidate node
    when called with `alwaysOn=True` - the "everything stays powered on" baseline the placement
    heuristic is meant to save against by consolidating functions onto fewer nodes.

## Scaling up

Going from 4 to tens of RRHs surfaced two real bugs in the placement logic, both fixed in
`network.py`/`simulation.py` rather than worked around:

1. **Thundering herd from deterministic tie-breaking.** `LatencyAwarePolicy.decide()` used to pick
   the minimum-load node with plain `min()`, which always resolves ties to the first candidate in
   list order. With one idle Edge that never mattered; with several equally-idle Edges (e.g. every
   node at load 0 when the simulation starts), *every* simultaneous caller picked the exact same
   node. Fixed by breaking ties randomly among every node at the minimum load.
2. **Global candidate pools flood transit traffic.** Every RRH used to be able to compete for
   literally any Edge node network-wide. Even after fixing (1), this routed a lot of traffic across
   multiple switch hops to reach whatever Edge looked momentarily least loaded, and the switches
   carrying that cross-network traffic became the real bottleneck before any Edge's own capacity
   was. `simulation.py` now restricts each RRH's candidates to nodes within `MAX_CANDIDATE_HOPS`
   (plus Cloud, always reachable) - both a bugfix and a more realistic model, since a real RRH can't
   reach an arbitrarily distant Edge site within the RT loop's latency budget anyway.

With both fixed, **20 RRHs / 10 Edges (2 RRHs/Edge) is stable** (100% RT compliance); the load sweep
below shows where it stops being stable.

## Load sweep

`scripts/run_load_sweep.py` sweeps RRHs/Edge from 1 to 6 (10 Edges fixed) and re-runs
`simulation.py` at each point - the same load-sweep methodology `old/simulator.py` used (24 traffic
levels) for the group's prior Cloud-Fog work. It found a sharp stability boundary: 1-2 RRHs/Edge
stay at ~100% RT compliance; from 3 RRHs/Edge on, latency keeps growing for as long as the
simulation runs (the queue never drains) and compliance collapses. This is a genuine capacity
result, not a placement-policy failure: `LatencyAwarePolicy` only gates *where* a new request goes,
it cannot make a node drain its queue faster than frames arrive.

```
python3 scripts/run_load_sweep.py         # writes sweep_results.csv (restores configurations.xml when done)
python3 scripts/generate_sweep_figures.py # reads it, writes figures/sweep_*.png
```

## Figures

`figures/` holds PNG charts generated from the metrics above, kept under version control as
reference plots for the dissertation. To regenerate all of them after changing the scenario or the
placement policy:

```
python3 simulation.py                     # writes metrics_*.csv for the scenario in configurations.xml
python3 scripts/run_mechanism_demo.py     # writes mechanism_demo.csv (isolated ControlPlane fallback/blocking test)
python3 scripts/generate_figures.py       # reads both, writes figures/*.png
python3 scripts/run_load_sweep.py         # writes sweep_results.csv (see "Load sweep" above)
python3 scripts/generate_sweep_figures.py # reads it, writes figures/sweep_*.png
```

From the default 20-RRH scenario:
- `latency_compliance.png` - measured latency (min/avg/max) per control loop against its budget.
- `node_utilization.png` - utilization over time, aggregated by role (min-max band across the 10
  Edges, Cloud, average of the 10 Switches) since plotting all 21 nodes individually isn't readable.
- `migration_count.png` - migrations in the real 20-RRH run (log scale) vs. the isolated demo.
- `blocking_probability.png` - blocking rate in the real run vs. the demo's forced total-saturation step.

From the isolated `run_mechanism_demo.py` test (an Edge's load stepped manually past its capacity,
then both Edge and Cloud saturated at once):
- `placement_mechanism.png` - Edge load rising past capacity, RT/NonRT function hosts, migrations.
- `energy_active_nodes.png` - active-node count and energy consumption (heuristic vs. always-on
  baseline) across the demo's steps, plus the real run's average for comparison.

From `run_load_sweep.py`'s sweep_results.csv:
- `sweep_compliance.png` - RT compliance vs. RRHs/Edge, marking the stable/overloaded regions.
- `sweep_latency_growth.png` - average latency in the first vs. second half of each run; parallel
  lines mean steady state was reached, diverging lines mean the queue is still growing.
- `sweep_active_nodes_energy.png` - active-node ratio and energy savings vs. RRHs/Edge.
- `sweep_migrations.png` - migrations vs. RRHs/Edge.

Please, when using 5GPy in your paper, thesis or dissertation, it is mandatory to cite the following reference:

@article{tinini20195gpy,
title={5GPy: A SimPy-based simulator for performance evaluations in 5G hybrid Cloud-Fog RAN architectures},
author={Tinini, Rodrigo Izidoro and dos Santos, Matias Rom{\'a}rio Pinheiro and Figueiredo, Gustavo Bittencourt and Batista, Daniel Mac{\^e}do},
journal={Simulation Modelling Practice and Theory},
pages={102030},
year={2019},
publisher={Elsevier}
}

If you have any questions, please contact me at: tinini at fei dot edu dot br
