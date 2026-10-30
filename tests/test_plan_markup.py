from pathlib import Path

from PIL import Image

from sitescribe import plan_markup
from sitescribe.models import PIN_DONE, PIN_OPEN, Observation, PlanPin, PlanSheet, Project


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def test_pins_red_while_open_gray_otherwise(tmp_path):
    sheet_png = tmp_path / "s201.png"
    Image.new("RGB", (2000, 1000), "white").save(sheet_png)
    sheet = PlanSheet("S-201", Path("plans.pdf"), 0, sheet_png, 2000, 1000)
    other = PlanSheet("S-202", Path("plans.pdf"), 1, sheet_png, 2000, 1000)
    project = Project(name="Job", plans=[sheet, other], observations=[
        Observation(action_item="Fix it.", number=3, pin=PlanPin(sheet.id, 0.5, 0.5)),
        Observation(action_item="Fix it.", number=3, pin=PlanPin(sheet.id, 0.5, 0.5)),
        Observation(action_item="Fixed.", closed=True, number=4, pin=PlanPin(sheet.id, 0.8, 0.7)),
        Observation(number=5, pin=PlanPin(other.id, 0.25, 0.25)),
        Observation(number=6),
    ])

    out = plan_markup.sheet_image_with_pins(project, sheet.id, tmp_path / "out" / "s201.png")

    assert out == tmp_path / "out" / "s201.png"
    with Image.open(out) as image:
        assert image.size == (2000, 1000)
        radius = round(1000 * 0.018)
        # just inside the circle, clear of the white number in the middle
        assert image.getpixel((1000, 500 + radius - 4)) == _rgb(PIN_OPEN)
        assert image.getpixel((1600, 700 + radius - 4)) == _rgb(PIN_DONE)
        # the other sheet's pin is not on this one
        assert image.getpixel((500, 250 + radius - 4)) == (255, 255, 255)
        # legend in the top-left corner
        assert image.getpixel((radius + round(radius * 0.7), radius + round(radius * 0.7))) == \
            _rgb(PIN_OPEN)
