#this is the simulation module, in which the simulation parameters and the simulation itself is initiated
import simpy
import network
import psutil
import utility as util
import networkx as nx
import simpy
import functools
import random as np
import time
from enum import Enum
import numpy
from scipy.stats import norm

#simpy environment variable
env = simpy.Environment()
#reads the XML configuration file
parameters = util.xmlParser('configurations.xml')

#initiate input parameters from the entries on the XML file
switchTime = float(parameters["InputParameters"].find("switchTime").text)
frameProcTime = float(parameters["InputParameters"].find("frameProcTime").text)
transmissionTime = float(parameters["InputParameters"].find("transmissionTime").text)
localTransmissionTime = float(parameters["InputParameters"].find("localTransmissionTime").text)
cpriFrameGenerationTime = float(parameters["InputParameters"].find("cpriFrameGenerationTime").text)
distributionAverage = float(parameters["InputParameters"].find("distributionAverage").text)
cpriMode = parameters["InputParameters"].find("cpriMode").text
utilizationSampleInterval = float(parameters["InputParameters"].find("utilizationSampleInterval").text)
simulationDuration = float(parameters["InputParameters"].find("simulationDuration").text)
distribution = lambda x: np.expovariate(1000)
limitAxisY = int(parameters["InputParameters"].find("limitAxisY").text)#limit of axis Y of the network topology on a cartesian plane
limitAxisX = int(parameters["InputParameters"].find("limitAxisX").text)#limit of axis X of the network topology on a cartesian plane
stepAxisY = int(parameters["InputParameters"].find("stepAxisY").text)#increasing step on axis Y when defining the size of the base station
stepAxisX = int(parameters["InputParameters"].find("stepAxisX").text)#increasing step on axis X when defining the size of the base station

#keep the input parameters for visualization or control purposes
inputParameters = []
for p in parameters["InputParameters"]:
	inputParameters.append(p)

#get the attributes of each RRH
rrhsParameters = []
for r in parameters["RRHs"]:
	rrhsParameters.append(r.attrib)

#get the attributes of each node to be created
netNodesParameters = []
for node in parameters["NetworkNodes"]:
	netNodesParameters.append(node.attrib)

#get the attributes of each processing node to be created (Layer 3 hosts: Edge/Cloud)
procNodesParameters = []
for proc in parameters["ProcessingNodes"]:
	procNodesParameters.append(proc.attrib)

#get the attributes of each Layer 2 O-RAN function to be created
oranFunctionsParameters = []
for func in parameters["ORANFunctions"]:
	oranFunctionsParameters.append(func.attrib)

#get the attributes of each Layer 1 use case (this Test Sample uses a single fixed use case)
useCasesParameters = []
for uc in parameters["UseCases"]:
	useCasesParameters.append(uc.attrib)

#get the edges for the graph representation
networkEdges = []
for e in parameters["Edges"]:
	networkEdges.append(e.attrib)

#save the id of each element to create the graph
vertex = []
#RRHs
for r in rrhsParameters:
	vertex.append("RRH:"+str(r["aId"]))
#Network nodes
for node in netNodesParameters:
	vertex.append(node["aType"]+":"+str(node["aId"]))
#Processing nodes
for proc in procNodesParameters:
	vertex.append(proc["aType"]+":"+str(proc["aId"]))

#create the graph
G = nx.Graph()
#add the nodes to the graph
for u in vertex:
	G.add_node(u)
#add the edges and weights to the graph
for edge in networkEdges:
	G.add_edge(edge["source"], edge["destiny"], weight= float(edge["weight"]))

#create the elements
#create the network nodes
for node in netNodesParameters:
	net_node = network.NetworkNode(env, node["aId"], node["aType"], float(node["capacity"]), node["qos"], switchTime, transmissionTime, G)
	network.elements[net_node.aId] = net_node
	env.process(network.utilizationMonitor(env, net_node, utilizationSampleInterval))

#create the processing nodes (Layer 3 hosts): role selects EdgeNode or CloudNode.
#these must exist before the RRHs/vBBUs and O-RAN functions that will be placed on them
NODE_ROLE_CLASSES = {"Edge": network.EdgeNode, "Cloud": network.CloudNode}
candidateNodes = []
for proc in procNodesParameters:
	nodeClass = NODE_ROLE_CLASSES[proc["role"]]
	proc_node = nodeClass(env, proc["aId"], proc["aType"], float(proc["capacity"]), proc["qos"], frameProcTime, transmissionTime, G, float(proc["accessDelay"]), float(proc["activationPower"]))
	network.elements[proc_node.aId] = proc_node
	candidateNodes.append(proc_node)
	env.process(network.utilizationMonitor(env, proc_node, utilizationSampleInterval))

