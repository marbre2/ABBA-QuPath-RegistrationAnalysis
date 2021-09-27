from functools import partial
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt5.QtCore import QThreadPool
from traitlets import HasTraits, Instance, directional_link
from vedo import Plotter, Mesh, Points
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from regexport.utils.plotting import plot_cells, PointCloud
from regexport.model import AppState
from regexport.utils.parallel import Task
from regexport.utils.profiling import warn_if_slow
from regexport.views.utils import HasWidget


class PlotterModel(HasTraits):
    atlas_mesh = Instance(Path, allow_none=True)
    points = Instance(PointCloud, default_value=PointCloud())

    def register(self, model: AppState):
        self.model = model
        directional_link(
            (model, 'atlas'),
            (self, 'atlas_mesh'),
            lambda atlas: Path(str(atlas.structures[997]['mesh_filename'])) if atlas is not None else None
        )
        model.observe(self.link_cells_to_points, names=[
            'selected_cell_ids', 'cells', 'selected_colormap', 'column_to_plot',
        ])

    def link_cells_to_points(self, change):
        model = self.model
        if model.cells is None:
            self.points = PointCloud()
            return
        color_col = model.cells[model.column_to_plot]
        points = plot_cells(
            positions=model.cells[['X', 'Y', 'Z']].values * 1000,
            colors=color_col.cat.codes.values if color_col.dtype.name == 'category' else color_col.values,
            indices=model.selected_cell_ids if model.selected_cell_ids is not None else (),
            cmap=self.model.selected_colormap
        )
        self.points = points


class PlotterView(HasWidget):

    def __init__(self, model: PlotterModel):
        self.model = model
        self.item_points = {}
        self._atlas_mesh = None

        widget = QVTKRenderWindowInteractor()
        HasWidget.__init__(self, widget=widget)
        self.plotter = Plotter(qtWidget=widget)

        self.model.observe(self.observe_atlas_mesh, ['atlas_mesh'])
        self.model.observe(self.render, ['points'])

    @property
    def atlas_mesh(self) -> Optional[Mesh]:
        return self._atlas_mesh

    @atlas_mesh.setter
    def atlas_mesh(self, value: Optional[Mesh]):
        self._atlas_mesh = value
        self.render(None)

    @staticmethod
    def load_mesh(filename: Path) -> Mesh:
        return Mesh(
            str(filename),
            alpha=0.1,
            computeNormals=True,
            c=(1., 1., 1.)
        )

    def observe_atlas_mesh(self, change):
        print('saw atlas change')
        if self.model.atlas_mesh is None:
            self._atlas_mesh = Mesh()
        else:
            print('loading')
            worker = Task(self.load_mesh, self.model.atlas_mesh)
            worker.signals.finished.connect(partial(setattr, self, "atlas_mesh"))

            pool = QThreadPool.globalInstance()
            pool.start(worker)


    @warn_if_slow()
    def render(self, change):
        actors = [self._atlas_mesh]
        # box = self._atlas_mesh.box().wireframe().alpha(0.2).color((255, 0, 0))

        # actors.append(box)
        if len((points := self.model.points).coords) > 0:
            coords = points.coords
            colors = (np.hstack((points.colors, points.alphas)) * 255).astype(int)  # alphas needed for fast rendering.
            actors.append(Points(coords, r=3, c=colors))

        self.plotter.show(actors, at=0)
        self.plotter.addInset(self._atlas_mesh, pos=(.9, .9), size=0.1, c='w', draggable=True)
        # note: look at from vedo.applications import SlicerPlotter for inspiration