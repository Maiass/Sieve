# Copyright (C) 2021 Maiass Zaher at Budapest University 
# of Technology and Economics, Budapest, Hungary.
# Copyright (C) 2016 Huang MaChi at Chongqing University
# of Posts and Telecommunications, Chongqing, China.
# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
This code creates the first layer of Sieves where it resides in data plane.
This layer contains of proactive flow entries and group buckets.
This the data plane created as python code using mininet emulator
where mininet uses TC (traffic control) functions provided in Linux kernel
for emulate BW shaping, delay, loss, etc. 
We evalute Sieve's performance over Fat tree whose size is 4.
Mininet uses Linux containers to create light weight virtual resources like hosts.
In addition, Mininet create OVS switches where use OVS command to create flows, groups, etc.
"""
from mininet.net import Mininet
from mininet.node import Controller, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import Link, Intf, TCLink
from mininet.topo import Topo
from mininet.util import quietRun

import logging
import os
import logging
import argparse
import time
import signal
from subprocess import Popen
from multiprocessing import Process
import sys
parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parentdir)
import setting
import tempfile


parser = argparse.ArgumentParser(description="Parameters importation")
parser.add_argument('--k', dest='k', type=int, default=4, choices=[4, 8], help="Switch fanout number")
parser.add_argument('--trapat', dest='traffic_pattern', help="Traffic pattern of the experiment")
args = parser.parse_args()

class Fattree(Topo):
	"""
		Class of Fattree Topology.
	"""
	CoreSwitchList = []
	AggSwitchList = []
	EdgeSwitchList = []
	HostList = []

	def __init__(self, k, density):
		self.pod = k
		self.density = density
		self.iCoreLayerSwitch = (k/2)**2
		self.iAggLayerSwitch = k*k/2
		self.iEdgeLayerSwitch = k*k/2
		self.iHost = self.iEdgeLayerSwitch * density

		# Topo initiation
		Topo.__init__(self)

	def createNodes(self):
		self.createCoreLayerSwitch(self.iCoreLayerSwitch)
		self.createAggLayerSwitch(self.iAggLayerSwitch)
		self.createEdgeLayerSwitch(self.iEdgeLayerSwitch)
		self.createHost(self.iHost)

	def _addSwitch(self, number, level, switch_list):
		"""
			Create switches.
		"""
		for i in xrange(1, number+1):
			PREFIX = str(level) + "00"
			if i >= 10:
				PREFIX = str(level) + "0"
			switch_list.append(self.addSwitch(PREFIX + str(i)))

	def createCoreLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 1, self.CoreSwitchList)

	def createAggLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 2, self.AggSwitchList)

	def createEdgeLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 3, self.EdgeSwitchList)

	def createHost(self, NUMBER):
		"""
			Create hosts.
		"""
		for i in xrange(1, NUMBER+1):
			if i >= 100:
				PREFIX = "h"
			elif i >= 10:
				PREFIX = "h0"
			else:
				PREFIX = "h00"
			self.HostList.append(self.addHost(PREFIX + str(i), cpu=1.0/float(NUMBER)))

	def createLinks(self, bw_c2a=10, bw_a2e=10, bw_e2h=10):
		"""
			Add network links.
		"""
		# Core to Agg
		end = self.pod/2
		for x in xrange(0, self.iAggLayerSwitch, end):
			for i in xrange(0, end):
				for j in xrange(0, end):
					self.addLink(
						self.CoreSwitchList[i*end+j],
						self.AggSwitchList[x+i],
						bw=bw_c2a)   # use_htb=False

		# Agg to Edge
		for x in xrange(0, self.iAggLayerSwitch, end):
			for i in xrange(0, end):
				for j in xrange(0, end):
					self.addLink(
						self.AggSwitchList[x+i], self.EdgeSwitchList[x+j],
						bw=bw_a2e, delay='1ms')   # use_htb=False

		# Edge to Host
		for x in xrange(0, self.iEdgeLayerSwitch):
			for i in xrange(0, self.density):
				self.addLink(
					self.EdgeSwitchList[x],
					self.HostList[self.density * x + i],
					bw=bw_e2h, delay='2ms')   # use_htb=False

	def set_ovs_protocol_13(self,):
		"""
			Set the OpenFlow version for switches.
		"""
		self._set_ovs_protocol_13(self.CoreSwitchList)
		self._set_ovs_protocol_13(self.AggSwitchList)
		self._set_ovs_protocol_13(self.EdgeSwitchList)

	def _set_ovs_protocol_13(self, sw_list):
		for sw in sw_list:
			# we set the OpenFlow 1.3 to used by OVS switches
			cmd = "sudo ovs-vsctl set bridge %s protocols=OpenFlow13" % sw
			os.system(cmd)


def set_host_ip(net, topo):
	hostlist = []
	for k in xrange(len(topo.HostList)):
		hostlist.append(net.get(topo.HostList[k]))
	i = 1
	j = 1
	for host in hostlist:
		host.setIP("10.%d.0.%d" % (i, j))
		j += 1
		if j == topo.density+1:
			j = 1
			i += 1

def create_subnetList(topo, num):
	"""
		Create the subnet list of the certain Pod.
	"""
	subnetList = []
	remainder = num % (topo.pod/2)
	if topo.pod == 4:
		if remainder == 0:
			subnetList = [num-1, num]
		elif remainder == 1:
			subnetList = [num, num+1]
		else:
			pass
	elif topo.pod == 8:
		if remainder == 0:
			subnetList = [num-3, num-2, num-1, num]
		elif remainder == 1:
			subnetList = [num, num+1, num+2, num+3]
		elif remainder == 2:
			subnetList = [num-1, num, num+1, num+2]
		elif remainder == 3:
			subnetList = [num-2, num-1, num, num+1]
		else:
			pass
	else:
		pass
	return subnetList

def install_proactive(net, topo):
	"""
		Install proactive flow entries into different layers switches
		according to the upstream and downstream directions.
	"""
	
	##########Edge Switch with buckets###########
	for sw in topo.EdgeSwitchList:
		num = int(sw[-2:])

		# Downstream.
		for i in xrange(1, topo.density+1):
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=1000,arp, \
				nw_dst=10.%d.0.%d,actions=output:%d'" % (sw, num, i, topo.pod/2+i)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=1000,ip, \
				nw_dst=10.%d.0.%d,actions=output:%d'" % (sw, num, i, topo.pod/2+i)
			os.system(cmd)

		# Upstream.
		# Install group entries to define ECMP scheduling using static packet header hashing.
		if topo.pod == 4:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=3,type=select,bucket=output:1,bucket=output:2'" % sw
			cmd1 = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=actions:CONTROLLER,bucket=weight:1,output:1'" % sw
			cmd2 = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=2,type=select,bucket=actions:CONTROLLER,bucket=weight:1,output:2'" % sw
		else:
			pass
		os.system(cmd)
		os.system(cmd1)
		os.system(cmd2)
		# Install flow entries.
		Edge_List = [i for i in xrange(1, 1 + topo.pod ** 2 / 2)]
		for i in Edge_List:
			if i != num:
				for j in xrange(1, topo.pod / 2 + 1):
					for k in xrange(1, topo.pod / 2 + 1):
						cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
						'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp,\
						nw_src=10.%d.0.%d,nw_dst=10.%d.0.%d,actions=group:3'" % (sw, num, j, i, k)
						os.system(cmd)
		Edge_List = [i for i in xrange(1, 1 + topo.pod ** 2 / 2)]
		#print "edge_list", Edge_List
		for i in Edge_List:
			if i != num:
				#print "i:", i
				for j in xrange(1, topo.pod / 2 + 1):
					for k in xrange(1, topo.pod / 2):
						#print "k:", k
						cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
						'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip,\
						nw_src=10.%d.0.%d,nw_dst=10.%d.0.%d,actions=group:1'" % (sw, num, j, i, k)
						os.system(cmd)
		Edge_List = [i for i in xrange(1, 1 + topo.pod ** 2 / 2)]
		#print "edge_list", Edge_List
		for i in Edge_List:
			if i != num:
				#print "i:", i
				for j in xrange(1, topo.pod / 2 + 1):
					for k in xrange(2, topo.pod / 2 + 1):
						#print "k:", k
						cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
						'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip,\
						nw_src=10.%d.0.%d,nw_dst=10.%d.0.%d,actions=group:2'" % (sw, num, j, i, k)

	###########Aggregate Switch###########
	for sw in topo.AggSwitchList:
		num = int(sw[-2:])
		subnetList = create_subnetList(topo, num)

		# Downstream.
		k = 1
		for i in subnetList:
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, topo.pod/2+k)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, topo.pod/2+k)
			os.system(cmd)
			k += 1

		# Upstream.
		if topo.pod == 4:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=output:1,bucket=output:2'" % sw
		elif topo.pod == 8:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=output:1,bucket=output:2,\
			bucket=output:3,bucket=output:4'" % sw
		else:
			pass
		os.system(cmd)
		cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
		'table=0,priority=10,arp,actions=group:1'" % sw
		os.system(cmd)
		cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
		'table=0,priority=10,ip,actions=group:1'" % sw
		os.system(cmd)

	#################Core Switch####################
	for sw in topo.CoreSwitchList:
		j = 1
		k = 1
		for i in xrange(1, len(topo.EdgeSwitchList)+1):
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, j)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, j)
			os.system(cmd)
			k += 1
			if k == topo.pod/2 + 1:
				j += 1
				k = 1

def traffic_generation(net, topo):
	"""
		Start the servers on hosts and invoke the traffic generation files
	"""
	for k in xrange(len(topo.HostList)):
		(net.get(topo.HostList[k])).popen("python -m SimpleHTTPServer 8000 &")
		(net.get(topo.HostList[k])).popen("iperf -s &")
	
	file_tra = './OUR3/'+args.traffic_pattern
	CLI(net, script=file_tra)
	time.sleep(120)
	#os.system('killall iperf')
	
def run_experiment(pod, density, ip="127.0.0.1", port=6653, bw_c2a=100, bw_a2e=20, bw_e2h=10):
	"""
		Create the network topology. Then, define the connection with the remote controller.
		Install the proactive flow entries, set IPs and OF version.
		Finally, run the Sieve as a module inside RYU controller, and wait until it discovers the network,
		then, we generate different traffic patterns based on command line arguments passed.
	"""
	# Create Topo.
	topo = Fattree(pod, density)
	topo.createNodes()
	topo.createLinks(bw_c2a=bw_c2a, bw_a2e=bw_a2e, bw_e2h=bw_e2h)

	# 1. Start Mininet.
	CONTROLLER_IP = ip
	CONTROLLER_PORT = port
	net = Mininet(topo=topo, link=TCLink, controller=None, autoSetMacs=True)
	net.addController(
		'controller', controller=RemoteController,
		ip=CONTROLLER_IP, port=CONTROLLER_PORT)
	net.start()

	# Set the OpenFlow version for switches as 1.3.0.
	topo.set_ovs_protocol_13()
	# Set the IP addresses for hosts.
	set_host_ip(net, topo)
	# Install proactive flow entries.
	install_proactive(net, topo)
	#print topo.HostList[0]
	
	k_paths = args.k ** 2 * 3 / 4
	fanout = args.k
	Controller_Ryu = Popen("ryu-manager --observe-links sieve.py --k_paths=%d --weight=bw --fanout=%d" % (k_paths, fanout), shell=True, preexec_fn=os.setsid)

	# Wait until the controller has discovered network topology.
	time.sleep(60)

	traffic_generation(net, topo)
	#CLI(net)
	os.killpg(Controller_Ryu.pid, signal.SIGKILL)
	# Stop Mininet.
	net.stop()

if __name__ == '__main__':
	setLogLevel('info')
	if os.getuid() != 0:
		logging.warning("You are NOT root!")
	elif os.getuid() == 0:
		run_experiment(4, 2)
