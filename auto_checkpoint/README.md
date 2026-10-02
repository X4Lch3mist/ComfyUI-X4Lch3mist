# Load Checkpoint (Auto VAE/CLIP)

Loads a checkpoint and automatically swaps in an external VAE and/or CLIP, based on a mapping file.

Copy `model_map.example.json` to `model_map.json` in this folder and adjust it. Without a `model_map.json`, the node simply loads VAE and CLIP from the checkpoint.

Entries are matched in this order:

1. Exact checkpoint name, as shown in the dropdown (e.g. `my_checkpoint.safetensors`)
2. Wildcard pattern (e.g. `pony/*`)
3. Architecture, prefixed with `@` (e.g. `@SDXL`, `@SD15`)

`vae` names refer to files in `models/vae`, `clip` names to files in `models/text_encoders`. External CLIP is only supported for SD1.5, SD2 and SDXL checkpoints.

The `info` output shows what was loaded, e.g. `arch=SDXL | match=@SDXL | vae=sdxl_vae.safetensors | clip=checkpoint`.

Category: `X4Lch3mist/loaders`
