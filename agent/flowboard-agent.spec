# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for flowboard-agent.
# Build: pyinstaller flowboard-agent.spec --clean

block_cipher = None

a = Analysis(
    ['flowboard/__main__.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # uvicorn dynamic imports
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # sqlmodel / sqlalchemy
        'sqlmodel',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.sqlite.pysqlite',
        # websockets
        'websockets.legacy',
        'websockets.legacy.server',
        # flowboard app entry (uvicorn loads "flowboard.main:app" by string at runtime)
        'flowboard',
        'flowboard.main',
        # flowboard routes (force include in case PyInstaller misses dynamic imports)
        'flowboard.routes.activity',
        'flowboard.routes.auth',
        'flowboard.routes.boards',
        'flowboard.routes.chat',
        'flowboard.routes.edges',
        'flowboard.routes.flow_projects',
        'flowboard.routes.llm',
        'flowboard.routes.media',
        'flowboard.routes.nodes',
        'flowboard.routes.plans',
        'flowboard.routes.projects',
        'flowboard.routes.prompt',
        'flowboard.routes.upload',
        'flowboard.routes.vision',
        'flowboard.routes.references',
        'flowboard.routes.requests',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy.tests', 'IPython', 'jupyter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='flowboard-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='flowboard-agent',
)
