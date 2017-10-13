## Issue related to time resolution/smoothness
#  http://bulletphysics.org/mediawiki-1.5.8/index.php/Stepping_The_World

import pybullet as p
import time
import random
import zmq
import argparse
import os
import json
import numpy as np
import settings
from transforms3d import euler, quaternions
from PhysicsObject import PhysicsObject
from numpy import sin, cos


class PhysRenderer(object):

    def __init__(self, datapath, model_id, framePerSec, debug):
        print("physics renderer", datapath)
        context = zmq.Context()
        self.visn_socket = context.socket(zmq.REQ)
        self.visn_socket.bind("tcp://*:5556")
        
        self.debug_sliders = {}

        if debug:
            p.connect(p.GUI)
            p.configureDebugVisualizer(p.COV_ENABLE_KEYBOARD_SHORTCUTS, 0)
            self._startDebugRoomMap()
        else:
            # Headless training mode
            p.connect(p.DIRECT)

        obj_path = os.path.join(datapath, model_id, "modeldata", 'out_z_up.obj')
        urdf_path = os.path.join(datapath, model_id, "modeldata", 'out_z_up.urdf')

        p.setRealTimeSimulation(0)

        collisionId = p.createCollisionShape(p.GEOM_MESH, fileName=obj_path, meshScale=[1, 1, 1], flags=p.GEOM_FORCE_CONCAVE_TRIMESH)
        visualId = p.createVisualShape(p.GEOM_MESH, fileName=obj_path, meshScale=[1, 1, 1], rgbaColor = [1, 0.2, 0.2, 0.3], specularColor=[0.4, 4.0])

        boundaryUid = p.createMultiBody(baseCollisionShapeIndex = collisionId, baseVisualShapeIndex = visualId)
        
        print("Exterior boundary", boundaryUid)
        
        p.changeVisualShape(boundaryUid, -1, rgbaColor=[1, 0.2, 0.2, 0.3], specularColor=[1, 1, 1])
        #p.changeVisualShape(visualId, -1, rgbaColor=[1, 0.2, 0.2, 0.3])
        
        p.setGravity(0,0,-10)
        p.setRealTimeSimulation(0)
        self.framePerSec = framePerSec

        file_dir = os.path.dirname(__file__)
        #objectUid = p.loadURDF("models/quadrotor.urdf", globalScaling = 0.8)
        self.objectUid = p.loadURDF(os.path.join(file_dir, "models/husky.urdf"), globalScaling = 0.8)

        self.viewMatrix = p.computeViewMatrixFromYawPitchRoll([0, 0, 0], 10, 0, 90, 0, 2)
        self.projMatrix = p.computeProjectionMatrix(-0.01, 0.01, -0.01, 0.01, 0.01, 128)
        p.getCameraImage(256, 256, viewMatrix = self.viewMatrix, projectionMatrix = self.projMatrix)

        self.target_pos = np.array([-4.35, -1.71, 0.8])

    def initialize(self, pose):
        pos, quat_xyzw = pose[0], pose[1]
        v_t = 1             # 1m/s max speed
        v_r = np.pi/5       # 36 degrees/s
        self.cart = PhysicsObject(self.objectUid, p, pos, quat_xyzw, v_t, v_r, self.framePerSec)
        print("Generated cart", self.objectUid)
        #p.setTimeStep(1.0/framePerSec)
        p.setTimeStep(1.0/settings.STEPS_PER_SEC)

    def _camera_init_orientation(self, quat):
        to_z_facing = euler.euler2quat(np.pi/2, np.pi, 0)
        return quaternions.qmult(to_z_facing, quat_wxyz)

    def _setPosViewOrientation(objectUid, pos, rot):
        return

    def _sendPoseToViewPort(self, pose):
        self.visn_socket.send_string(json.dumps(pose))
        self.visn_socket.recv()

    def _getInitialPositionOrientation(self):
        print("waiting to receive initial")
        self.visn_socket.send_string("Initial")
        pos, quat = json.loads(self.visn_socket.recv().decode("utf-8"))
        print("received initial", pos, quat)
        return pos, quat

    def _stepNsteps(self, N, pObject):
        for _ in range(N):
            p.stepSimulation()
            pObject.parseActionAndUpdate()

    def _startDebugRoomMap(self):
        cameraDistSlider  = p.addUserDebugParameter("Distance",0,15,4)
        cameraYawSlider   = p.addUserDebugParameter("Camera Yaw",-180,180,-45)
        cameraPitchSlider = p.addUserDebugParameter("Camera Pitch",-90,90,-30)
        self.debug_sliders = {
            'dist' :cameraDistSlider,
            'yaw'  : cameraYawSlider,
            'pitch': cameraPitchSlider
        }

    def renderOffScreen(self, action, restart=False):
        ## Execute one frame
        #print("physics engine get action", action)
        self.cart.parseActionAndUpdate(action)

        self._stepNsteps(int(settings.STEPS_PER_SEC/self.framePerSec), self.cart)
        pos_xyz, quat_wxyz = self.cart.getViewPosAndOrientation()
        state = {
            'distance_to_target': np.sum(np.square(pos_xyz - self.target_pos))
        }
        return [pos_xyz, quat_wxyz], state

    def renderToScreen(self, action, restart=False):
        
        #self.cart.getUpdateFromKeyboard(restart=restart)
        self.cart.parseActionAndUpdate(action)

        self._stepNsteps(int(settings.STEPS_PER_SEC/self.framePerSec), self.cart)
        pos_xyz, quat_wxyz = self.cart.getViewPosAndOrientation()
        
        cameraDist = p.readUserDebugParameter(self.debug_sliders['dist'])
        cameraYaw  = p.readUserDebugParameter(self.debug_sliders['yaw'])
        cameraPitch = p.readUserDebugParameter(self.debug_sliders['pitch'])
        p.getCameraImage(256, 256, viewMatrix = self.viewMatrix, projectionMatrix = self.projMatrix)
        p.resetDebugVisualizerCamera(cameraDist, cameraYaw, cameraPitch, pos_xyz)
        #time.sleep(0.01)
        state = {
            'distance_to_target': np.sum(np.square(pos_xyz - self.target_pos))
        }
        return [pos_xyz, quat_wxyz], state

    ## DEPRECATED
    def _getCollisionFromUpdate(self):
        message = self.visn_socket.recv().decode("utf-8")

        x, y, z, r_w, r_x, r_y, r_z = map(float, message.split())

        p.resetBasePositionAndOrientation(self.objectUid, [x, y, z], [r_w, r_x, r_y, r_z])
        p.stepSimulation()
        print("step simulation done")
        collisions = p.getContactPoints(boundaryUid, self.objectUid)
        if len(collisions) == 0:
            print("No collisions")
        else:
            print("Collisions!")
        print("collision length", len(collisions))
        self.visn_socket.send_string(str(len(collisions)))
        return

    ## DEPRECATED
    def _synchronizeWithViewPort(self):
        #step
        view_pose = json.loads(self.visn_socket.recv().decode("utf-8"))
        changed = view_pose['changed']
        ## Always send pose from last frame
        pos, rot = p.getBasePositionAndOrientation(self.objectUid)

        print("receiving changed ?", changed)
        print("receiving from view", view_pose['pos'])
        print("original view posit", pos)
        print("receiving from view", view_pose['quat'])
        print("original view posit", rot)
        if changed:
            ## Apply the changes
            new_pos = view_pose['pos']
            new_quat = view_pose['quat']
            #new_quat = [0, 0, 0, 1]
            p.resetBasePositionAndOrientation(self.objectUid, new_pos, new_quat)
        p.stepSimulation()
        pos, rot = p.getBasePositionAndOrientation(self.objectUid)
        print("after applying pose", pos)
        print("")
        #print(changed, pos, rot)
        self.visn_socket.send_string(json.dumps([pos, rot]))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--datapath'  , required = True, help='dataset path')
    parser.add_argument('--model'  , type = str, default = '', help='path of model')
    opt = parser.parse_args()

    framePerSec = 13

    r_physics = PhysRenderer(opt.datapath, opt.model, framePerSec)
    r_physics.initialize(pose_init)
    r_physics.renderToScreen()
        