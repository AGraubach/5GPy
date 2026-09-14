import copy
import sys
import abc
import simpy
import functools
import networkx as nx
import random
import time
from enum import Enum
import numpy
import utility as util
from scipy.stats import norm
import psutil


#This is the network module. It keeps all network elements, such as, processing nodes, RRHs, network nodes

#this dictionaire keeps all created network objects
elements = {}
generatedCPRI = 0

#this class represents a general frame
#aId is the fram id, payLoad is its data, src and dst is the source and destiny element, nextHop keeps the path from src to dst, procTime is the average time to process this frame
class Frame(object):
	def __init__(self, aId, payLoad, src, dst):
		self.aId = aId
		self.payLoad = payLoad
		self.src = src
		self.dst = dst
		self.nextHop = []
		self.inversePath = []#return path
		#self.localTransmissionTime = localTransmissionTime
		#self.procTime = procTime
		#self.switchTime = switchTime
		#self.transmissionTime = transmissionTime

#this class extends the basic frame to represent a basic eCPRI frame
#the ideia is that it carries payload from several users equipments and can carry one or more QoS classes of service
#users is a list of UEs being carried, 
#QoS are the classes of service carried on this fram and size is the bit rate of the frame
class ecpriFrame(Frame):
	def __init__(self, aId, payLoad, src, dst, users, QoS, size):
		super().__init__(aId, payLoad, src, dst)
		self.users = users
		self.QoS = QoS
		self.size = size

#this class represents Layer 1 (User Application) requirements for a use case (e.g., IoT)
#maxLatency (s) and minBandwidth are the requirements that drive Layer 2/3 function placement,
#trafficPattern is kept for future traffic generators specific to each use case
class UseCase(object):
	def __init__(self, aId, maxLatency, minBandwidth, trafficPattern):
		self.aId = aId
		self.maxLatency = maxLatency
		self.minBandwidth = minBandwidth
		self.trafficPattern = trafficPattern

#this class represents a basic user equipment
#aId is the UE identification, posY and posX are the locations of the UE in a cartesian plane, useCase is the Layer 1 use case (e.g., IoT) accessed by the UE
class UserEquipment(object):
	def __init__(self, env, aId, servingRRH, useCase, localTransmissionTime):
		self.env = env
		self.aId = aId
		self.servingRRH = servingRRH
		#set the beginning position of each UE as the middle of its base station area
		self.posY = self.servingRRH.y2/2
		self.posX = self.servingRRH.x2/2
		#self.frameProcTime = frameProcTime
		self.localTransmissionTime = localTransmissionTime
		self.useCase = useCase
		self.ackFrames = simpy.Store(self.env)
		self.initiation = self.env.process(self.run())
		#self.action = self.env.process(self.sendFrame())
		self.latency = 0.0
		self.jitter = 0.0
		self.lastLatency = 0.0


	#TODO VOU MUDAR DE NOVO. OS UE NAO VAO GERAR QUADROS, APENAS ANDAR. O RRH AO GERAR O FRAME CPRI ASSUMIRÁ QUE RECEBEU UM QUADRO DE CADA UE
	#O CALCULO DO JITTER E DA TRANSMISSÃO SERÁ FEITO EM CIMA DA POSIÇÃO EM QUE CADA UE SE ENCONTRAR QUANDO O RRH GERAR O FRAME CPRI E QUANDO DEVOLVER (HIPOTETICAMENTE) O QUADRO A CADA UE
	#this method causes UEs to move
	def run(self):
		i = 0
		while True:
			#timeout for the UE to move
			yield self.env.timeout(0.5)
			self.randomWalk()
			#print("UE {} moved to position X = {} and Y = {}".format(hash(self), self.posX, self.posY))
			i += 1

	#TODO: Implement the limits of the UE to move (the combinations of the maximum values of axis y and x)
	#moves the UE
	def randomWalk(self):
		val = random.randint(1, 4)
		if val == 1:
			self.posX += 1
			self.posY = self.posY 
		if val == 2:
			self.posX -= 1
			self.posY = self.posY 
		elif val == 3:
			self.posX = self.posX 
			self.posY += 1
		else:
			self.posX = self.posX 
			self.posY -= 1

