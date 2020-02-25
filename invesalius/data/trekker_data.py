import psutil
import threading
import time

import numpy as np
import wx
from wx.lib.pubsub import pub as Publisher
import vtk
import math

import invesalius.data.bases as db


def compute_seed(position, affine):
    pos_world_aux = np.ones([4, 1])
    # pos_world_aux[:3, -1] = db.flip_x(self.position)[:3]
    pos_world_aux[:3, -1] = position[:3]
    pos_world = np.linalg.inv(affine) @ pos_world_aux
    seed = pos_world.reshape([1, 4])[0, :3]

    return seed[np.newaxis, :]


def simple_direction(trk_n):
    # trk_d = np.diff(trk_n, axis=0, append=2*trk_n[np.newaxis, -1, :])
    trk_d = np.diff(trk_n, axis=0, append=trk_n[np.newaxis, -2, :])
    trk_d[-1, :] *= -1
    # check that linalg norm makes second norm
    # https://stackoverflow.com/questions/21030391/how-to-normalize-an-array-in-numpy
    direction = 255 * np.absolute((trk_d / np.linalg.norm(trk_d, axis=1)[:, None]))
    return direction.astype(int)


def compute_tubes_vtk(trk, direc):
    numb_points = trk.shape[0]
    points = vtk.vtkPoints()
    lines = vtk.vtkCellArray()

    # colors = vtk.vtkFloatArray()
    colors = vtk.vtkUnsignedCharArray()
    colors.SetNumberOfComponents(3)
    # colors.SetName("tangents")

    k = 0
    lines.InsertNextCell(numb_points)
    for j in range(numb_points):
        points.InsertNextPoint(trk[j, :])
        lines.InsertCellPoint(k)
        k += 1

        # if j < (numb_points - 1):
        colors.InsertNextTuple(direc[j, :])
        # else:
        #     colors.InsertNextTuple(direc[j, :])

    trkData = vtk.vtkPolyData()
    trkData.SetPoints(points)
    trkData.SetLines(lines)
    trkData.GetPointData().SetScalars(colors)

    # make it a tube
    trkTube = vtk.vtkTubeFilter()
    trkTube.SetRadius(0.5)
    trkTube.SetNumberOfSides(4)
    trkTube.SetInputData(trkData)
    trkTube.Update()

    return trkTube
    # return trkData


def tracts_actor(out_list, affine_vtk):
    # create tracts only when at least one was computed
    if not out_list.count(None) == len(out_list):
        root = vtk.vtkMultiBlockDataSet()

        for n, tube in enumerate(out_list):
            if tube:
                root.SetBlock(n, tube.GetOutput())

        # https://lorensen.github.io/VTKExamples/site/Python/CompositeData/CompositePolyDataMapper/
        mapper = vtk.vtkCompositePolyDataMapper2()
        mapper.SetInputDataObject(root)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetUserMatrix(affine_vtk)

    return actor


def tracts_root(out_list, root, n_tracts):
    # create tracts only when at least one was computed
    # print("Len outlist in root: ", len(out_list))
    if not out_list.count(None) == len(out_list):
        for n, tube in enumerate(out_list):
            if tube:
                root.SetBlock(n_tracts + n, tube.GetOutput())
                # root.SetBlock(n_tracts + n, tube)

    return root


class ComputeTractsRoot(threading.Thread):
        """
        Thread to update the coordinates with the fiducial points
        co-registration method while the Navigation Button is pressed.
        Sleep function in run method is used to avoid blocking GUI and
        for better real-time navigation
        """

        def __init__(self, tracker, position, affine, affine_vtk, n_tracts):
            threading.Thread.__init__(self)
            # trekker variables
            self.tracker = tracker
            self.position = position
            self.affine = affine
            self.affine_vtk = affine_vtk
            self.n_tracts = n_tracts
            # threading variables
            # self.run_id = run_id
            self._pause_ = False
            # self.start()

        def stop(self):
            self._pause_ = True

        def run(self):

            seed = compute_seed(self.position, self.affine)

            chunck_size = 2
            nchuncks = math.floor(self.n_tracts/chunck_size)
            # print("The nchuncks: ", nchuncks)

            root = vtk.vtkMultiBlockDataSet()
            # n = 1
            n_tracts = 0
            # while n <= nchuncks:
            for n in range(nchuncks):
                # Compute the tracts
                trk_list = []
                for _ in range(chunck_size):
                    self.tracker.seed_coordinates(seed)
                    if self.tracker.run():
                        trk_list.append(self.tracker.run()[0])

                # Transform tracts to array
                trk_arr = [np.asarray(trk_n).T if trk_n else None for trk_n in trk_list]

                # Compute the directions
                trk_dir = [simple_direction(trk_n) for trk_n in trk_arr]

                # Compute the vtk tubes
                out_list = [compute_tubes_vtk(trk_arr_n, trk_dir_n) for trk_arr_n, trk_dir_n in zip(trk_arr, trk_dir)]
                # Compute the actor
                # root = tracts_root(out_list, root, n_tracts)
                root = tracts_actor(out_list, root, n_tracts)
                n_tracts += len(out_list)

                wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, root=root, affine_vtk=self.affine_vtk)

                time.sleep(0.05)
                # n += 1

            if self._pause_:
                return


