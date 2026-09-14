#isolated test of network.ControlPlane's placement/migration/blocking/energy mechanisms,
#independent of a full simulation run - forces the Edge (and, in the last step, the Cloud too)
#through a sequence of load levels and records where the LatencyAwarePolicy hosts a RT (vBBU) and
#a NonRT (rApp) function at each step, plus migrations, active-node count and energy consumption.
#run from the project root: python3 scripts/run_mechanism_demo.py
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import simpy
import network

env = simpy.Environment()
edge = network.EdgeNode(env, 0, "Edge", 2, "Standard", 0.0001, 0.0000001, None, 0.0000980654, 300)
cloud = network.CloudNode(env, 0, "Cloud", 10000, "Standard", 0.0001, 0.0000001, None, 0.0001961308, 600)
candidateNodes = [edge, cloud]
controlPlane = network.ControlPlane(env, None, network.LatencyAwarePolicy())

rtFunction = network.VBBU(0, ownerRRH=None)
nonRtFunction = network.NonRTRIC(0)

#(edgeLoad, cloudLoad) per step - the last step saturates both nodes at once to force a genuinely
#blocked placement request, which never happens with Cloud's large real-world capacity but is
#useful to demonstrate the LatencyAwarePolicy's blocking path in isolation
loadSteps = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (0, 0), (3, 10001)]
rows = []
for step, (edgeLoad, cloudLoad) in enumerate(loadSteps):
	edge.currentLoad = edgeLoad
	cloud.currentLoad = cloudLoad
	migrationsBefore = len(network.util.migrationRecords)
	blockingBefore = len(network.util.blockingRecords)
	rtHost = controlPlane.placeFunction(rtFunction, candidateNodes)
	nonRtHost = controlPlane.placeFunction(nonRtFunction, candidateNodes)
	migrated = len(network.util.migrationRecords) > migrationsBefore
	blocked = len(network.util.blockingRecords) > blockingBefore
	activeNodes = controlPlane.activeNodes(candidateNodes)
	rows.append({
		"step": step,
		"edgeLoad": edgeLoad,
		"edgeCapacity": edge.processingCapacity,
		"cloudLoad": cloudLoad,
		"cloudCapacity": cloud.processingCapacity,
		"rtHost": rtHost.aId if rtHost else "BLOCKED",
		"nonRtHost": nonRtHost.aId if nonRtHost else "BLOCKED",
		"migrated": migrated,
		"blocked": blocked,
		"activeCount": len(activeNodes),
		"energy": controlPlane.energyConsumption(candidateNodes, alwaysOn=False),
		"energyAlwaysOn": controlPlane.energyConsumption(candidateNodes, alwaysOn=True),
	})

outPath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mechanism_demo.csv")
fieldnames = ["step", "edgeLoad", "edgeCapacity", "cloudLoad", "cloudCapacity", "rtHost", "nonRtHost", "migrated", "blocked", "activeCount", "energy", "energyAlwaysOn"]
with open(outPath, "w", newline="") as f:
	writer = csv.DictWriter(f, fieldnames=fieldnames)
	writer.writeheader()
	for r in rows:
		writer.writerow(r)

print("wrote {} ({} steps, {} migrations, {} blocked requests)".format(outPath, len(rows), len(network.util.migrationRecords), len(network.util.blockingRecords)))
