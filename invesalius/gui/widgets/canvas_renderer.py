# -*- coding: utf-8 -*-
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
#--------------------------------------------------------------------------

import sys

import numpy as np
import wx
import vtk

try:
    from weakref import WeakMethod
except ImportError:
    from weakrefmethod import WeakMethod

from invesalius.data import converters
from invesalius_pubsub import pub as Publisher


class CanvasEvent:
    def __init__(self, event_name, root_event_obj, pos, viewer, renderer,
                 control_down=False, alt_down=False, shift_down=False):
        self.root_event_obj = root_event_obj
        self.event_name = event_name
        self.position = pos
        self.viewer = viewer
        self.renderer = renderer

        self.control_down = control_down
        self.alt_down = alt_down
        self.shift_down = shift_down


class CanvasRendererCTX:
    def __init__(self, viewer, evt_renderer, canvas_renderer, orientation=None):
        """
        A Canvas to render over a vtktRenderer.

        Params:
            evt_renderer: a vtkRenderer which this class is going to watch for
                any render event to update the canvas content.
            canvas_renderer: the vtkRenderer where the canvas is going to be
                added.

        This class uses wx.GraphicsContext to render to a vtkImage.

        TODO: Verify why in Windows the color are strange when using transparency.
        TODO: Add support to evento (ex. click on a square)
        """
        self.viewer = viewer
        self.canvas_renderer = canvas_renderer
        self.evt_renderer = evt_renderer
        self._size = self.canvas_renderer.GetSize()
        self.draw_list = []
        self._ordered_draw_list = []
        self.orientation = orientation
        self.gc = None
        self.last_cam_modif_time = -1
        self.modified = True
        self._drawn = False
        self._init_canvas()

        self._over_obj = None
        self._drag_obj = None
        self._selected_obj = None

        self._callback_events = {
            'LeftButtonPressEvent': [],
            'LeftButtonReleaseEvent': [],
            'LeftButtonDoubleClickEvent': [],
            'MouseMoveEvent': [],
        }

        self._bind_events()

    def _bind_events(self):
        iren = self.viewer.interactor
        iren.Bind(wx.EVT_MOTION, self.OnMouseMove)
        iren.Bind(wx.EVT_LEFT_DOWN, self.OnLeftButtonPress)
        iren.Bind(wx.EVT_LEFT_UP, self.OnLeftButtonRelease)
        iren.Bind(wx.EVT_LEFT_DCLICK, self.OnDoubleClick)
        self.canvas_renderer.AddObserver("StartEvent", self.OnPaint)

    def subscribe_event(self, event, callback):
        ref = WeakMethod(callback)
        self._callback_events[event].append(ref)

    def unsubscribe_event(self, event, callback):
        for n, cb in enumerate(self._callback_events[event]):
            if cb() == callback:
                print('removed')
                self._callback_events[event].pop(n)
                return

    def propagate_event(self, root, event):
        print('propagating', event.event_name, 'from', root)
        node = root
        callback_name = 'on_%s' % event.event_name
        while node:
            try:
                getattr(node, callback_name)(event)
            except AttributeError as e:
                print('errror', node, e)
            node = node.parent

    def _init_canvas(self):
        w, h = self._size
        self._array = np.zeros((h, w, 4), dtype=np.uint8)

        self._cv_image = converters.np_rgba_to_vtk(self._array)

        self.mapper = vtk.vtkImageMapper()
        self.mapper.SetInputData(self._cv_image)
        self.mapper.SetColorWindow(255)
        self.mapper.SetColorLevel(128)

        self.actor = vtk.vtkActor2D()
        self.actor.SetPosition(0, 0)
        self.actor.SetMapper(self.mapper)
        self.actor.GetProperty().SetOpacity(0.99)

        self.canvas_renderer.AddActor2D(self.actor)

        self.rgb = np.zeros((h, w, 3), dtype=np.uint8)
        self.alpha = np.zeros((h, w, 1), dtype=np.uint8)

        self.bitmap = wx.Bitmap.FromRGBA(w, h)
        try:
            self.image = wx.Image(w, h, self.rgb, self.alpha)
        except TypeError:
            self.image = wx.ImageFromBuffer(w, h, self.rgb, self.alpha)

    def _resize_canvas(self, w, h):
        self._array = np.zeros((h, w, 4), dtype=np.uint8)
        self._cv_image = converters.np_rgba_to_vtk(self._array)
        self.mapper.SetInputData(self._cv_image)
        self.mapper.Update()

        self.rgb = np.zeros((h, w, 3), dtype=np.uint8)
        self.alpha = np.zeros((h, w, 1), dtype=np.uint8)

        self.bitmap = wx.Bitmap.FromRGBA(w, h)
        try:
            self.image = wx.Image(w, h, self.rgb, self.alpha)
        except TypeError:
            self.image = wx.ImageFromBuffer(w, h, self.rgb, self.alpha)

        self.modified = True

    def remove_from_renderer(self):
        self.canvas_renderer.RemoveActor(self.actor)
        self.evt_renderer.RemoveObservers("StartEvent")

    def get_over_mouse_obj(self, x, y):
        for n, i in self._ordered_draw_list[::-1]:
            try:
                obj = i.is_over(x, y)
                self._over_obj = obj
                if obj:
                    print("is over at", n, i)
                    return True
            except AttributeError:
                pass
        return False

    def Refresh(self):
        print('Refresh')
        self.modified = True
        self.viewer.interactor.Render()

    def OnMouseMove(self, evt):
        x, y = evt.GetPosition()
        y = self.viewer.interactor.GetSize()[1] - y
        redraw = False

        if self._drag_obj:
            redraw = True
            evt_obj = CanvasEvent('mouse_move', self._drag_obj, (x, y), self.viewer, self.evt_renderer,
                                  control_down=evt.ControlDown(),
                                  alt_down=evt.AltDown(),
                                  shift_down=evt.ShiftDown())
            self.propagate_event(self._drag_obj, evt_obj)
            #  self._drag_obj.mouse_move(evt_obj)
        else:
            was_over = self._over_obj
            redraw = self.get_over_mouse_obj(x, y) or was_over

            if was_over and was_over != self._over_obj:
                try:
                    evt_obj = CanvasEvent('mouse_leave', was_over, (x, y), self.viewer,
                                          self.evt_renderer,
                                          control_down=evt.ControlDown(),
                                          alt_down=evt.AltDown(),
                                          shift_down=evt.ShiftDown())
                    was_over.on_mouse_leave(evt_obj)
                except AttributeError:
                    pass

            if self._over_obj:
                try:
                    evt_obj = CanvasEvent('mouse_enter', self._over_obj, (x, y), self.viewer,
                                          self.evt_renderer,
                                          control_down=evt.ControlDown(),
                                          alt_down=evt.AltDown(),
                                          shift_down=evt.ShiftDown())
                    self._over_obj.on_mouse_enter(evt_obj)
                except AttributeError:
                    pass

        if redraw:
            #  Publisher.sendMessage('Redraw canvas %s' % self.orientation)
            self.Refresh()

        evt.Skip()

    def OnLeftButtonPress(self, evt):
        x, y = evt.GetPosition()
        y = self.viewer.interactor.GetSize()[1] - y
        if self._over_obj and hasattr(self._over_obj, 'on_mouse_move'):
            if hasattr(self._over_obj, 'on_select'):
                try:
                    evt_obj = CanvasEvent('deselect', self._over_obj, (x, y), self.viewer,
                                          self.evt_renderer,
                                          control_down=evt.ControlDown(),
                                          alt_down=evt.AltDown(),
                                          shift_down=evt.ShiftDown())
                    #  self._selected_obj.on_deselect(evt_obj)
                    self.propagate_event(self._selected_obj, evt_obj)
                except AttributeError:
                    pass
                evt_obj = CanvasEvent('select', self._over_obj, (x, y), self.viewer,
                                      self.evt_renderer,
                                      control_down=evt.ControlDown(),
                                      alt_down=evt.AltDown(),
                                      shift_down=evt.ShiftDown())
                #  self._over_obj.on_select(evt_obj)
                self.propagate_event(self._over_obj, evt_obj)
                self._selected_obj = self._over_obj
                self.Refresh()
            self._drag_obj = self._over_obj
        else:
            self.get_over_mouse_obj(x, y)
            if not self._over_obj:
                evt_obj = CanvasEvent('leftclick', None, (x, y), self.viewer,
                                      self.evt_renderer,
                                      control_down=evt.ControlDown(),
                                      alt_down=evt.AltDown(),
                                      shift_down=evt.ShiftDown())
                #  self._selected_obj.on_deselect(evt_obj)
                for cb in self._callback_events['LeftButtonPressEvent']:
                    if cb() is not None:
                        cb()(evt_obj)
                        break
                try:
                    evt_obj = CanvasEvent('deselect', self._over_obj, (x, y), self.viewer,
                                          self.evt_renderer,
                                          control_down=evt.ControlDown(),
                                          alt_down=evt.AltDown(),
                                          shift_down=evt.ShiftDown())
                    #  self._selected_obj.on_deselect(evt_obj)
                    if self._selected_obj.on_deselect(evt_obj):
                        self.Refresh()
                except AttributeError:
                    pass
        evt.Skip()

    def OnLeftButtonRelease(self, evt):
        self._over_obj = None
        self._drag_obj = None
        evt.Skip()

    def OnDoubleClick(self, evt):
        x, y = evt.GetPosition()
        y = self.viewer.interactor.GetSize()[1] - y
        evt_obj = CanvasEvent('double_left_click', None, (x, y), self.viewer, self.evt_renderer,
                              control_down=evt.ControlDown(),
                              alt_down=evt.AltDown(),
                              shift_down=evt.ShiftDown())
        for cb in self._callback_events['LeftButtonDoubleClickEvent']:
            if cb() is not None:
                cb()(evt_obj)
                break
        evt.Skip()

    def OnPaint(self, evt, obj):
        size = self.canvas_renderer.GetSize()
        w, h = size
        if self._size != size:
            self._size = size
            self._resize_canvas(w, h)

        cam_modif_time = self.evt_renderer.GetActiveCamera().GetMTime()
        if (not self.modified) and cam_modif_time == self.last_cam_modif_time:
            return

        self.last_cam_modif_time = cam_modif_time

        self._array[:] = 0

        coord = vtk.vtkCoordinate()

        self.image.SetDataBuffer(self.rgb)
        self.image.SetAlphaBuffer(self.alpha)
        self.image.Clear()
        gc = wx.GraphicsContext.Create(self.image)
        if sys.platform != 'darwin':
            gc.SetAntialiasMode(0)

        self.gc = gc

        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        #  font.SetWeight(wx.BOLD)
        font = gc.CreateFont(font, (0, 0, 255))
        gc.SetFont(font)

        pen = wx.Pen(wx.Colour(255, 0, 0, 128), 2, wx.SOLID)
        brush = wx.Brush(wx.Colour(0, 255, 0, 128))
        gc.SetPen(pen)
        gc.SetBrush(brush)
        gc.Scale(1, -1)

        self._ordered_draw_list = sorted(self._follow_draw_list(), key=lambda x: x[0])
        for l, d in self._ordered_draw_list: #sorted(self.draw_list, key=lambda x: x.layer if hasattr(x, 'layer') else 0):
            d.draw_to_canvas(gc, self)

        gc.Destroy()

        self.gc = None

        if self._drawn:
            self.bitmap = self.image.ConvertToBitmap()
            self.bitmap.CopyToBuffer(self._array, wx.BitmapBufferFormat_RGBA)

        self._cv_image.Modified()
        self.modified = False
        self._drawn = False

    def _follow_draw_list(self):
        out = []
        def loop(node, layer):
            for child in node.children:
                loop(child, layer + child.layer)
                out.append((layer + child.layer, child))

        for element in self.draw_list:
            out.append((element.layer, element))
            if hasattr(element, 'children'):
                loop(element,element.layer)

        return out


    def draw_element_to_array(self, elements, size=None, antialiasing=False, flip=True):
        """
        Draws the given elements to a array.

        Params:
            elements: a list of elements (objects that contains the
                draw_to_canvas method) to draw to a array.
            flip: indicates if it is necessary to flip. In this canvas the Y
                coordinates starts in the bottom of the screen.
        """
        if size is None:
            size = self.canvas_renderer.GetSize()
        w, h = size
        image = wx.Image(w, h)
        image.Clear()

        arr = np.zeros((h, w, 4), dtype=np.uint8)

        gc = wx.GraphicsContext.Create(image)
        if antialiasing:
            gc.SetAntialiasMode(0)

        old_gc = self.gc
        self.gc = gc

        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font = gc.CreateFont(font, (0, 0, 255))
        gc.SetFont(font)

        pen = wx.Pen(wx.Colour(255, 0, 0, 128), 2, wx.SOLID)
        brush = wx.Brush(wx.Colour(0, 255, 0, 128))
        gc.SetPen(pen)
        gc.SetBrush(brush)
        gc.Scale(1, -1)

        for element in elements:
            element.draw_to_canvas(gc, self)

        gc.Destroy()
        self.gc = old_gc

        bitmap = image.ConvertToBitmap()
        bitmap.CopyToBuffer(arr, wx.BitmapBufferFormat_RGBA)

        if flip:
            arr = arr[::-1]

        return arr

    def calc_text_size(self, text, font=None):
        """
        Given an unicode text and a font returns the width and height of the
        rendered text in pixels.

        Params:
            text: An unicode text.
            font: An wxFont.

        Returns:
            A tuple with width and height values in pixels
        """
        if self.gc is None:
            return None
        gc = self.gc

        if font is None:
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)

        _font = gc.CreateFont(font)
        gc.SetFont(_font)

        w = 0
        h = 0
        for t in text.split('\n'):
            _w, _h = gc.GetTextExtent(t)
            w = max(w, _w)
            h += _h
        return w, h

    def draw_line(self, pos0, pos1, arrow_start=False, arrow_end=False, colour=(255, 0, 0, 128), width=2, style=wx.SOLID):
        """
        Draw a line from pos0 to pos1

        Params:
            pos0: the start of the line position (x, y).
            pos1: the end of the line position (x, y).
            arrow_start: if to draw a arrow at the start of the line.
            arrow_end: if to draw a arrow at the end of the line.
            colour: RGBA line colour.
            width: the width of line.
            style: default wx.SOLID.
        """
        if self.gc is None:
            return None
        gc = self.gc

        p0x, p0y = pos0
        p1x, p1y = pos1

        p0y = -p0y
        p1y = -p1y

        pen = wx.Pen(wx.Colour(*[int(c) for c in colour]), width, wx.SOLID)
        pen.SetCap(wx.CAP_BUTT)
        gc.SetPen(pen)

        path = gc.CreatePath()
        path.MoveToPoint(p0x, p0y)
        path.AddLineToPoint(p1x, p1y)
        gc.StrokePath(path)

        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font = gc.CreateFont(font)
        gc.SetFont(font)
        w, h = gc.GetTextExtent("M")

        p0 = np.array((p0x, p0y))
        p3 = np.array((p1x, p1y))
        if arrow_start:
            v = p3 - p0
            v = v / np.linalg.norm(v)
            iv = np.array((v[1], -v[0]))
            p1 = p0 + w*v + iv*w/2.0
            p2 = p0 + w*v + (-iv)*w/2.0

            path = gc.CreatePath()
            path.MoveToPoint(p0)
            path.AddLineToPoint(p1)
            path.MoveToPoint(p0)
            path.AddLineToPoint(p2)
            gc.StrokePath(path)

        if arrow_end:
            v = p3 - p0
            v = v / np.linalg.norm(v)
            iv = np.array((v[1], -v[0]))
            p1 = p3 - w*v + iv*w/2.0
            p2 = p3 - w*v + (-iv)*w/2.0

            path = gc.CreatePath()
            path.MoveToPoint(p3)
            path.AddLineToPoint(p1)
            path.MoveToPoint(p3)
            path.AddLineToPoint(p2)
            gc.StrokePath(path)

        self._drawn = True

    def draw_circle(self, center, radius=2.5, width=2, line_colour=(255, 0, 0, 128), fill_colour=(0, 0, 0, 0)):
        """
        Draw a circle centered at center with the given radius.

        Params:
            center: (x, y) position.
            radius: float number.
            width: line width.
            line_colour: RGBA line colour
            fill_colour: RGBA fill colour.
        """
        if self.gc is None:
            return None
        gc = self.gc

        pen = wx.Pen(wx.Colour(*line_colour), width, wx.SOLID)
        gc.SetPen(pen)

        brush = wx.Brush(wx.Colour(*fill_colour))
        gc.SetBrush(brush)

        cx, cy = center
        cy = -cy

        path = gc.CreatePath()
        path.AddCircle(cx, cy, radius)
        gc.StrokePath(path)
        gc.FillPath(path)
        self._drawn = True

        return (cx, -cy, radius*2, radius*2)

    def draw_ellipse(self, center, width, height, line_width=2, line_colour=(255, 0, 0, 128), fill_colour=(0, 0, 0, 0)):
        """
        Draw a ellipse centered at center with the given width and height.

        Params:
            center: (x, y) position.
            width: ellipse width (float number).
            height: ellipse height (float number)
            line_width: line width.
            line_colour: RGBA line colour
            fill_colour: RGBA fill colour.
        """
        if self.gc is None:
            return None
        gc = self.gc

        pen = wx.Pen(wx.Colour(*line_colour), line_width, wx.SOLID)
        gc.SetPen(pen)

        brush = wx.Brush(wx.Colour(*fill_colour))
        gc.SetBrush(brush)

        cx, cy = center
        xi = cx - width/2.0
        xf = cx + width/2.0
        yi = cy - height/2.0
        yf = cy + height/2.0

        cx -= width/2.0
        cy += height/2.0
        cy = -cy

        path = gc.CreatePath()
        path.AddEllipse(cx, cy, width, height)
        gc.StrokePath(path)
        gc.FillPath(path)
        self._drawn = True

        return (xi, yi, xf, yf)

    def draw_rectangle(self, pos, width, height, line_colour=(255, 0, 0, 128), fill_colour=(0, 0, 0, 0)):
        """
        Draw a rectangle with its top left at pos and with the given width and height.

        Params:
            pos: The top left pos (x, y) of the rectangle.
            width: width of the rectangle.
            height: heigth of the rectangle.
            line_colour: RGBA line colour.
            fill_colour: RGBA fill colour.
        """
        if self.gc is None:
            return None
        gc = self.gc

        px, py = pos
        py = -py
        gc.SetPen(wx.Pen(wx.Colour(*line_colour)))
        gc.SetBrush(wx.Brush(wx.Colour(*fill_colour)))
        gc.DrawRectangle(px, py, width, height)
        self._drawn = True

    def draw_text(self, text, pos, font=None, txt_colour=(255, 255, 255)):
        """
        Draw text.

        Params:
            text: an unicode text.
            pos: (x, y) top left position.
            font: if None it'll use the default gui font.
            txt_colour: RGB text colour
        """
        if self.gc is None:
            return None
        gc = self.gc

        if font is None:
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)

        font = gc.CreateFont(font, txt_colour)
        px, py = pos
        for t in text.split('\n'):
            t = t.strip()
            _py = -py
            _px = px
            gc.SetFont(font)
            gc.DrawText(t, _px, _py)

            w, h = self.calc_text_size(t)
            py -= h

        self._drawn = True

    def draw_text_box(self, text, pos, font=None, txt_colour=(255, 255, 255), bg_colour=(128, 128, 128, 128), border=5):
        """
        Draw text inside a text box.

        Params:
            text: an unicode text.
            pos: (x, y) top left position.
            font: if None it'll use the default gui font.
            txt_colour: RGB text colour
            bg_colour: RGBA box colour
            border: the border size.
        """
        if self.gc is None:
            return None
        gc = self.gc

        if font is None:
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)

        _font = gc.CreateFont(font, txt_colour)
        gc.SetFont(_font)
        w, h = self.calc_text_size(text)

        px, py = pos

        # Drawing the box
        cw, ch = w + border * 2, h + border * 2
        self.draw_rectangle((px, py), cw, ch, bg_colour, bg_colour)

        # Drawing the text
        tpx, tpy = px + border, py - border
        self.draw_text(text, (tpx, tpy), font, txt_colour)
        self._drawn = True

        return px, py, cw, ch

    def draw_arc(self, center, p0, p1, line_colour=(255, 0, 0, 128), width=2):
        """
        Draw an arc passing in p0 and p1 centered at center.

        Params:
            center: (x, y) center of the arc.
            p0: (x, y).
            p1: (x, y).
            line_colour: RGBA line colour.
            width: width of the line.
        """
        if self.gc is None:
            return None
        gc = self.gc
        pen = wx.Pen(wx.Colour(*line_colour), width, wx.SOLID)
        gc.SetPen(pen)

        c = np.array(center)
        v0 = np.array(p0) - c
        v1 = np.array(p1) - c

        c[1] = -c[1]
        v0[1] = -v0[1]
        v1[1] = -v1[1]

        s0 = np.linalg.norm(v0)
        s1 = np.linalg.norm(v1)

        a0 = np.arctan2(v0[1] , v0[0])
        a1 = np.arctan2(v1[1] , v1[0])

        if (a1 - a0) % (np.pi*2) < (a0 - a1) % (np.pi*2):
            sa = a0
            ea = a1
        else:
            sa = a1
            ea = a0

        path = gc.CreatePath()
        path.AddArc(float(c[0]), float(c[1]), float(min(s0, s1)), float(sa), float(ea), True)
        gc.StrokePath(path)
        self._drawn = True

    def draw_polygon(self, points, fill=True, closed=False, line_colour=(255, 255, 255, 255),
                     fill_colour=(255, 255, 255, 255), width=2):

        if self.gc is None:
            return None
        gc = self.gc

        gc.SetPen(wx.Pen(wx.Colour(*line_colour), width, wx.SOLID))
        gc.SetBrush(wx.Brush(wx.Colour(*fill_colour), wx.SOLID))

        if points:
            path = gc.CreatePath()
            px, py = points[0]
            path.MoveToPoint((px, -py))

            for point in points:
                px, py = point
                path.AddLineToPoint((px, -py))

            if closed:
                px, py = points[0]
                path.AddLineToPoint((px, -py))

            gc.StrokePath(path)
            gc.FillPath(path)

            self._drawn = True

        return path


