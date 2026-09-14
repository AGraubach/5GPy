#sweeps the number of RRHs served by a fixed 10-Edge topology (i.e., RRHs/Edge, from light to
#heavy) and re-runs simulation.py at each point, the way old/simulator.py swept traffic load across
#24 timestamps in the group's prior Cloud-Fog work. At each point, summarizes the resulting
#metrics_*.csv into one row of sweep_results.csv - the input for scripts/generate_sweep_figures.py.
#
#This is the load dimension that actually matters for this simulator: while validating the scaled-up
#scenario, sweeping the Edge admission-capacity attribute alone turned out to be uninformative once
#offered load already exceeded the network's real (per-hop, sequential) service rate - capacity only
#gates *new* placements, it does not speed up how fast a node's queue drains. RRHs/Edge is what
#actually controls the offered-load-to-service-rate ratio, so it is what is swept here.
#
#run from the project root: python3 scripts/run_load_sweep.py
#restores configurations.xml to its original (checked-in) content when done, regardless of outcome.
import csv
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "configurations.xml")

N_EDGE = 10
EDGE_CAPACITY = 2#matches the default scenario's 1:1 (RRHs/Edge=2) provisioning
#RRHs/Edge = 1..6 (10..60 total RRHs): from comfortably under-loaded to well past the stability
#boundary found while validating this scenario (stable at 2/Edge, already degrading at 3/Edge)
RRH_PER_EDGE_POINTS = [1, 2, 3, 4, 5, 6]
SWEEP_DURATION = 5#simulated seconds per point - enough to see whether latency is stabilizing or growing


def buildConfigXML(nRRH, nEdge, edgeCapacity, duration):
	rrhPerSwitch = nRRH // nEdge
	gx = math.ceil(math.sqrt(nRRH))
	while nRRH % gx != 0:
		gx += 1
	gy = nRRH // gx

	lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>", "    <InputParameters>",
		"        <switchTime>0.0001</switchTime>", "        <frameProcTime>0.0001</frameProcTime>",
		"        <transmissionTime>0.0000001</transmissionTime>", "        <localTransmissionTime>0.0000001</localTransmissionTime>",
		"        <cpriFrameGenerationTime>0.001</cpriFrameGenerationTime>", "        <distributionAverage>1000</distributionAverage>",
		"        <cpriMode>CPRI</cpriMode>", "        <utilizationSampleInterval>1</utilizationSampleInterval>",
		"        <simulationDuration>{}</simulationDuration>".format(duration),
		"        <limitAxisY>{}</limitAxisY>".format(gy), "        <limitAxisX>{}</limitAxisX>".format(gx),
		"        <stepAxisY>1</stepAxisY>", "        <stepAxisX>1</stepAxisX>", "    </InputParameters>", "    <RRHs>"]
	for i in range(nRRH):
		lines.append('        <RRH aId = "{}" />'.format(i))
	lines.append("    </RRHs>")
	lines.append("    <NetworkNodes>")
	for i in range(nEdge):
		lines.append('        <Node aId = "{}" aType = "Switch" capacity = "10000" qos = "Standard" />'.format(i))
	lines.append("    </NetworkNodes>")
	lines.append("    <ProcessingNodes>")
	for i in range(nEdge):
		lines.append('        <Proc aId = "{}" aType = "Edge"  role = "Edge"  capacity = "{}"     qos = "Standard" accessDelay = "0.0000980654" activationPower = "300" />'.format(i, edgeCapacity))
	lines.append('        <Proc aId = "0" aType = "Cloud" role = "Cloud" capacity = "10000" qos = "Standard" accessDelay = "0.0001961308" activationPower = "600" />')
	lines.append("    </ProcessingNodes>")
	lines.append('    <ORANFunctions><Function aId = "0" aType = "NonRTRIC" /><Function aId = "0" aType = "NearRTRIC" /><Function aId = "0" aType = "RTRIC" /></ORANFunctions>')
	lines.append('    <UseCases><UseCase aId = "IoT" maxLatency = "1.0" minBandwidth = "0.1" trafficPattern = "periodic" /></UseCases>')
	lines.append("    <Edges>")
	for i in range(nRRH):
		switch = i // rrhPerSwitch
		lines.append('        <Edge  source = "RRH:{}" destiny = "Switch:{}" weight = "5.5" />'.format(i, switch))
	for i in range(nEdge):
		lines.append('        <Edge  source = "Switch:{}" destiny = "Switch:{}" weight = "7" />'.format(i, (i + 1) % nEdge))
		lines.append('        <Edge  source = "Switch:{}" destiny = "Edge:{}" weight = "1" />'.format(i, i))
	lines.append('        <Edge  source = "Switch:0" destiny = "Cloud:0" weight = "10" />')
	lines.append("    </Edges>")
	lines.append("</config>")
	return "\n".join(lines)


