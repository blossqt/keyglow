"""Read-only: the real mouse through MouseLink, as the window gets it."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from PySide6.QtCore import QCoreApplication  # noqa: E402
from keyglow import mouselink  # noqa: E402

app = QCoreApplication([])
link = mouselink.MouseLink()
link.start()
end = time.perf_counter() + 6
while link.view.status != mouselink.READY and time.perf_counter() < end:
    app.processEvents()
    time.sleep(0.02)
print(link.view)
link.stop()