#this class represents a generic RRH
#it generates a bunch of UEs, receives/transmits baseband signals from/to them, generate eCPRI frames and send/receive them to/from processing
class RRH(object):
	def __init__(self, env, aId, distribution, cpriFrameGenerationTime, transmissionTime, localTransmissionTime, graph, cpriMode, controlPlane, candidateNodes, useCase):
		self.env = env
		self.nextNode = None
		self.aType = "RRH"
		self.aId = "RRH"+":"+str(aId)
		self.frames = []
		self.users = []#list of active UEs served by this RRH
		self.nodes_connection = []#binary array that keeps the connection fron this RRH to fog nodes and cloud node(s)
		self.distribution = distribution#the distribution for the traffic generator distribution
		#Layer 3 (Fronthaul): the vBBU is the placeable function processing this RRH's baseband signal.
		#Its hostNode (Edge or Cloud) is decided/updated by the ControlPlane on every uplink frame.
		self.controlPlane = controlPlane
		self.candidateNodes = candidateNodes#Edge/Cloud nodes eligible to host this RRH's vBBU
		self.useCase = useCase#Layer 1 use case (e.g., IoT) served by this RRH's UEs
		self.vbbu = VBBU(aId, self)
		self.trafficGen = self.env.process(self.run())#initiate the built-in traffic generator
		#self.genFrame = self.env.process(self.takeFrameUE())
		self.uplinkTransmitCPRI = self.env.process(self.uplinkTransmitCPRI())#send eCPRI frames to a processing node
		self.downlinkTransmitUE = self.env.process(self.downlinkTransmitUE())#send frames to the UEs
		#thsi store receives frames back from the users
		self.received_users_frames = simpy.Store(self.env)
		#buffer to transmit to UEs
		self.currentLoad = 0
		#this store receives frames back from the processing nodes
		#self.received_eCPRI_frames = simpy.Store(self.env)
		self.processingQueue = simpy.Store(self.env)
		#this store keeps the local processed baseband signals
		self.local_processing_queue = simpy.Store(self.env)
		#self.frameProcTime = frameProcTime
		self.cpriFrameGenerationTime = cpriFrameGenerationTime
		self.transmissionTime = transmissionTime
		self.localTransmissionTime = localTransmissionTime
		self.graph = graph
		self.cpriMode = cpriMode
		#limiting coordinates of the base station area
		self.x1 = 0
		self.x2 = 0
		self.y1 = 0
		self.y2 = 0

	#this method generates users equipments
	def run(self):
		i = 0
		while True:
			yield self.env.timeout(self.distribution(self))
			#a limit for the generation of UEs for testing purposes
			if len(self.users) < 2:
				ue = UserEquipment(self.env, i, self, self.useCase, self.localTransmissionTime)
				self.users.append(ue)
				#print("{} generated UE {} at {}".format(self.aId, hash(ue), self.env.now))
				i += 1

	#every time a frame is received from a UE, keep it to generate the eCPRI frame later
	def takeFrameUE(self):
		while True:
			r = yield self.received_users_frames.get()
			self.frames.append(r)

	#this method builds a eCPRI frame and uplink transmits it to a optical network element
	def uplinkTransmitCPRI(self):
		global generatedCPRI
		frame_id = 1
		while True:
			yield self.env.timeout(self.cpriFrameGenerationTime)
			#ask the ControlPlane where this RRH's vBBU (Layer 3) should be hosted right now -
			#this is what makes placement dynamic: it is re-evaluated on every uplink frame
			#instead of being fixed once for the whole simulation
			hostNode = self.controlPlane.placeFunction(self.vbbu, self.candidateNodes)
			if hostNode is None:
				#blocked: no candidate node had spare capacity for this RRH's vBBU - the frame is
				#lost rather than forced onto an overloaded node, matching the "lost traffic" the
				#old ILP-based simulator counted in getBlockingProbability()
				print("{} blocked - no candidate node has capacity for its vBBU at {}".format(self.aId, self.env.now))
				frame_id += 1
				continue
			print("{} generating eCPRI frame {} at {} (vBBU hosted at {})".format(self.aId, self.aId+"->"+str(frame_id), self.env.now, hostNode.aId))
			#print(psutil.virtual_memory())
			#If traditional CPRI is used, create a frame with fixed bandwidth (not implemented yet)
			activeUsers = []
			if self.cpriMode == "CPRI":
				#take each UE and put it into the CPRI frame
				if self.users:
					for i in self.users:
						activeUsers.append(i)
				eCPRIFrame = ecpriFrame(self.aId+"->"+str(frame_id), None, self, hostNode.aId, activeUsers, None, None)
				if self.users:
					for i in self.users:
						i.lastLatency = i.latency
						i.latency = (i.latency + self.env.now)/frame_id
				generatedCPRI += 1
			#if eCPRI is being used, different strategy must be implemented to generate the frame
			elif self.cpriMode == "eCPRI":
				if self.users:
					for i in self.users:
						activeUsers.append(i)
				frame_size = len(activeUsers)
				eCPRIFrame = ecpriFrame(frame_id, None, self, hostNode.aId, activeUsers, None, frame_size)
				#TODO atualizar o tempo em que cada UE mandou o quadro para o RRH em função da sua distância até ele (ex. env.now - transmissiontTime,  transmissionTime vai ser dinâmico)
				if self.users:
					for i in self.users:
						i.latency = (i.latency + self.env.now)/frame_id
			#tag the frame with the fronthaul (RT) control loop requirement and its creation time,
			#so the destination node can check latency compliance for this loop once it arrives
			eCPRIFrame.createdAt = self.env.now
			eCPRIFrame.controlLoop = self.vbbu.controlLoop
			eCPRIFrame.maxLatency = self.vbbu.maxLatency
			#calculates the shortest path to wherever the vBBU is hosted right now
			length, path = nx.single_source_dijkstra(self.graph, self.aId, hostNode.aId)
			#remove the aId of this node from the path
			eCPRIFrame.nextHop = copy.copy(path)
			eCPRIFrame.inversePath = list(eCPRIFrame.nextHop)
			eCPRIFrame.inversePath.reverse()
			eCPRIFrame.inversePath.pop(0)
			#takes the next hop
			eCPRIFrame.nextHop.pop(0)
			#print("Path for {} is {}".format(self.aId, eCPRIFrame.nextHop))
			#print("Inverse path is {}".format(eCPRIFrame.inversePath))
			destiny = elements[eCPRIFrame.nextHop.pop(0)]
			#print("{} transmitting to {}".format(self.aId, destiny.aId))
			#yield self.env.timeout(self.transmissionTime)
			destiny.processingQueue.put(eCPRIFrame)
			#update the load on the buffer of the destiny node
			destiny.currentLoad += 1
			#print("Frame {} generated".format(eCPRIFrame.aId))
			frame_id += 1

	#This method hipothetically sends an ACK to each UE. The ACK message is modeled as an update on the received time attribute of each UE.
	#The received time is update as a function of the time to send a frame to each UE regarding the distance of each UE from the RRH
	#Note that the calculation of the latency to send the frame in function of the UE position is not yet implemented
	#TODO: Implement the received time for eacj UE in function of its distance to the RRH
	def downlinkTransmitUE(self):
		frame_id = 1
		while True:
			#print(psutil.virtual_memory())
			print("{} transmitting to its UEs".format(self.aId))
			received_frame = yield self.processingQueue.get()
			#yield self.env.timeout(frameProcTime)
			#send an ack to each UE within this received eCPRI frame
			if received_frame.users:
				for i in received_frame.users:
					yield self.env.timeout(self.localTransmissionTime)
					#TODO: implement the time in which each UE receives the frame from the RRH
					#i.timeReceived[i] = self.env.now
					#TODO: Implement the jitter calculation, using the lastLatency variable
					i.jitter = (i.latency + self.env.now)/frame_id
			#update the load on the buffer after processing the frame
			self.currentLoad -= 1
			del received_frame
			#received_frame = None
			frame_id += 1