class ComputeTractsParallel(threading.Thread):
    """
    Thread to update the coordinates with the fiducial points
    co-registration method while the Navigation Button is pressed.
    Sleep function in run method is used to avoid blocking GUI and
    for better real-time navigation
    """

    def __init__(self, tracker, position, affine, affine_vtk, n_tracts):
        threading.Thread.__init__(self)
        # trekker variables
        self.tracker = tracker
        self.position = position
        self.affine = affine
        self.affine_vtk = affine_vtk
        self.n_tracts = n_tracts
        # threading variables
        # self.run_id = run_id
        self._pause_ = False
        self.mutex = threading.Lock()
        # self.start()

    def stop(self):
        # self.mutex.release()
        self._pause_ = True

    def run(self):
        if self._pause_:
            return
        else:
            # self.mutex.acquire()
            # try:
            seed = compute_seed(self.position, self.affine)

            chunck_size = 6
            nchuncks = math.floor(self.n_tracts / chunck_size)
            # print("The chunck_size: ", chunck_size)
            # print("The nchuncks: ", nchuncks)

            root = vtk.vtkMultiBlockDataSet()
            # n = 1
            n_tracts = 0
            # while n <= nchuncks:
            for n in range(nchuncks):
                # Compute the tracts
                trk_list = []
                # for _ in range(chunck_size):
                self.tracker.seed_coordinates(np.repeat(seed, chunck_size, axis=0))
                if self.tracker.run():
                    trk_list.extend(self.tracker.run())

                # Transform tracts to array
                trk_arr = [np.asarray(trk_n).T if trk_n else None for trk_n in trk_list]

                # Compute the directions
                trk_dir = [simple_direction(trk_n) for trk_n in trk_arr]

                # Compute the vtk tubes
                out_list = [compute_tubes_vtk(trk_arr_n, trk_dir_n) for trk_arr_n, trk_dir_n in zip(trk_arr, trk_dir)]
                # Compute the actor
                root = tracts_root(out_list, root, n_tracts)
                n_tracts += len(out_list)

                wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, root=root, affine_vtk=self.affine_vtk)
            # finally:
            #     self.mutex.release()

                # time.sleep(0.05)
                # n += 1


# class ComputeTracts(threading.Thread):
#     """
#     Thread to update the coordinates with the fiducial points
#     co-registration method while the Navigation Button is pressed.
#     Sleep function in run method is used to avoid blocking GUI and
#     for better real-time navigation
#     """
#
#     def __init__(self, tracker, position, affine, affine_vtk, n_tracts):
#         threading.Thread.__init__(self)
#         # trekker variables
#         self.tracker = tracker
#         self.position = position
#         self.affine = affine
#         self.affine_vtk = affine_vtk
#         self.n_tracts = n_tracts
#         # threading variables
#         # self.run_id = run_id
#         self._pause_ = False
#         self.start()
#
#     def stop(self):
#         self._pause_ = True
#
#     def run(self):
#
#         seed = compute_seed(self.position, self.affine)
#
#         # Compute the tracts
#         trk_list = []
#         for n in range(self.n_tracts):
#             self.tracker.set_seeds(seed)
#             if self.tracker.run()[0]:
#                 trk_list.append(self.tracker.run()[0])
#
#         # Transform tracts to array
#         trk_arr = [np.asarray(trk_n).T if trk_n else None for trk_n in trk_list]
#
#         # Compute the directions
#         trk_dir = [simple_direction(trk_n) for trk_n in trk_arr]
#
#         # Compute the vtk tubes
#         out_list = [compute_tubes_vtk(trk_arr_n, trk_dir_n) for trk_arr_n, trk_dir_n in zip(trk_arr, trk_dir)]
#
#         # Compute the actor
#         root = tracts_root(out_list, root, n_tracts)
#
#         wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, actor=actor)
#
#         # time.sleep(1.)
#
#         if self._pause_:
#             return
#         else:
#             return actor


