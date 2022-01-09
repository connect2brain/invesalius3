#!/usr/bin/env python3
#--------------------------------------------------------------------------
# Software:     InVesalius - Software de Reconstrucao 3D de Imagens Medicas
# Copyright:    (C) 2001  Centro de Pesquisas Renato Archer
# Homepage:     http://www.softwarepublico.gov.br
# Contact:      invesalius@cti.gov.br
# License:      GNU - GPL 2 (LICENSE.txt/LICENCA.txt)
#--------------------------------------------------------------------------
#    Este programa e software livre; voce pode redistribui-lo e/ou
#    modifica-lo sob os termos da Licenca Publica Geral GNU, conforme
#    publicada pela Free Software Foundation; de acordo com a versao 2
#    da Licenca.
#
#    Este programa eh distribuido na expectativa de ser util, mas SEM
#    QUALQUER GARANTIA; sem mesmo a garantia implicita de
#    COMERCIALIZACAO ou de ADEQUACAO A QUALQUER PROPOSITO EM
#    PARTICULAR. Consulte a Licenca Publica Geral GNU para obter mais
#    detalhes.
#-------------------------------------------------------------------------

from threading import Thread

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from invesalius.utils import Singleton

class InVesaliusNode(Node): 
    def __init__(self):
        super().__init__("invesalius")

        self._publisher = self.create_publisher(String, "invesalius/example", 10)

        self._control_loop_timer = self.create_timer(1.0, self.control_loop)

    def control_loop(self):
        msg = String()
        msg.data = "Example"

        self.get_logger().info("Publishing to the topic /invesalius/example")
        self._publisher.publish(msg)


class RosConnection(Thread, metaclass=Singleton):
    def __init__(self):
        Thread.__init__(self)
        self.daemon = True

        rclpy.init(args=None)
        self.node = InVesaliusNode() 

    def run(self):
        rclpy.spin(self.node)
        rclpy.shutdown()