#basic network node interface to be extended by any new network class node
class ActiveNode(metaclass=abc.ABCMeta):
	def __init__(self, env, aId, aType, capacity):
		self.env = env
		self.aType = aType
		self.aId = aType+":"+str(aId)
		self.processingCapacity = capacity
		self.currentLoad = 0
		self.nextNode = None
		self.processingQueue = simpy.Store(self.env)
		self.nextNode = None
		self.lastNode = None
		self.toProcess = self.env.process(self.processRequest())

	#process each frame
	@abc.abstractmethod
	def processRequest(self):
		pass

	#transmit each frame after processing
	@abc.abstractmethod
	def sendRequest(self, request):
		pass

	#test the processing capacity
	def hasCapacity(self):
		if self.currentLoad <= self.processingCapacity:
			return True
		else:
			return False

#a general processing node
class ProcessingNode(ActiveNode):
	def __init__(self, env, aId, aType, capacity, qos, procTime, transmissionTime, graph):
		super().__init__(env, aId, aType, capacity)
		self.qos = qos#list of class of service suppoerted by this node
		self.procTime = procTime
		self.transmissionTime = transmissionTime
		self.graph = graph

	#process a request
	def processRequest(self):
		while True:
			request = yield self.processingQueue.get()
			if self.aId == request.dst:#this is the destiny node. Process it and compute the downlink path
				#print("Request {} arrived at destination {}".format(request.aId, self.aId))
				request.nextHop = request.inversePath
				#if the request carries a control loop requirement (e.g., set by RRH.uplinkTransmitCPRI),
				#record whether it met the control loop's latency budget
				if hasattr(request, "createdAt"):
					measuredLatency = self.env.now - request.createdAt
					util.recordLatencyCompliance(getattr(request, "controlLoop", None), measuredLatency, getattr(request, "maxLatency", None), self.env.now)
			print("{} buffer load is {}".format(self.aId, self.currentLoad))
			print("{} processing request {} at {}".format(self.aId, request.aId, self.env.now))
			#EdgeNode/CloudNode add their tier's accessDelay on top of the base processing time
			yield self.env.timeout(self.procTime + getattr(self, "accessDelay", 0))
			#update the load on the buffer after processing the frame
			self.currentLoad -= 1
			self.sendRequest(request)

	#transmit a request to its destiny	
	def sendRequest(self, request):
		nextHop = request.nextHop.pop(0)#returns the id of the next hop
		destiny = elements[nextHop]#retrieve the next hop object searching by its id
		print("{} sending request {} to {}".format(self.aId, request.aId, destiny.aId))
		print("{} buffer load is {}".format(self.aId, self.currentLoad))
		self.env.timeout(self.transmissionTime)
		destiny.processingQueue.put(request)
		#update the load on the buffer of the destiny node
		destiny.currentLoad += 1

