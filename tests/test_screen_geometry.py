"""Capture rectangles on a second, scaled monitor (region selection -> screenshot)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeScreen:
    """A monitor right of a 1920 px primary, at 150 % scaling."""
    def __init__(self, x, y, w, h, dpr):
        self.g, self.dpr, self.grabs = QRect(x, y, w, h), dpr, 0

    def geometry(self):
        return self.g

    def devicePixelRatio(self):
        return self.dpr

    def grabWindow(self, _wid):
        self.grabs += 1
        img = QImage(int(self.g.width() * self.dpr), int(self.g.height() * self.dpr), QImage.Format_RGB32)
        img.fill(0xFFFFFF)
        return QPixmap.fromImage(img)


def test_second_scaled_monitor(app, monkeypatch):
    from phraseforge import app as appmod
    from phraseforge.ui.region_select import logical_to_physical
    primary = FakeScreen(0, 0, 1920, 1080, 1.0)
    second = FakeScreen(1920, 0, 1280, 720, 1.5)     # Qt keeps the origin unscaled
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [primary, second]))
    # a 200x100 selection near the second monitor's right edge
    rect = logical_to_physical(second, QRect(1000, 500, 200, 100))
    assert rect == (1920 + 1500, 750, 1920 + 1800, 900)
    png = appmod._grab_screen_png(rect)
    assert png and second.grabs == 1 and primary.grabs == 0    # used to miss the screen
    img = QImage.fromData(png)
    assert (img.width(), img.height()) == (300, 150)
    area = appmod._area_around(1920 + 1700, 800, "line")
    assert area[0] >= 1920 and area[2] == 1920 + 1920 and area[1] >= 0
