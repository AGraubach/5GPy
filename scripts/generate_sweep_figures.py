#reads sweep_results.csv (written by scripts/run_load_sweep.py) and plots the existing metrics -
#RT compliance, latency growth, active-node ratio, energy savings, migrations - as a function of
#RRHs/Edge, the same load-sweep methodology old/simulator.py used (24 traffic levels) for the
#group's prior Cloud-Fog work. Saves PNGs under figures/.
#run from the project root, after scripts/run_load_sweep.py: python3 scripts/generate_sweep_figures.py
import csv
import os

import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGURES_DIR = os.path.join(ROOT, "figures")
os.makedirs(FIGURES_DIR, exist_ok=True)

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


def readSweep():
	path = os.path.join(ROOT, "sweep_results.csv")
	if not os.path.exists(path):
		print("sweep_results.csv not found - run scripts/run_load_sweep.py first")
		return None
	with open(path) as f:
		rows = list(csv.DictReader(f))
	rows.sort(key=lambda r: int(r["rrhPerEdge"]))
	return rows


#Figure: RT compliance vs. RRHs/Edge, with a marker for the stability boundary found while
#validating this scenario (stable up to 2/Edge, degrading from 3/Edge on)
def plotCompliance(rows):
	if not rows:
		return
	x = [int(r["rrhPerEdge"]) for r in rows]
	compliance = [float(r["rtComplianceRate"]) * 100 if r["rtComplianceRate"] else 0 for r in rows]

	fig, ax = plt.subplots(figsize=(7.5, 4.4))
	ax.plot(x, compliance, marker="o", color=COLOR_EDGE, linewidth=2.2, markersize=7)
	ax.axvspan(x[0] - 0.5, 2.5, color=COLOR_GOOD, alpha=0.08)
	ax.axvspan(2.5, x[-1] + 0.5, color=COLOR_MIGRATION, alpha=0.06)
	ax.text(1.2, 12, "estável", color=COLOR_GOOD, fontsize=9.5, fontweight="bold")
	ax.text(4.2, 12, "sobrecarregado", color=COLOR_MIGRATION, fontsize=9.5, fontweight="bold")
	ax.set_xticks(x)
	ax.set_xlabel("RRHs por Edge (10 Edges fixos)")
	ax.set_ylabel("compliance do loop RT (%)")
	ax.set_ylim(-5, 105)
	ax.set_title("Compliance de latência vs. carga oferecida por Edge")
	fig.tight_layout()
	fig.savefig(os.path.join(FIGURES_DIR, "sweep_compliance.png"))
	plt.close(fig)


#Figure: avg latency in the first vs. second half of each run - flat/parallel lines mean the system
#reached steady state; diverging lines mean the queue is still growing (unstable) at that load level
def plotLatencyGrowth(rows):
	if not rows:
		return
	x = [int(r["rrhPerEdge"]) for r in rows]
	firstHalf = [float(r["avgLatencyFirstHalfMs"]) if r["avgLatencyFirstHalfMs"] else 0 for r in rows]
	secondHalf = [float(r["avgLatencySecondHalfMs"]) if r["avgLatencySecondHalfMs"] else 0 for r in rows]

	fig, ax = plt.subplots(figsize=(7.5, 4.4))
	ax.plot(x, firstHalf, marker="o", color=COLOR_CLOUD, linewidth=2, label="1ª metade da execução")
	ax.plot(x, secondHalf, marker="o", color=COLOR_MIGRATION, linewidth=2, label="2ª metade da execução")
	ax.set_xticks(x)
	ax.set_xlabel("RRHs por Edge (10 Edges fixos)")
	ax.set_ylabel("latência média do loop RT (ms)")
	ax.set_title("Crescimento da latência: 1ª vs. 2ª metade de cada execução")
	ax.legend(frameon=False)
	fig.tight_layout()
	fig.savefig(os.path.join(FIGURES_DIR, "sweep_latency_growth.png"))
	plt.close(fig)


#Figure: active-node ratio and energy savings vs. RRHs/Edge
def plotActiveNodesAndEnergy(rows):
	if not rows:
		return
	x = [int(r["rrhPerEdge"]) for r in rows]
	activeRatio = [float(r["avgActiveNodeRatio"]) * 100 if r["avgActiveNodeRatio"] else 0 for r in rows]
	savings = [float(r["avgEnergySavingsRatio"]) * 100 if r["avgEnergySavingsRatio"] else 0 for r in rows]

	fig, (axTop, axBottom) = plt.subplots(2, 1, figsize=(7.5, 5.6), sharex=True)

	axTop.plot(x, activeRatio, marker="o", color=COLOR_CLOUD, linewidth=2)
	axTop.set_ylabel("nós ativos (% do total)")
	axTop.set_ylim(0, 105)
	fig.suptitle("Nós ativos e economia de energia vs. carga oferecida por Edge", fontsize=12.5, x=0.02, ha="left")

	axBottom.plot(x, savings, marker="o", color=COLOR_GOOD, linewidth=2)
	axBottom.set_ylabel("economia de energia (%)")
	axBottom.set_xlabel("RRHs por Edge (10 Edges fixos)")
	axBottom.set_xticks(x)
	axBottom.set_ylim(min(savings + [0]) - 5, max(savings + [10]) * 1.2)

	fig.tight_layout(rect=[0, 0, 1, 0.94])
	fig.savefig(os.path.join(FIGURES_DIR, "sweep_active_nodes_energy.png"))
	plt.close(fig)


#Figure: migration count vs. RRHs/Edge
def plotMigrations(rows):
	if not rows:
		return
	x = [int(r["rrhPerEdge"]) for r in rows]
	migrations = [int(r["migrationCount"]) for r in rows]

	fig, ax = plt.subplots(figsize=(7, 4))
	ax.plot(x, migrations, marker="o", color=COLOR_INK, linewidth=2)
	ax.set_xticks(x)
	ax.set_xlabel("RRHs por Edge (10 Edges fixos)")
	ax.set_ylabel("migrações registradas")
	ax.set_title("Migrações registradas vs. carga oferecida por Edge")
	fig.tight_layout()
	fig.savefig(os.path.join(FIGURES_DIR, "sweep_migrations.png"))
	plt.close(fig)


if __name__ == "__main__":
	rows = readSweep()
	plotCompliance(rows)
	plotLatencyGrowth(rows)
	plotActiveNodesAndEnergy(rows)
	plotMigrations(rows)
	print("sweep figures written to {}".format(FIGURES_DIR))
