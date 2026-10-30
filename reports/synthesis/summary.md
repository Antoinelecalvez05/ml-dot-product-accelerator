# Measured mapped synthesis resources

Tool: `Yosys 0.33 (git sha1 2584903a060)`.

Mapped synthesis primitive counts, before placement and routing. Core including input buffers and controller; excludes board IO/clock buffers.

| Design | Mapping | DSP48 | Logic LUT primitives | Fabric FF | Carry4 | LUT-RAM primitives |
|---|---|---:|---:|---:|---:|---:|
| serial | dsp | 1 | 48 | 56 | 2 | 16 |
| parallel | dsp | 4 | 156 | 112 | 6 | 32 |
| serial | lut | 0 | 276 | 56 | 7 | 16 |
| parallel | lut | 0 | 1102 | 112 | 26 | 32 |

- LUT is the sum of LUT* primitive instances, not packed slices or total physical LUT sites.
- Distributed RAM primitives are listed separately and consume FPGA LUT resources too.
- Fabric FF excludes registers within DSP and RAM primitives.
- Different primitive kinds are not interchangeable units of area.
- No clock-frequency, board timing, energy or power result is measured by this script.

Full primitive counts and source hashes: `summary.json`. Raw commands/logs are adjacent.