class ComputeTractsSimple:
    """
    Thread to update the coordinates with the fiducial points
    co-registration method while the Navigation Button is pressed.
    Sleep function in run method is used to avoid blocking GUI and
    for better real-time navigation
    """

    def __init__(self, tracker, position, affine, affine_vtk, n_tracts):
        # threading.Thread.__init__(self)
        self.tracker = tracker
        self.position = position
        self.affine = affine
        self.affine_vtk = affine_vtk
        self.n_tracts = n_tracts

    def run(self):

        seed = compute_seed(self.position, self.affine)

        # Compute the tracts
        trk_list = []
        for n in range(self.n_tracts):
            self.tracker.seed_coordinates(seed)
            if self.tracker.run()[0]:
                trk_list.append(self.tracker.run()[0])

        # Transform tracts to array
        trk_arr = [np.asarray(trk_n).T if trk_n else None for trk_n in trk_list]

        # Compute the directions
        trk_dir = [simple_direction(trk_n) for trk_n in trk_arr]

        # Compute the vtk tubes
        out_list = [compute_tubes_vtk(trk_arr_n, trk_dir_n) for trk_arr_n, trk_dir_n in zip(trk_arr, trk_dir)]

        # Compute the actor
        actor = tracts_actor(out_list, affine_vtk=self.affine_vtk)

        return actor


def TractsThread(inp, queue_coord, queue_tract, event):
    tracker, affine, timestamp = inp
    p_old = np.array([[0., 0., 0.]])

    # n_tracts, tracker = inp
    print("Start compute_tracts\n")
    """Pretend we're getting a number from the network."""
    # While the event is not set or the queue is not empty
    # or not queue_tract.full()
    while not event.is_set() or not queue_coord.empty() or not queue_tract.full():
        position, arg = queue_coord.get()
        wx, wy, wz = db.flip_x(position[:3])
        p2 = db.flip_x(position[:3])

        if np.any(arg):
            m_img2 = arg.copy()
            m_img2[:3, -1] = np.asmatrix(db.flip_x_m((m_img2[0, -1], m_img2[1, -1], m_img2[2, -1]))).reshape([3, 1])
            norm_vec = m_img2[:3, 2].reshape([1, 3]).tolist()
            p0 = m_img2[:3, -1].reshape([1, 3]).tolist()
            p2 = [x - timestamp * y for x, y in zip(p0[0], norm_vec[0])]
            wx, wy, wz = p2
            dist = abs(np.linalg.norm(p_old - np.asarray(p2)))
            p_old = np.asarray(p2)

        if dist > 3:
            seed = compute_seed((wx, wy, wz), affine)
            chunck_size = 6
            tracker.seed_coordinates(np.repeat(seed, chunck_size, axis=0))

            if tracker.run():
                trk_list = tracker.run()
        else:
            trk_list = []
        queue_tract.put(trk_list)


def tracts_computation(trk_list, root, n_tracts):
    # Transform tracts to array
    trk_arr = [np.asarray(trk_n).T if trk_n else None for trk_n in trk_list]

    # Compute the directions
    trk_dir = [simple_direction(trk_n) for trk_n in trk_arr]

    # Compute the vtk tubes
    out_list = [compute_tubes_vtk(trk_arr_n, trk_dir_n) for trk_arr_n, trk_dir_n in zip(trk_arr, trk_dir)]

    root = tracts_root(out_list, root, n_tracts)

    return root


def ComputeTractsChunck(affine_vtk, queue, event):

    n_tracts = 0
    root = vtk.vtkMultiBlockDataSet()

    while not event.is_set() or not queue.empty():
    # while not event.is_set():
        # time.sleep(0.5)
        print("Enter split_simple\n")
        # trk_list = queue.get_nowait()
        trk_list = queue.get()
        root = tracts_computation(trk_list, root, n_tracts)
        n_tracts += len(trk_list)

        wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, root=root, affine_vtk=affine_vtk)

        # return actor