#a general processing node
class NetworkNode(ActiveNode):
	def __init__(self, env, aId, aType, capacity, qos, switchTime, transmissionTime, graph):
		super().__init__(env, aId, aType, capacity)
		self.qos = qos#list of class of service suppoerted by this node
		self.switchTime = switchTime
		self.transmissionTime = transmissionTime
		self.graph = graph

	#process a request
	def processRequest(self):
		while True:
			request = yield self.processingQueue.get()
			print("{} buffer load is {}".format(self.aId, self.currentLoad))
			#print("Request {} arrived at {}".format(request.aId, self.aId))
			print("{} processing request {} at {}".format(self.aId, request.aId, self.env.now))
			yield self.env.timeout(self.switchTime)
			#update the load on the buffer after processing the frame
			self.currentLoad -= 1
			#self.processingCapacity -= 1
			self.sendRequest(request)

	#transmit a request to its destiny
	def sendRequest(self, request):
		nextHop = request.nextHop.pop(0)#returns the id of the next hop
		destiny = elements[nextHop]#retrieve the next hop object searching by its id
		print("{} sending request {} to {}".format(self.aId, request.aId, destiny.aId))
		self.env.timeout(self.transmissionTime)
		destiny.processingQueue.put(request)
		#update the load on the buffer of the destiny node
		destiny.currentLoad += 1


#a general processing node hosted at the Edge tier of the Cloud-Edge continuum
#accessDelay models the extra propagation/access delay of reaching this tier (defaults follow the
#fog-tier delay used in the group's prior Cloud-Fog work, e.g., old/graph.py's fog_delay).
#activationPower is the fixed power cost incurred while this node hosts at least one function -
#the same "cost per activated node" idea as old/graph.py's costs["fog{}"]/costs["cloud"], used
#there by overallPowerConsumption() to reward consolidating onto fewer active nodes
class EdgeNode(ProcessingNode):
	def __init__(self, env, aId, aType, capacity, qos, procTime, transmissionTime, graph, accessDelay, activationPower):
		super().__init__(env, aId, aType, capacity, qos, procTime, transmissionTime, graph)
		self.role = "Edge"
		self.accessDelay = accessDelay
		self.activationPower = activationPower

