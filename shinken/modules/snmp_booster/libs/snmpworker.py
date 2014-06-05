from threading import Thread
import time

from shinken.log import logger
from pysnmp.entity.rfc3413.oneliner import cmdgen


class SNMPWorker(Thread):
    def __init__(self, snmp_task_queue):
        Thread.__init__(self)
        self.cmdgen = cmdgen.AsynCommandGenerator()
        self.snmp_task_queue = snmp_task_queue
        self.must_run = False

    
    def run(self):
        self.must_run = True
        while self.must_run:
            task_prepared = 0
#            print "QUEUE_LEN", self.snmp_task_queue.empty()
            while (not self.snmp_task_queue.empty()) and task_prepared <= 2000:
                task_prepared += 1
                snmp_task = self.snmp_task_queue.get()
                print "NEW TASK", snmp_task
                if snmp_task['type'] == 'bulk':
                    snmp_task['data']
                    # dict keys:
                        # authData: cmdgen.CommunityData('ERS8600-1')
                        # transportTarget: cmdgen.UdpTransportTarget((transportTarget, 1161))
                        # nonRepeaters: 0
                        # maxRepetitions: 
                        # varNames: ( '1.3.6.1.2.1.2.2.1.2.0', )
                        # cbInfo: (cbFun, None)
                    self.cmdgen.asyncBulkCmd(**snmp_task['data'])
                else:
                    snmp_task['data']
                    # dict keys:
                        # authData: cmdgen.CommunityData('ERS8600-1')
                        # transportTarget: cmdgen.UdpTransportTarget((transportTarget, 1161))
                        # varNames: ( '1.3.6.1.2.1.2.2.1.2.0', )
                        # cbInfo: (cbFun, None)
                    self.cmdgen.asyncNextCmd(**snmp_task['data'])
                self.snmp_task_queue.task_done()

            if task_prepared > 0:
                self.cmdgen.snmpEngine.transportDispatcher.runDispatcher()
            time.sleep(0.1)


    def stop_worker(self):
        self.must_run = False
