#reads the metrics CSVs produced by simulation.py (metrics_latency.csv, metrics_utilization.csv,
#metrics_migrations.csv) and by run_mechanism_demo.py (mechanism_demo.csv), all expected in the
#project root, and saves the resulting charts as PNGs under figures/.
#run from the project root, after a simulation run and the mechanism demo:
#   python3 simulation.py
#   python3 scripts/run_mechanism_demo.py
#   python3 scripts/generate_figures.py
import csv
import os
from collections import defaultdict

import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGURES_DIR = os.path.join(ROOT, "figures")
os.makedirs(FIGURES_DIR, exist_ok=True)

#palette shared with the evaluation dashboard, so figures read consistently across deliverables
COLOR_EDGE = "#0e9488"
COLOR_CLOUD = "#3b6ea5"
COLOR_BUDGET = "#4361c8"
COLOR_MIGRATION = "#c93f56"
COLOR_GOOD = "#238a4d"
COLOR_GRID = "#d8dee2"
COLOR_INK = "#182129"

plt.rcParams.update({
	"figure.dpi": 150,
	"savefig.dpi": 150,
	"font.size": 10.5,
	"axes.edgecolor": COLOR_GRID,
	"axes.labelcolor": COLOR_INK,
	"text.color": COLOR_INK,
	"xtick.color": COLOR_INK,
	"ytick.color": COLOR_INK,
	"axes.titleweight": "bold",
	"axes.grid": True,
	"grid.color": COLOR_GRID,
	"grid.linewidth": 0.6,
})


def readCSV(filename):
	path = os.path.join(ROOT, filename)
	if not os.path.exists(path):
		print("skipping {}: {} not found (run simulation.py / run_mechanism_demo.py first)".format(filename, path))
		return None
	with open(path) as f:
		return list(csv.DictReader(f))


#Figure 1: latency compliance per control loop - min/avg/max measured latency (ms) against
#the loop's latency budget
def plotLatencyCompliance(rows):
	if not rows:
		return
	byLoop = defaultdict(list)
	budgetByLoop = {}
	for r in rows:
		loop = r["controlLoop"]
		byLoop[loop].append(float(r["latency"]) * 1000)#s -> ms
		if r["maxLatency"]:
			budgetByLoop[loop] = float(r["maxLatency"]) * 1000

	loops = sorted(byLoop)
	fig, ax = plt.subplots(figsize=(7, 4))
	x = range(len(loops))
	mins = [min(byLoop[l]) for l in loops]
	avgs = [sum(byLoop[l]) / len(byLoop[l]) for l in loops]
	maxs = [max(byLoop[l]) for l in loops]

	ax.bar(x, avgs, width=0.5, color=COLOR_EDGE, zorder=3, label="média")
	ax.vlines(x, mins, maxs, color=COLOR_INK, linewidth=1.4, zorder=4, label="faixa mín-máx")
	for xi, loop in zip(x, loops):
		if loop in budgetByLoop:
			ax.hlines(budgetByLoop[loop], xi - 0.35, xi + 0.35, color=COLOR_BUDGET, linewidth=1.8, linestyle="--", zorder=5)
			ax.text(xi + 0.37, budgetByLoop[loop], "orçamento {:.0f} ms".format(budgetByLoop[loop]), color=COLOR_BUDGET, fontsize=9, va="center")

	ax.set_xticks(list(x))
	ax.set_xticklabels(["loop {}".format(l) for l in loops])
	ax.set_ylabel("latência (ms)")
	ax.set_title("Compliance de latência por loop de controle")
	ax.set_ylim(0, max([budgetByLoop.get(l, 0) for l in loops] + maxs) * 1.25)
	ax.legend(loc="upper left", frameon=False)
	fig.tight_layout()
	fig.savefig(os.path.join(FIGURES_DIR, "latency_compliance.png"))
	plt.close(fig)