class CanvasHandlerBase(object):
    def __init__(self, parent):
        self.parent = parent
        self.children = []
        self.layer = 0
        self._visible = True

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, value):
        self._visible = value
        for child in self.children:
            child.visible = value

    def _3d_to_2d(self, renderer, pos):
        coord = vtk.vtkCoordinate()
        coord.SetValue(pos)
        px, py = coord.GetComputedDoubleDisplayValue(renderer)
        return px, py

    def add_child(self, child):
        self.children.append(child)

    def draw_to_canvas(self, gc, canvas):
        pass

    def is_over(self, x, y):
        xi, yi, xf, yf = self.bbox
        if xi <= x <= xf and yi <= y <= yf:
            return self
        return None

class TextBox(CanvasHandlerBase):
    def __init__(self, parent,
                 text, position=(0, 0, 0),
                 text_colour=(0, 0, 0, 255),
                 box_colour=(255, 255, 255, 255)):
        super(TextBox, self).__init__(parent)

        self.layer = 0
        self.text = text
        self.text_colour = text_colour
        self.box_colour = box_colour
        self.position = position

        self.children = []

        self.bbox = (0, 0, 0, 0)

        self._highlight = False

        self._last_position = (0, 0, 0)

    def set_text(self, text):
        self.text = text

    def draw_to_canvas(self, gc, canvas):
        if self.visible:
            px, py = self._3d_to_2d(canvas.evt_renderer, self.position)

            x, y, w, h = canvas.draw_text_box(self.text, (px, py),
                                              txt_colour=self.text_colour,
                                              bg_colour=self.box_colour)
            if self._highlight:
                rw, rh = canvas.evt_renderer.GetSize()
                canvas.draw_rectangle((px, py), w, h,
                                      (255, 0, 0, 25),
                                      (255, 0, 0, 25))

            self.bbox = (x, y - h, x + w, y)

    def is_over(self, x, y):
        xi, yi, xf, yf = self.bbox
        if xi <= x <= xf and yi <= y <= yf:
            return self
        return None

    def on_mouse_move(self, evt):
        mx, my = evt.position
        x, y, z = evt.viewer.get_coordinate_cursor(mx, my)
        self.position = [i - j + k  for (i, j, k) in zip((x, y, z), self._last_position, self.position)]

        self._last_position = (x, y, z)

        return True

    def on_mouse_enter(self, evt):
        #  self.layer = 99
        self._highlight = True

    def on_mouse_leave(self, evt):
        #  self.layer = 0
        self._highlight = False

    def on_select(self, evt):
        mx, my = evt.position
        x, y, z = evt.viewer.get_coordinate_cursor(mx, my)
        self._last_position = (x, y, z)