class VisualizeTractsDev(threading.Thread):
    """
    Thread to update the coordinates with the fiducial points
    co-registration method while the Navigation Button is pressed.
    Sleep function in run method is used to avoid blocking GUI and
    for better real-time navigation
    """

    def __init__(self, affine_vtk, pipeline, event, sle):
        threading.Thread.__init__(self, name='VisTracts')
        self.affine_vtk = affine_vtk
        self.pipeline = pipeline
        self.event = event
        self.sle = sle

    def run(self):
        n_tracts = 0
        root = vtk.vtkMultiBlockDataSet()
        # Compute the tracts
        while not self.event.is_set():
            if self.pipeline.event_tracts.is_set():
                print("Visualizing tracts")
                trk_list = self.pipeline.get_tracts_list()
                root = tracts_computation(trk_list, root, n_tracts)
                n_tracts += len(trk_list)

                wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, root=root, affine_vtk=self.affine_vtk)
            time.sleep(self.sle)

    # def stop(self):
    #     self.event.set()
    #
    # def __enter__(self):
    #     self.start()
    #     return self
    #
    # def __exit__(self, *args, **kwargs):
    #     self.stop()
    #     print('Force set Thread Sleeper stop_event')


class ComputeTractsDev(threading.Thread):
    """
    Thread to update the coordinates with the fiducial points
    co-registration method while the Navigation Button is pressed.
    Sleep function in run method is used to avoid blocking GUI and
    for better real-time navigation
    """

    def __init__(self, inp, pipeline, event, sle):
        threading.Thread.__init__(self, name='CompTracts')
        self.inp = inp
        self.pipeline = pipeline
        self.event = event
        self.sle = sle

    def run(self):

        tracker, affine, timestamp = self.inp
        p_old = np.array([[0., 0., 0.]])
        # Compute the tracts
        while not self.event.is_set():
            if self.pipeline.event_coreg.is_set():
                # print("Computing tracts")
                position, arg = self.pipeline.get_coord_coreg()
                wx, wy, wz = db.flip_x(position[:3])
                p2 = db.flip_x(position[:3])

                if np.any(arg):
                    m_img2 = arg.copy()
                    m_img2[:3, -1] = np.asmatrix(db.flip_x_m((m_img2[0, -1], m_img2[1, -1], m_img2[2, -1]))).reshape([3, 1])
                    norm_vec = m_img2[:3, 2].reshape([1, 3]).tolist()
                    p0 = m_img2[:3, -1].reshape([1, 3]).tolist()
                    p2 = [x - timestamp * y for x, y in zip(p0[0], norm_vec[0])]
                    wx, wy, wz = p2
                    dist = abs(np.linalg.norm(p_old - np.asarray(p2)))
                    p_old = np.asarray(p2)

                if dist > 3:
                    # seed = compute_seed((wx, wy, wz), affine)
                    seed = np.array([[-8.49, -8.39, 2.5]])
                    chunck_size = 6
                    tracker.seed_coordinates(np.repeat(seed, chunck_size, axis=0))

                    if tracker.run():
                        trk_list = tracker.run()
                        print(f"Tracts list: {len(trk_list)}")
                        self.pipeline.set_tracts_list(trk_list)
                else:
                    trk_list = []
            time.sleep(self.sle)

    # def stop(self):
    #     self.event.set()
    #
    # def __enter__(self):
    #     self.start()
    #     return self
    #
    # def __exit__(self, *args, **kwargs):
    #     self.stop()
    #     print('Force set Thread Sleeper stop_event')

class ComputeVisualize(threading.Thread):
    """
    Thread to update the coordinates with the fiducial points
    co-registration method while the Navigation Button is pressed.
    Sleep function in run method is used to avoid blocking GUI and
    for better real-time navigation
    """

    def __init__(self, inp, affine_vtk, pipeline, event, sle):
        threading.Thread.__init__(self, name='CompVisTracts')
        self.inp = inp
        self.affine_vtk = affine_vtk
        self.pipeline = pipeline
        self.event = event
        self.sle = sle

    def run(self):

        tracker, affine, offset = self.inp
        p_old = np.array([[0., 0., 0.]])
        n_tracts = 0
        root = vtk.vtkMultiBlockDataSet()
        # Compute the tracts
        while not self.event.is_set():
            if self.pipeline.event.is_set():
                # print("Computing tracts")
                position, m_img = self.pipeline.get_message()
                xx, yy, zz = db.flip_x(position[:3])
                p2 = db.flip_x(position[:3])

                if np.any(m_img):
                    m_img[:3, -1] = np.asmatrix(db.flip_x_m((m_img[0, -1], m_img[1, -1], m_img[2, -1]))).reshape([3, 1])
                    norm_vec = m_img[:3, 2].reshape([1, 3]).tolist()
                    p0 = m_img[:3, -1].reshape([1, 3]).tolist()
                    p_new = [x - offset * y for x, y in zip(p0[0], norm_vec[0])]
                    # xx, yy, zz = p2
                    dist = abs(np.linalg.norm(p_old - np.asarray(p_new)))
                    # p_old = np.asarray(p_new)

                    if dist > 3:
                    # while dist < 3:
                        # seed = compute_seed(p_new, affine)
                        seed = np.array([[-8.49, -8.39, 2.5]])
                        chunck_size = 4
                        tracker.seed_coordinates(np.repeat(seed, chunck_size, axis=0))
                        trk_list = tracker.run()

                        if trk_list:
                            root = tracts_computation(trk_list, root, n_tracts)
                            n_tracts += len(trk_list)
                            wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, root=root,
                                         affine_vtk=self.affine_vtk)

            time.sleep(self.sle)


