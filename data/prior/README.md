# Prior Volumes

Place previously translated EPUB files here.
They will be loaded automatically as context when running `python main.py translate`.

Files are loaded in **alphabetical / sorted order**, so name them consistently:

    vol01_vi.epub
    vol02_vi.epub
    vol03_vi.epub
    ...

The last `--context-window` chapters from these volumes are fed as context
to the first chapters of the new volume being translated.