#a general processing node hosted at the Cloud tier of the Cloud-Edge continuum
class CloudNode(ProcessingNode):
	def __init__(self, env, aId, aType, capacity, qos, procTime, transmissionTime, graph, accessDelay, activationPower):
		super().__init__(env, aId, aType, capacity, qos, procTime, transmissionTime, graph)
		self.role = "Cloud"
		self.accessDelay = accessDelay
		self.activationPower = activationPower

#latency budget (in seconds) of each O-RAN control loop, as defined in the qualification:
#RT (O-DU<->O-RU/vBBU fronthaul) < 10ms; NearRT (Near-RT RIC/xApps) 10ms-1s; NonRT (Non-RT RIC/rApps) > 1s (no strict upper bound)
CONTROL_LOOPS = {
	"RT": 0.010,
	"NearRT": 1.0,
	"NonRT": None,
}

#this class represents the Layer 3 (Fronthaul) placeable function that processes one RRH's
#baseband signal. It does not own a SimPy process/queue itself: its hostNode (an EdgeNode or
#CloudNode) is where the actual frame processing happens, and hostNode is kept updated by the
#ControlPlane. This is what allows a vBBU to "migrate" between Edge and Cloud during the simulation
class VBBU(object):
	def __init__(self, aId, ownerRRH):
		self.aId = "VBBU:"+str(aId)
		self.aType = "VBBU"
		self.ownerRRH = ownerRRH
		self.controlLoop = "RT"
		self.maxLatency = CONTROL_LOOPS["RT"]
		self.hostNode = None#aId of the EdgeNode/CloudNode currently hosting this vBBU

#this class represents the Layer 2 (O-RAN Applications) placeable functions: Non-RT RIC (rApps),
#Near-RT RIC (xApps) and RT-RIC, as defined in the qualification's Layer 2 taxonomy. Like the vBBU,
#it carries only placement metadata - it is instantiated and placed by the ControlPlane at bootstrap;
#simulating its E2/A1 message traffic is out of scope for this iteration of the simulator
class ORANFunction(object):
	def __init__(self, aId, aType, controlLoop):
		self.aId = aType+":"+str(aId)
		self.aType = aType
		self.controlLoop = controlLoop
		self.maxLatency = CONTROL_LOOPS[controlLoop]
		self.hostNode = None

class NonRTRIC(ORANFunction):
	def __init__(self, aId):
		super().__init__(aId, "NonRTRIC", "NonRT")

class NearRTRIC(ORANFunction):
	def __init__(self, aId):
		super().__init__(aId, "NearRTRIC", "NearRT")

class RTRIC(ORANFunction):
	def __init__(self, aId):
		super().__init__(aId, "RTRIC", "RT")

#maps the aType used in configurations.xml's <ORANFunctions> block to its class
ORAN_FUNCTION_TYPES = {
	"NonRTRIC": NonRTRIC,
	"NearRTRIC": NearRTRIC,
	"RTRIC": RTRIC,
}

#interface for a placement decision algorithm. "function" is any placeable object with
#.controlLoop/.maxLatency/.hostNode (a VBBU or an ORANFunction). "candidateNodes" is the list of
#EdgeNode/CloudNode objects it may be hosted on. A future ML/RL-based policy plugs in here by
#implementing decide() - no other part of the simulator needs to change
class PlacementPolicy(abc.ABC):
	@abc.abstractmethod
	def decide(self, function, candidateNodes):
		pass