class CircleHandler(CanvasHandlerBase):
    def __init__(self, parent, position, radius=5,
                 line_colour=(255, 255, 255, 255),
                 fill_colour=(0, 0, 0, 0), is_3d=True):

        super(CircleHandler, self).__init__(parent)

        self.layer = 0
        self.position = position
        self.radius = radius
        self.line_colour = line_colour
        self.fill_colour = fill_colour
        self.bbox = (0, 0, 0, 0)
        self.is_3d = is_3d

        self.children = []

        self._on_move_function = None

    def on_move(self, evt_function):
        self._on_move_function = WeakMethod(evt_function)

    def draw_to_canvas(self, gc, canvas):
        if self.visible:
            if self.is_3d:
                px, py = self._3d_to_2d(canvas.evt_renderer, self.position)
            else:
                px, py = self.position
            x, y, w, h = canvas.draw_circle((px, py), self.radius,
                                            line_colour=self.line_colour,
                                            fill_colour=self.fill_colour)
            self.bbox = (x - w/2, y - h/2, x + w/2, y + h/2)

    def on_mouse_move(self, evt):
        mx, my = evt.position
        if self.is_3d:
            x, y, z = evt.viewer.get_coordinate_cursor(mx, my)
            self.position = (x, y, z)

        else:
            self.position = mx, my

        if self._on_move_function and self._on_move_function():
            self._on_move_function()(self, evt)

        return True


