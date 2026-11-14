# Offline tile packs (`data/tiles/`)

This folder is what the backend reads in **Mars mode** (`DATA_SOURCE=local`).
Its contents are **not** committed to git (they can weigh GBs); only this
README and `.gitkeep` are.

Layout (identical to the remote-mode disk cache in `backend/cache/tiles/`):

```
data/tiles/
└── {layer_id}/          e.g. viking_mdim21_color
    └── {z}/             native source level
        └── {x}/         column (from -180° eastwards)
            └── {y}.jpg  row (from +90° southwards); .png for PNG layers
```

Two ways to fill it:

1. **Prefetch** with the script (see `backend/README.md`):
   `python -m scripts.prefetch_tiles --layer viking_mdim21_color --max-level 4`
2. **Reuse the cache**: browse the map in Earth mode, then copy
   `backend/cache/tiles/*` here.
