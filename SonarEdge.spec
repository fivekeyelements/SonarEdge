# Build with: .venv\Scripts\python.exe -m PyInstaller SonarEdge.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH)
files = ['index.html', 'style.css', 'appearance.css', 'readable.css', 'effects.css', 'visuals.js', 'app.js', 'native.js', 'icon.svg']
data = [(str(root / 'web' / name), 'web') for name in files]
data += [(str(root / 'musicbee/mb_SonarEdge.dll'), 'musicbee')]
data += [(str(root / 'widget/index.html'), 'widget')]
data += collect_data_files('webview')
hidden = collect_submodules('winrt') + [
    'winrt.windows.foundation', 'winrt.windows.foundation.collections',
    'winrt.windows.media', 'winrt.windows.media.control', 'winrt.windows.storage.streams',
    'webview.platforms.winforms', 'webview.platforms.edgechromium',
]
a = Analysis([str(root / 'native_app.py')], pathex=[str(root)], binaries=[], datas=data,
             hiddenimports=hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PyQt5','PyQt6','PySide2','PySide6','tkinter','pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='SonarEdge',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(root / 'assets/SonarEdge.ico'), version=str(root / 'version-info.txt'),
          manifest=str(root / 'assets/SonarEdge.manifest'))
