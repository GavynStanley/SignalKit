#!/bin/bash
# Launch SignalKit QML display with correct Qt plugin path
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.venv-qml/bin/activate"
export QT_PLUGIN_PATH="$(python -c 'import os,PySide6; print(os.path.join(os.path.dirname(PySide6.__file__),"Qt","plugins"))')"
exec python "$DIR/signalkit/qml_display.py" "$@"