#Figure 2: node utilization (load/capacity ratio, %) sampled over simulated time. With 10 Edge nodes
#in this scenario, plotting one line per node is unreadable, so this aggregates by role instead:
#the Edge band (min-max across all 10, plus their average) shows how unevenly loaded individual
#Edges get even when the scenario as a whole is stable; Cloud and the Switch average are single lines
def plotNodeUtilization(rows):
	if not rows:
		return
	byRole = defaultdict(lambda: defaultdict(list))#role -> node -> [(t, ratio%), ...]
	capacityByNode = {}
	for r in rows:
		node = r["node"]
		role = "Cloud" if node.startswith("Cloud") else ("Edge" if node.startswith("Edge") else "Switch")
		byRole[role][node].append((float(r["time"]), float(r["ratio"]) * 100))
		capacityByNode[node] = float(r["capacity"])

	fig, ax = plt.subplots(figsize=(8, 4.4))

	if "Edge" in byRole:
		times = sorted({t for series in byRole["Edge"].values() for t, _ in series})
		avgEdge, minEdge, maxEdge = [], [], []
		for t in times:
			valuesAtT = [dict(series)[t] for series in byRole["Edge"].values() if t in dict(series)]
			avgEdge.append(sum(valuesAtT) / len(valuesAtT))
			minEdge.append(min(valuesAtT))
			maxEdge.append(max(valuesAtT))
		ax.fill_between(times, minEdge, maxEdge, color=COLOR_EDGE, alpha=0.15, label="faixa min-máx entre os {} Edges".format(len(byRole["Edge"])))
		ax.plot(times, avgEdge, color=COLOR_EDGE, linewidth=2, marker="o", markersize=3, label="média dos Edges")

	if "Cloud" in byRole:
		for node, series in byRole["Cloud"].items():
			series = sorted(series)
			ax.plot([p[0] for p in series], [p[1] for p in series], color=COLOR_CLOUD, linewidth=2, marker="o", markersize=3, label="{} (cap. {:.0f})".format(node, capacityByNode[node]))

	if "Switch" in byRole:
		times = sorted({t for series in byRole["Switch"].values() for t, _ in series})
		avgSwitch = []
		for t in times:
			valuesAtT = [dict(series)[t] for series in byRole["Switch"].values() if t in dict(series)]
			avgSwitch.append(sum(valuesAtT) / len(valuesAtT))
		ax.plot(times, avgSwitch, color="#c9791f", linewidth=1.4, linestyle=":", label="média dos {} Switches".format(len(byRole["Switch"])))

	ax.set_xlabel("tempo simulado (s)")
	ax.set_ylabel("utilização (%)")
	ax.set_title("Utilização dos nós ao longo da simulação, por papel")
	ax.set_ylim(-2, 105)
	ax.legend(loc="upper right", frameon=False, fontsize=8.5)
	fig.tight_layout()
	fig.savefig(os.path.join(FIGURES_DIR, "node_utilization.png"))
	plt.close(fig)


#Figure 3: isolated ControlPlane mechanism demo - where the RT (vBBU) and NonRT (rApp) functions
#get hosted as the Edge node's load is pushed past its capacity, with migrations flagged.
#Excludes the final (blocked) step of mechanism_demo.csv - that one is its own figure below
def plotMechanismDemo(rows):
	if not rows:
		return
	rows = [r for r in rows if r.get("blocked", "False") == "False"]
	steps = [int(r["step"]) for r in rows]
	edgeLoad = [int(r["edgeLoad"]) for r in rows]
	edgeCapacity = int(rows[0]["edgeCapacity"])
	rtHost = [0 if r["rtHost"].startswith("Edge") else 1 for r in rows]
	nonRtHost = [0 if r["nonRtHost"].startswith("Edge") else 1 for r in rows]
	migrated = [r["migrated"] == "True" for r in rows]

	fig, (axTop, axBottom) = plt.subplots(2, 1, figsize=(7.5, 5), sharex=True, height_ratios=[1, 1.4])

	axTop.step(steps, edgeLoad, where="mid", color=COLOR_INK, linewidth=1.8)
	axTop.axhline(edgeCapacity, color=COLOR_MIGRATION, linestyle="--", linewidth=1.4)
	axTop.text(steps[-1], edgeCapacity, " capacidade do Edge = {}".format(edgeCapacity), color=COLOR_MIGRATION, fontsize=9, va="bottom", ha="right")
	axTop.set_ylabel("Edge.currentLoad")
	fig.suptitle("Mecanismo de posicionamento: carga do Edge força o fallback para a Cloud", fontsize=12.5, x=0.02, ha="left")

	axBottom.step(steps, rtHost, where="mid", color=COLOR_EDGE, linewidth=2.2, label="função RT (vBBU) — loop com budget de 10 ms")
	axBottom.step(steps, nonRtHost, where="mid", color=COLOR_CLOUD, linewidth=2.2, linestyle=":", label="função NonRT (rApp) — sem budget rígido")
	for i, m in enumerate(migrated):
		if m:
			axBottom.scatter([steps[i]], [rtHost[i]], color=COLOR_MIGRATION, s=70, zorder=5, marker="^")
			axBottom.annotate("migração", (steps[i], rtHost[i]), textcoords="offset points", xytext=(0, 10), ha="center", color=COLOR_MIGRATION, fontsize=8.5)

	axBottom.set_yticks([0, 1])
	axBottom.set_yticklabels(["Edge:0", "Cloud:0"])
	axBottom.set_xlabel("passo do teste (carga do Edge forçada manualmente)")
	axBottom.set_xticks(steps)
	axBottom.legend(loc="center right", frameon=False, fontsize=8.5)
	fig.tight_layout(rect=[0, 0, 1, 0.94])
	fig.savefig(os.path.join(FIGURES_DIR, "placement_mechanism.png"))
	plt.close(fig)