#initial heuristic policy: functions with a strict control loop (RT/NearRT) are preferably hosted
#at the Edge (to keep them close to the RRHs/UEs); functions without a strict budget (NonRT) are
#preferably centralized at the Cloud. Within the preferred tier, picks the least-loaded node with
#spare capacity, breaking ties randomly among every node at that minimum load. Without this,
#Python's min() always resolves a tie to the first candidate in list order - harmless with a couple
#of nodes, but with many equally-idle candidates (e.g. every Edge at load 0 when the simulation
#starts) it makes every simultaneous caller pick the exact same node, a thundering-herd collapse
#that was observed and fixed while validating the 30-RRH/5-Edge scenario.
#Returns None (the request is blocked, as in old/graph.py's getBlockingProbability - traffic that
#could not be routed to any node) only when NO candidate node has spare capacity at all
class LatencyAwarePolicy(PlacementPolicy):
	def decide(self, function, candidateNodes):
		eligible = [n for n in candidateNodes if n.hasCapacity()]
		if not eligible:
			return None
		preferredRole = "Edge" if function.controlLoop in ("RT", "NearRT") else "Cloud"
		preferred = [n for n in eligible if n.role == preferredRole]
		chosenPool = preferred if preferred else eligible
		loadRatio = lambda n: n.currentLoad / n.processingCapacity if n.processingCapacity else float("inf")
		minRatio = min(loadRatio(n) for n in chosenPool)
		tied = [n for n in chosenPool if loadRatio(n) == minRatio]
		return random.choice(tied)

#this class represents the control plane that invokes the placement algorithm for every Layer 2/3
#function and keeps track of where each one is currently hosted. It owns a PlacementPolicy instance -
#swapping self.policy for a ML/RL-based policy is the only change needed to plug in a trained agent
class ControlPlane(object):
	def __init__(self, env, graph, policy):
		self.env = env
		self.graph = graph
		self.policy = policy
		self.hostedFunctions = {}#node.aId -> set of function aIds currently hosted there, used for activeNodes()/energyConsumption()

	#asks the policy where "function" should be hosted among "candidateNodes". Returns the chosen
	#node, records a migration if the decision changed its current host, and updates the live
	#hostedFunctions view used by activeNodes()/energyConsumption(). If the policy blocks the
	#request (no candidate node has spare capacity), records the blocking and returns None -
	#the function keeps whatever host it had before, exactly like lost/unrouted traffic in
	#old/graph.py's getBlockingProbability
	def placeFunction(self, function, candidateNodes):
		node = self.policy.decide(function, candidateNodes)
		if node is None:
			util.recordBlocking(function.aId, function.controlLoop, self.env.now)
			return None
		if function.hostNode is not None and function.hostNode != node.aId:
			util.recordMigration(function.aId, function.hostNode, node.aId, self.env.now)
			self.hostedFunctions.get(function.hostNode, set()).discard(function.aId)
		function.hostNode = node.aId
		self.hostedFunctions.setdefault(node.aId, set()).add(function.aId)
		return node

	#nodes among candidateNodes that currently host at least one function - the same "active if
	#something is assigned to it" criterion as old/graph.py's countActNodes()
	def activeNodes(self, candidateNodes):
		return [n for n in candidateNodes if self.hostedFunctions.get(n.aId)]

	#power cost of the current placement: activationPower summed over active nodes only. Passing
	#alwaysOn=True instead sums every candidate node, regardless of use - the "keep everything
	#powered on" baseline that the consolidation heuristic is meant to save against, mirroring
	#old/graph.py's overallPowerConsumption() (fixed cost per active node)
	def energyConsumption(self, candidateNodes, alwaysOn=False):
		nodes = candidateNodes if alwaysOn else self.activeNodes(candidateNodes)
		return sum(n.activationPower for n in nodes)

#periodically samples a node's utilization (currentLoad/processingCapacity) for later analysis
def utilizationMonitor(env, node, interval):
	while True:
		util.recordUtilization(node.aId, env.now, node.currentLoad, node.processingCapacity)
		yield env.timeout(interval)

#periodically samples how many candidateNodes are active and the resulting energy consumption,
#against the always-on baseline, so energy savings from consolidation can be plotted over time
def controlPlaneMonitor(env, controlPlane, candidateNodes, interval):
	while True:
		active = controlPlane.activeNodes(candidateNodes)
		util.recordActiveNodes(env.now, len(active), len(candidateNodes))
		util.recordEnergy(env.now, controlPlane.energyConsumption(candidateNodes, alwaysOn=False), controlPlane.energyConsumption(candidateNodes, alwaysOn=True))
		yield env.timeout(interval)