#the ControlPlane owns the placement policy - swap LatencyAwarePolicy() for a ML/RL-based
#PlacementPolicy once one is trained, without changing anything else in this file
controlPlane = network.ControlPlane(env, G, network.LatencyAwarePolicy())
#samples active-node count and energy consumption (vs. the always-on baseline) over time
env.process(network.controlPlaneMonitor(env, controlPlane, candidateNodes, utilizationSampleInterval))

#create the Layer 2 O-RAN functions and place each one once at bootstrap (research question 4:
#where to place the Near-RT RIC/xApps). Dynamic re-placement during the simulation is not yet
#driven by any traffic model for these functions - see the ORANFunctions comment in configurations.xml
oranFunctions = []
for func in oranFunctionsParameters:
	oranFunction = network.ORAN_FUNCTION_TYPES[func["aType"]](func["aId"])
	hostNode = controlPlane.placeFunction(oranFunction, candidateNodes)
	if hostNode is None:
		print("{} blocked at bootstrap - no candidate node has capacity".format(oranFunction.aId))
	else:
		print("{} placed at {}".format(oranFunction.aId, hostNode.aId))
	oranFunctions.append(oranFunction)

#create the Layer 1 use case for this Test Sample (a single fixed use case, e.g., IoT)
useCase = network.UseCase(useCasesParameters[0]["aId"], float(useCasesParameters[0]["maxLatency"]), float(useCasesParameters[0]["minBandwidth"]), useCasesParameters[0]["trafficPattern"])

#restrict each RRH's placement candidates to nodes within a bounded number of hops (its local Edge
#plus a couple of ring-adjacent ones for redundancy) instead of every Edge/Cloud network-wide.
#RRHs in a real Fronthaul network can only reach a physically nearby set of sites within the RT
#loop's latency budget - letting every RRH compete globally for literally any Edge, regardless of
#distance, was found (while validating the 30-RRH scenario) to flood the switches carrying that
#cross-network transit traffic long before any Edge's own capacity was the bottleneck. Cloud is
#always a candidate, matching NonRT traffic's tolerance for a centralized location.
MAX_CANDIDATE_HOPS = 3
def localCandidatesFor(rrhAid):
	local = []
	for node in candidateNodes:
		if node.role == "Cloud" or nx.shortest_path_length(G, source=rrhAid, target=node.aId) <= MAX_CANDIDATE_HOPS:
			local.append(node)
	return local

#create the RRHs, wiring each one to the ControlPlane, its candidate Layer 3 hosts and the use case
for r in rrhsParameters:
	rrhAid = "RRH:"+str(r["aId"])
	rrh = network.RRH(env, r["aId"], distribution, cpriFrameGenerationTime, transmissionTime, localTransmissionTime, G, cpriMode, controlPlane, localCandidatesFor(rrhAid), useCase)
	network.elements[rrh.aId] = rrh

#print(network.elements.keys())

#set the limit area of each base station
util.createNetworkLimits(limitAxisX, limitAxisY, stepAxisX, stepAxisY, network.elements)

#print the coordinate of each base station
util.printBaseStationCoordinates(rrhsParameters, network.elements)


#starts the simulation
print("------------------------------------------------------------SIMULATION STARTED AT {}------------------------------------------------------------".format(env.now))
env.run(until = simulationDuration)
print("------------------------------------------------------------SIMULATION ENDED AT {}------------------------------------------------------------".format(env.now))
print(psutil.virtual_memory())#print the memory consumption for testing

#export the recorded latency compliance, migration and utilization metrics for offline analysis
util.exportMetricsCSV(".")
#print("Total of CPRI basic frames: {}".format(network.generatedCPRI))

'''
#Tests
#print the graph
#print([i for i in nx.edges(G)])
print(G.edges())
#print(G["RRH:0"]["Switch:0"]["weight"])
#print(G.graph)
#for i in nx.edges(G):
#	print("{} --> {} Weight: {}".format(i[0], i[1], G[i[0]][i[1]]["weight"]))

#calling Dijkstra to calculate the shortest path. Returning variables "length" and "path" are the total cost of the path and the path itself, respectively
#length, path = nx.single_source_dijkstra(G, "RRH:0", "Cloud:0")
#print(path)

#for i in range(len(rrhs)):
#  print(g["s"]["RRH{}".format(i)]["capacity"])


print("-----------------Input Parameters-------------------")
for i in inputParameters:
	print("{}: {}".format(i.tag, i.text))

print("-----------------RRHs-------------------")
for i in rrhsParameters:
	print(i)

print("-----------------Network Nodes-------------------")
for i in netNodesParameters:
	print(i)

print("-----------------Processing Nodes-------------------")
for i in procNodesParameters:
	print(i)

print("-----------------Edges-------------------")
for i in networkEdges:
	print(i)
'''