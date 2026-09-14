#this is the utility module, where every utility method must be put, including methods that calculates metrics from the simulation
import xml.etree.ElementTree as ET
import networkx as nx
import csv

#metrics recorded during the simulation, exported to CSV by exportMetricsCSV at the end of simulation.py
latencyRecords = []
migrationRecords = []
utilizationRecords = []
blockingRecords = []
activeNodeRecords = []
energyRecords = []

#records whether a frame met its control loop's latency budget (maxLatency in seconds, may be None for NonRT)
def recordLatencyCompliance(controlLoop, latency, maxLatency, time):
	compliant = latency <= maxLatency if maxLatency is not None else None
	latencyRecords.append({"controlLoop": controlLoop, "latency": latency, "maxLatency": maxLatency, "compliant": compliant, "time": time})

#records a placement change (migration) of a Layer 2/3 function between two nodes
def recordMigration(functionId, fromNode, toNode, time):
	migrationRecords.append({"function": functionId, "from": fromNode, "to": toNode, "time": time})

#records a node's load/capacity sample, taken periodically by network.utilizationMonitor
def recordUtilization(nodeId, time, load, capacity):
	utilizationRecords.append({"node": nodeId, "time": time, "load": load, "capacity": capacity, "ratio": load / capacity if capacity else 0.0})

#records a placement request that no candidate node could accept (all were at/over capacity) -
#the same "lost traffic" that old/graph.py's getBlockingProbability computed from a min-cost flow
def recordBlocking(functionId, controlLoop, time):
	blockingRecords.append({"function": functionId, "controlLoop": controlLoop, "time": time})

#records how many of the candidate nodes are currently active (hosting >=1 function), taken
#periodically by network.controlPlaneMonitor - the SimPy-era equivalent of old/graph.py's countActNodes()
def recordActiveNodes(time, activeCount, totalCount):
	activeNodeRecords.append({"time": time, "activeCount": activeCount, "totalCount": totalCount, "ratio": activeCount / totalCount if totalCount else 0.0})

#records the current placement's energy cost against the "every node always on" baseline - the
#SimPy-era equivalent of old/graph.py's overallPowerConsumption(), taken periodically by network.controlPlaneMonitor
def recordEnergy(time, energy, energyAlwaysOn):
	savings = (energyAlwaysOn - energy) / energyAlwaysOn if energyAlwaysOn else 0.0
	energyRecords.append({"time": time, "energy": energy, "energyAlwaysOn": energyAlwaysOn, "savingsRatio": savings})

#writes the recorded metrics as CSV files under outputDir, for offline analysis
def exportMetricsCSV(outputDir="."):
	_writeCSV("{}/metrics_latency.csv".format(outputDir), latencyRecords, ["controlLoop", "latency", "maxLatency", "compliant", "time"])
	_writeCSV("{}/metrics_migrations.csv".format(outputDir), migrationRecords, ["function", "from", "to", "time"])
	_writeCSV("{}/metrics_utilization.csv".format(outputDir), utilizationRecords, ["node", "time", "load", "capacity", "ratio"])
	_writeCSV("{}/metrics_blocking.csv".format(outputDir), blockingRecords, ["function", "controlLoop", "time"])
	_writeCSV("{}/metrics_active_nodes.csv".format(outputDir), activeNodeRecords, ["time", "activeCount", "totalCount", "ratio"])
	_writeCSV("{}/metrics_energy.csv".format(outputDir), energyRecords, ["time", "energy", "energyAlwaysOn", "savingsRatio"])

def _writeCSV(path, records, fieldnames):
	with open(path, "w", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		for r in records:
			writer.writerow(r)

#XML parser
def xmlParser(xmlFile):
	#keep the configuration parameters
	parameters = {}
	#construct the XML tree
	tree = ET.parse(xmlFile)
	#get the root
	root = tree.getroot()
	#return root
	##iterate over the nodes and  store each one into the parameters dictionaire
	for child in root:
		parameters[child.tag] = child
	return parameters

#call Dijkstra shortest path algorithm
def dijkstraShortestpath(G, source, destiny):
	length, path = nx.single_source_dijkstra(G, source, destiny)
	return length, path

#create the limits of each base station/RRH following a cartesian plane
def createNetworkLimits(limitX, limitY, stepX, stepY, elements):
	#dictionaire to keep all coordinates of a base station
	#coordinates = {}
	#to place each base station in a dictionaire position
	i = 0
	#until the limit of axis x, go upside until the limite of axis y
	x = 0
	while x < limitX:
		#print("X equal to {}".format(x))
		y = 0
		while y < limitY:
			#coordinates["RRH:{}".format(i)] = [(x, y), (x, y+1), (x+1, y), (x+1, y+1)]#old implementation
			elements["RRH:{}".format(i)].x1 = x
			elements["RRH:{}".format(i)].y1 = y
			elements["RRH:{}".format(i)].x2 = x + 1
			elements["RRH:{}".format(i)].y2 = y + 1
			#print("Coordinates: x1 y1 {}, x1 y 2 {}, x2 y1 {}, x2 y2 {}".format((x, y), (x, y+1), (x+1, y), (x+1, y+1)))
			y += stepY
			#y += 1
			i += 1
		x += stepX
		#x += 1
	#print the coordinate of each RRH
	#for key, value in coordinates.items():
	#	print(key, " :", value)

#test
#createNetworkLimits(5, 4)

#print the coordinates of each base station
def printBaseStationCoordinates(baseStations, elements):
	for r in baseStations:
		print("{} coordinates are: \n X1: {}\n Y1: {}\n X2: {}\n Y2: {}\n".format(elements["RRH:{}".format(r["aId"])].aId,
			elements["RRH:{}".format(r["aId"])].x1, elements["RRH:{}".format(r["aId"])].y1, elements["RRH:{}".format(r["aId"])].x2, elements["RRH:{}".format(r["aId"])].y2))