class ComputeVisualizeParallel(threading.Thread):
    """
    Thread to update the coordinates with the fiducial points
    co-registration method while the Navigation Button is pressed.
    Sleep function in run method is used to avoid blocking GUI and
    for better real-time navigation
    """

    def __init__(self, inp, affine_vtk, pipeline, event, sle):
        threading.Thread.__init__(self, name='CompVisTractsParallel')
        self.inp = inp
        self.affine_vtk = affine_vtk
        self.pipeline = pipeline
        self.event = event
        self.sle = sle

    def run(self):

        tracker, affine, offset, n_tracts_total, seed_radius = self.inp
        p_old = np.array([[0., 0., 0.]])
        n_tracts = 0
        ncores = psutil.cpu_count()
        chunck_size = 2*ncores
        root = vtk.vtkMultiBlockDataSet()
        # Compute the tracts
        while not self.event.is_set():
            if self.pipeline.event.is_set():
                # print("Computing tracts")
                position, m_img = self.pipeline.get_message()
                xx, yy, zz = db.flip_x(position[:3])
                p2 = db.flip_x(position[:3])

                if np.any(m_img):
                    m_img[:3, -1] = np.asmatrix(db.flip_x_m((m_img[0, -1], m_img[1, -1], m_img[2, -1]))).reshape([3, 1])
                    norm_vec = m_img[:3, 2].reshape([1, 3]).tolist()
                    p0 = m_img[:3, -1].reshape([1, 3]).tolist()
                    p_new = [x - offset * y for x, y in zip(p0[0], norm_vec[0])]
                    # p_new = [-8.49, -8.39, 2.5]
                    dist = abs(np.linalg.norm(p_old - np.asarray(p_new)))
                    p_old = np.asarray(p_new)

                    seed = compute_seed(p_new, affine)
                    # seed = np.array([[-8.49, -8.39, 2.5]])
                    tracker.seed_coordinates(np.repeat(seed, chunck_size, axis=0))

                    if tracker.run():

                        if dist < seed_radius and n_tracts < n_tracts_total:
                            # Compute the tracts
                            trk_list.extend(tracker.run())
                            # print("Menor que seed_radius com n tracts and dist: ", n_tracts, dist)
                            root = tracts_computation(trk_list, root, n_tracts)
                            n_tracts = len(trk_list)
                            # print("Total new tracts: ", n_tracts)
                            wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, root=root,
                                         affine_vtk=self.affine_vtk)
                        elif dist >= seed_radius:
                            n_tracts = 0
                            trk_list = tracker.run()
                            # print(">>> que seed_radius com n tracts: ", len(trk_list))
                            root = tracts_computation(trk_list, root, n_tracts)
                            n_tracts = len(trk_list)
                            # print("Total tracts: ", n_tracts)
                            wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, root=root,
                                         affine_vtk=self.affine_vtk)

                        # this logic is a bit stupid because it has to compute the actors every loop, better would be
                        # to check the distance and update actors in viewer volume, but that would require that each
                        # loop outputs one actor which is a fiber bundle, and if the dist is < 3 and n_tract > n_total
                        # do nothing


                        # root = tracts_computation(trk_list, root, n_tracts)
                        # print("Total tracts: ", n_tracts)
                        # wx.CallAfter(Publisher.sendMessage, 'Update tracts', flag=True, root=root,
                        #              affine_vtk=self.affine_vtk)

            time.sleep(self.sle)


class Tractography:
    def __init__(self):
        self._n_tracts = None
        self._seed_offset = None
        self._tracker = None

    @property
    def n_tracts(self):
        return self._n_tracts

    @n_tracts.setter
    def n_tracts(self, value):
        self._n_tracts = value

    @property
    def tracker(self):
        return self._tracker

    @tracker.setter
    def tracker(self, value):
        self._tracker = value

    @property
    def seed_offset(self):
        return self._seed_offset

    @seed_offset.setter
    def seed_offset(self, value):
        self._seed_offset = value