#Figure 4: migrations recorded in the real simulation run vs. in the isolated mechanism demo
#(the demo's forced overload is what actually exercises the fallback logic)
def plotMigrationCount(realRows, demoRows):
	realCount = len(realRows) if realRows else 0
	demoCount = sum(1 for r in demoRows if r["migrated"] == "True") if demoRows else 0
	labels = ["execução real\n(cenário atual, 20 RRHs)", "teste isolado\n(6 decisões controladas)"]
	counts = [realCount, demoCount]
	colors = [COLOR_CLOUD, COLOR_EDGE]

	fig, ax = plt.subplots(figsize=(6.2, 4.6))
	bars = ax.bar(labels, counts, color=colors, width=0.5)
	ax.set_yscale("log")
	ax.set_ylabel("migrações registradas (escala log)")
	ax.set_title("Migrações registradas")
	for b, c in zip(bars, counts):
		ax.text(b.get_x() + b.get_width() / 2, c, str(c), ha="center", va="bottom", fontweight="bold")
	fig.text(0.5, 0.01, "Na execução real cada RRH reavalia seu posicionamento a cada quadro (1000x/s) -\nmigrações frequentes são o mecanismo funcionando, não uma anomalia.", ha="center", fontsize=8.5, color=COLOR_INK)
	fig.tight_layout(rect=[0, 0.1, 1, 1])
	fig.savefig(os.path.join(FIGURES_DIR, "migration_count.png"))
	plt.close(fig)


#Figure 5: energy consumption and active-node count across the isolated mechanism demo's steps -
#consolidating the RT/NonRT functions onto fewer active nodes (Edge saturated -> everything on
#Cloud) is what old/graph.py's overallPowerConsumption() rewarded; energyAlwaysOn is the "every
#candidate node stays powered on" baseline the heuristic is meant to save against
def plotEnergyAndActiveNodes(demoRows, realEnergyRows):
	if not demoRows:
		return
	steps = [int(r["step"]) for r in demoRows]
	activeCount = [int(r["activeCount"]) for r in demoRows]
	energy = [float(r["energy"]) for r in demoRows]
	energyAlwaysOn = [float(r["energyAlwaysOn"]) for r in demoRows]
	totalCount = 2#the demo's candidateNodes are always exactly [Edge:0, Cloud:0]

	fig, (axTop, axBottom) = plt.subplots(2, 1, figsize=(7.5, 5.2), sharex=True, height_ratios=[1, 1.4])

	axTop.step(steps, activeCount, where="mid", color=COLOR_INK, linewidth=2)
	axTop.set_ylabel("nós ativos")
	axTop.set_yticks(range(0, totalCount + 1))
	axTop.set_ylim(-0.3, totalCount + 0.5)
	fig.suptitle("Nós ativos e consumo de energia sob consolidação", fontsize=12.5, x=0.02, ha="left")

	axBottom.step(steps, energyAlwaysOn, where="mid", color=COLOR_GRID, linewidth=2.4, linestyle="--", label="baseline: todos os nós sempre ligados")
	axBottom.step(steps, energy, where="mid", color=COLOR_GOOD, linewidth=2.4, label="ControlPlane (LatencyAwarePolicy)")
	axBottom.fill_between(steps, energy, energyAlwaysOn, step="mid", color=COLOR_GOOD, alpha=0.12)

	maxSavingsIdx = max(range(len(steps)), key=lambda i: energyAlwaysOn[i] - energy[i])
	if energyAlwaysOn[maxSavingsIdx] > energy[maxSavingsIdx]:
		savingsPct = (energyAlwaysOn[maxSavingsIdx] - energy[maxSavingsIdx]) / energyAlwaysOn[maxSavingsIdx] * 100
		midY = (energy[maxSavingsIdx] + energyAlwaysOn[maxSavingsIdx]) / 2
		axBottom.annotate("-{:.0f}% de energia\n(Edge desligado)".format(savingsPct), (steps[maxSavingsIdx], midY),
			ha="center", va="center", color=COLOR_GOOD, fontsize=9.5, fontweight="bold",
			bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=COLOR_GOOD, alpha=0.9))

	realAvgEnergy = sum(float(r["energy"]) for r in realEnergyRows) / len(realEnergyRows) if realEnergyRows else None
	realAvgAlwaysOn = sum(float(r["energyAlwaysOn"]) for r in realEnergyRows) / len(realEnergyRows) if realEnergyRows else None
	if realAvgEnergy is not None and realAvgAlwaysOn:
		realSavingsPct = (realAvgAlwaysOn - realAvgEnergy) / realAvgAlwaysOn * 100
		axBottom.text(0.02, 0.06, "Execução real (cenário atual): energia média {:.0f} de {:.0f} sempre-ligado\n({:.0f}% de economia observada ao longo da simulação).".format(realAvgEnergy, realAvgAlwaysOn, realSavingsPct),
			transform=axBottom.transAxes, fontsize=8.5, color=COLOR_INK, va="bottom", ha="left",
			bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor=COLOR_GRID))

	axBottom.set_ylabel("energia (u.a.)")
	axBottom.set_xlabel("passo do teste isolado (carga do Edge/Cloud forçada manualmente)")
	axBottom.set_xticks(steps)
	axBottom.set_ylim(min(energy) * 0.9, max(energyAlwaysOn) * 1.14)
	axBottom.legend(loc="upper center", frameon=False, fontsize=8.5, ncol=1)
	fig.tight_layout(rect=[0, 0, 1, 0.94])
	fig.savefig(os.path.join(FIGURES_DIR, "energy_active_nodes.png"))
	plt.close(fig)