class Polygon(CanvasHandlerBase):
    def __init__(self, parent,
                 points=None,
                 fill=True,
                 closed=True,
                 line_colour=(255, 255, 255, 255),
                 fill_colour=(255, 255, 255, 128), width=2,
                 interactive=True, is_3d=True):

        super(Polygon, self).__init__(parent)

        self.layer = 0
        self.children = []

        if points is None:
            self.points = []
        else:
            self.points = points

        self.handlers = []

        self.fill = fill
        self.closed = closed
        self.line_colour = line_colour

        self._path = None

        if self.fill:
            self.fill_colour = fill_colour
        else:
            self.fill_colour = (0, 0, 0, 0)

        self.width = width
        self._interactive = interactive
        self.is_3d = is_3d

    @property
    def interactive(self):
        return self._interactive

    @interactive.setter
    def interactive(self, value):
        self._interactive = value
        for handler in self.handlers:
            handler.visible = value

    def draw_to_canvas(self, gc, canvas):
        if self.visible and self.points:
            if self.is_3d:
                points = [self._3d_to_2d(canvas.evt_renderer, p) for p in self.points]
            else:
                points = self.points
            self._path = canvas.draw_polygon(points, self.fill, self.closed, self.line_colour, self.fill_colour, self.width)

            #  if self.closed:
                #  U, L = self.convex_hull(points, merge=False)
                #  canvas.draw_polygon(U, self.fill, self.closed, self.line_colour, (0, 255, 0, 255), self.width)
                #  canvas.draw_polygon(L, self.fill, self.closed, self.line_colour, (0, 0, 255, 255), self.width)
                #  for p0, p1 in self.get_all_antipodal_pairs(points):
                    #  canvas.draw_line(p0, p1)

        #  if self.interactive:
            #  for handler in self.handlers:
                #  handler.draw_to_canvas(gc, canvas)

    def append_point(self, point):
        handler = CircleHandler(self, point, is_3d=self.is_3d, fill_colour=(255, 0, 0, 255))
        handler.layer = 1
        self.add_child(handler)
        #  handler.on_move(self.on_move_point)
        self.handlers.append(handler)
        self.points.append(point)

    def on_mouse_move(self, evt):
        if evt.root_event_obj is self:
            self.on_mouse_move2(evt)
        else:
            self.points = []
            for handler in self.handlers:
                self.points.append(handler.position)

    def is_over(self, x, y):
        if self.closed and self._path and self._path.Contains(x, -y):
            return self

    def on_mouse_move2(self, evt):
        mx, my = evt.position
        if self.is_3d:
            x, y, z = evt.viewer.get_coordinate_cursor(mx, my)
            new_pos = (x, y, z)
        else:
            new_pos = mx, my

        diff = [i-j for i,j in zip(new_pos, self._last_position)]

        for n, point in enumerate(self.points):
            self.points[n] = tuple((i+j for i,j in zip(diff, point)))
            self.handlers[n].position = self.points[n]

        self._last_position = new_pos

        return True

    def on_mouse_enter(self, evt):
        pass
        #  self.interactive = True
        #  self.layer = 99

    def on_mouse_leave(self, evt):
        pass
        #  self.interactive = False
        #  self.layer = 0

    def on_select(self, evt):
        mx, my = evt.position
        self.interactive = True
        print("on_select", self.interactive)
        if self.is_3d:
            x, y, z = evt.viewer.get_coordinate_cursor(mx, my)
            self._last_position = (x, y, z)
        else:
            self._last_position = (mx, my)

    def on_deselect(self, evt):
        self.interactive = False
        return True

    def convex_hull(self, points, merge=True):
        spoints = sorted(points)
        U = []
        L = []

        _dir = lambda o, a, b:  (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        for p in spoints:
            while len(L) >= 2 and _dir(L[-2], L[-1], p) <= 0:
                L.pop()
            L.append(p)

        for p in reversed(spoints):
            while len(U) >= 2 and _dir(U[-2], U[-1], p) <= 0:
                U.pop()
            U.append(p)

        if merge:
            return U + L
        return U, L

    def get_all_antipodal_pairs(self, points):
        U, L = self.convex_hull(points, merge=False)
        i = 0
        j = len(L) - 1
        while i < len(U) - 1 or j > 0:
            yield U[i], L[j]

            if i == len(U) - 1:
                j -=  1
            elif j == 0:
                i += 1
            elif (U[i+1][1]-U[i][1])*(L[j][0]-L[j-1][0]) > (L[j][1]-L[j-1][1])*(U[i+1][0]-U[i][0]):
                i += 1
            else:
                j -= 1


class Ellipse(CanvasHandlerBase):
    def __init__(self, parent,
                 center,
                 point1, point2,
                 fill=True,
                 line_colour=(255, 255, 255, 255),
                 fill_colour=(255, 255, 255, 128), width=2,
                 interactive=True, is_3d=True):

        super(Ellipse, self).__init__(parent)

        self.children = []
        self.layer = 0

        self.center = center
        self.point1 = point1
        self.point2 = point2

        self.bbox = (0, 0, 0, 0)

        self.fill = fill
        self.line_colour = line_colour
        if self.fill:
            self.fill_colour = fill_colour
        else:
            self.fill_colour = (0, 0, 0, 0)
        self.width = width
        self._interactive = interactive
        self.is_3d = is_3d

        self.handler_1 = CircleHandler(self, self.point1, is_3d=is_3d, fill_colour=(255, 0, 0, 255))
        self.handler_1.layer = 1
        self.handler_2 = CircleHandler(self, self.point2, is_3d=is_3d, fill_colour=(255, 0, 0, 255))
        self.handler_2.layer = 1

        self.add_child(self.handler_1)
        self.add_child(self.handler_2)

    @property
    def interactive(self):
        return self._interactive

    @interactive.setter
    def interactive(self, value):
        self._interactive = value
        self.handler_1.visible = value
        self.handler_2.visible = value

    def draw_to_canvas(self, gc, canvas):
        if self.visible:
            if self.is_3d:
                cx, cy = self._3d_to_2d(canvas.evt_renderer, self.center)
                p1x, p1y = self._3d_to_2d(canvas.evt_renderer, self.point1)
                p2x, p2y = self._3d_to_2d(canvas.evt_renderer, self.point2)
            else:
                cx, cy = self.center
                p1x, p1y = self.point1
                p2x, p2y = self.point2

            width = abs(p1x - cx) * 2.0
            height = abs(p2y - cy) * 2.0

            self.bbox = canvas.draw_ellipse((cx, cy), width,
                                            height, self.width,
                                            self.line_colour,
                                            self.fill_colour)
            #  if self.interactive:
                #  self.handler_1.draw_to_canvas(gc, canvas)
                #  self.handler_2.draw_to_canvas(gc, canvas)

    def set_point1(self, pos):
        self.point1 = pos
        self.handler_1.position = pos

    def set_point2(self, pos):
        self.point2 = pos
        self.handler_2.position = pos

    def on_mouse_move(self, evt):
        if evt.root_event_obj is self:
            self.on_mouse_move2(evt)
        else:
            self.move_p1(evt)
            self.move_p2(evt)

    def move_p1(self, evt):
        pos = self.handler_1.position
        if evt.viewer.orientation == 'AXIAL':
            pos = pos[0], self.point1[1], self.point1[2]
        elif evt.viewer.orientation == 'CORONAL':
            pos = pos[0], self.point1[1], self.point1[2]
        elif evt.viewer.orientation == 'SAGITAL':
            pos = self.point1[0], pos[1], self.point1[2]

        self.set_point1(pos)

        if evt.control_down:
            dist = np.linalg.norm(np.array(self.point1) - np.array(self.center))
            vec = np.array(self.point2) - np.array(self.center)
            vec /= np.linalg.norm(vec)
            point2 = np.array(self.center) + vec * dist

            self.set_point2(tuple(point2))

    def move_p2(self, evt):
        pos = self.handler_2.position
        if evt.viewer.orientation == 'AXIAL':
            pos = self.point2[0], pos[1], self.point2[2]
        elif evt.viewer.orientation == 'CORONAL':
            pos = self.point2[0], self.point2[1], pos[2]
        elif evt.viewer.orientation == 'SAGITAL':
            pos = self.point2[0], self.point2[1], pos[2]

        self.set_point2(pos)

        if evt.control_down:
            dist = np.linalg.norm(np.array(self.point2) - np.array(self.center))
            vec = np.array(self.point1) - np.array(self.center)
            vec /= np.linalg.norm(vec)
            point1 = np.array(self.center) + vec * dist

            self.set_point1(tuple(point1))

    def on_mouse_enter(self, evt):
        #  self.interactive = True
        pass

    def on_mouse_leave(self, evt):
        #  self.interactive = False
        pass

    def is_over(self, x, y):
        xi, yi, xf, yf = self.bbox
        if xi <= x <= xf and yi <= y <= yf:
            return self

    def on_mouse_move2(self, evt):
        mx, my = evt.position
        if self.is_3d:
            x, y, z = evt.viewer.get_coordinate_cursor(mx, my)
            new_pos = (x, y, z)
        else:
            new_pos = mx, my

        diff = [i-j for i,j in zip(new_pos, self._last_position)]

        self.center = tuple((i+j for i,j in zip(diff, self.center)))
        self.set_point1(tuple((i+j for i,j in zip(diff, self.point1))))
        self.set_point2(tuple((i+j for i,j in zip(diff, self.point2))))

        self._last_position = new_pos

        return True

    def on_select(self, evt):
        self.interactive = True
        mx, my = evt.position
        if self.is_3d:
            x, y, z = evt.viewer.get_coordinate_cursor(mx, my)
            self._last_position = (x, y, z)
        else:
            self._last_position = (mx, my)

    def on_deselect(self, evt):
        self.interactive = False
        return True