def readCSV(filename):
	path = os.path.join(ROOT, filename)
	if not os.path.exists(path):
		return []
	with open(path) as f:
		return list(csv.DictReader(f))


def summarizeRun(rrhPerEdge, nRRH):
	latency = readCSV("metrics_latency.csv")
	blocking = readCSV("metrics_blocking.csv")
	migrations = readCSV("metrics_migrations.csv")
	activeNodes = readCSV("metrics_active_nodes.csv")
	energy = readCSV("metrics_energy.csv")

	attempted = len(latency) + len(blocking)
	rtLatencyMs = [float(r["latency"]) * 1000 for r in latency if r["controlLoop"] == "RT"]
	compliant = sum(1 for r in latency if r["compliant"] == "True")
	#compare the first vs. second half of the run to tell a stable point (flat) from a diverging one
	#(growing queue) without needing a longer simulation at every sweep point
	half = SWEEP_DURATION / 2
	firstHalf = [float(r["latency"]) * 1000 for r in latency if r["controlLoop"] == "RT" and float(r["time"]) < half]
	secondHalf = [float(r["latency"]) * 1000 for r in latency if r["controlLoop"] == "RT" and float(r["time"]) >= half]

	return {
		"rrhPerEdge": rrhPerEdge,
		"totalRRHs": nRRH,
		"framesAttempted": attempted,
		"blockingRate": (len(blocking) / attempted) if attempted else 0.0,
		"rtComplianceRate": (compliant / len(latency)) if latency else None,
		"avgLatencyMs": (sum(rtLatencyMs) / len(rtLatencyMs)) if rtLatencyMs else None,
		"avgLatencyFirstHalfMs": (sum(firstHalf) / len(firstHalf)) if firstHalf else None,
		"avgLatencySecondHalfMs": (sum(secondHalf) / len(secondHalf)) if secondHalf else None,
		"migrationCount": len(migrations),
		"avgActiveNodeRatio": (sum(float(r["ratio"]) for r in activeNodes) / len(activeNodes)) if activeNodes else None,
		"avgEnergySavingsRatio": (sum(float(r["savingsRatio"]) for r in energy) / len(energy)) if energy else None,
	}


def main():
	with open(CONFIG_PATH) as f:
		originalConfig = f.read()

	results = []
	try:
		for rrhPerEdge in RRH_PER_EDGE_POINTS:
			nRRH = rrhPerEdge * N_EDGE
			print("--- sweep point: {} RRHs/Edge ({} RRHs total) ---".format(rrhPerEdge, nRRH))
			with open(CONFIG_PATH, "w") as f:
				f.write(buildConfigXML(nRRH, N_EDGE, EDGE_CAPACITY, SWEEP_DURATION))
			subprocess.run([sys.executable, "simulation.py"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
			results.append(summarizeRun(rrhPerEdge, nRRH))
	finally:
		with open(CONFIG_PATH, "w") as f:
			f.write(originalConfig)
		for fname in ["metrics_latency.csv", "metrics_migrations.csv", "metrics_utilization.csv", "metrics_blocking.csv", "metrics_active_nodes.csv", "metrics_energy.csv"]:
			p = os.path.join(ROOT, fname)
			if os.path.exists(p):
				os.remove(p)

	outPath = os.path.join(ROOT, "sweep_results.csv")
	fieldnames = ["rrhPerEdge", "totalRRHs", "framesAttempted", "blockingRate", "rtComplianceRate", "avgLatencyMs", "avgLatencyFirstHalfMs", "avgLatencySecondHalfMs", "migrationCount", "avgActiveNodeRatio", "avgEnergySavingsRatio"]
	with open(outPath, "w", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		for r in results:
			writer.writerow(r)

	print("wrote {} ({} points); configurations.xml restored".format(outPath, len(results)))


if __name__ == "__main__":
	main()