#Figure 6: blocking probability - the real run's light load never blocks a placement request;
#the isolated demo's overload step saturates both Edge and Cloud at once to show what a blocked
#request looks like (network.LatencyAwarePolicy.decide returning None), akin to the "lost traffic"
#old/graph.py's getBlockingProbability computed from a min-cost flow
def plotBlockingProbability(realLatencyRows, realBlockingRows, demoRows):
	realAttempted = (len(realLatencyRows) if realLatencyRows else 0) + (len(realBlockingRows) if realBlockingRows else 0)
	realBlocked = len(realBlockingRows) if realBlockingRows else 0
	realRate = (realBlocked / realAttempted * 100) if realAttempted else 0.0

	overloadStep = [r for r in demoRows if r.get("blocked") == "True"] if demoRows else []
	demoAttempted = len(overloadStep) * 2 if overloadStep else 0#2 functions (RT + NonRT) placed per step
	demoBlocked = demoAttempted#both are blocked in the overload step by construction
	demoRate = (demoBlocked / demoAttempted * 100) if demoAttempted else 0.0

	labels = ["execução real\n(cenário atual)", "teste isolado\n(Edge + Cloud saturados)"]
	rates = [realRate, demoRate]
	colors = [COLOR_GOOD if realRate == 0 else COLOR_MIGRATION, COLOR_MIGRATION if demoRate else COLOR_GOOD]

	fig, ax = plt.subplots(figsize=(5.5, 3.8))
	bars = ax.bar(labels, rates, color=colors, width=0.5)
	ax.set_ylabel("probabilidade de bloqueio (%)")
	ax.set_title("Bloqueio: carga real vs. saturação total forçada")
	ax.set_ylim(0, 115)
	for b, rate, blocked, attempted in zip(bars, rates, [realBlocked, demoBlocked], [realAttempted, demoAttempted]):
		ax.text(b.get_x() + b.get_width() / 2, rate, "{:.0f}%\n({}/{})".format(rate, blocked, attempted), ha="center", va="bottom", fontweight="bold", fontsize=9.5)
	fig.tight_layout()
	fig.savefig(os.path.join(FIGURES_DIR, "blocking_probability.png"))
	plt.close(fig)


if __name__ == "__main__":
	plotLatencyCompliance(readCSV("metrics_latency.csv"))
	plotNodeUtilization(readCSV("metrics_utilization.csv"))
	plotMechanismDemo(readCSV("mechanism_demo.csv"))
	plotMigrationCount(readCSV("metrics_migrations.csv"), readCSV("mechanism_demo.csv"))
	plotEnergyAndActiveNodes(readCSV("mechanism_demo.csv"), readCSV("metrics_energy.csv"))
	plotBlockingProbability(readCSV("metrics_latency.csv"), readCSV("metrics_blocking.csv"), readCSV("mechanism_demo.csv"))
	print("figures written to {}".format(FIGURES_DIR))
